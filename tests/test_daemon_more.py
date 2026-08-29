"""Additional unit tests for agent_core.server.daemon.

These cover the Windows and stale-PID branches that the original
tests/test_daemon.py does not exercise.  All subprocess/ctypes/file
operations are mocked — no real daemon process is started.
"""

import sys
from types import SimpleNamespace

from agent_core.server import daemon


class _FakeFile:
    def __init__(self, content: str = ""):
        self.content = content
        self.writes: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> str:
        return self.content

    def write(self, text: str) -> int:
        self.writes.append(text)
        return len(text)


def _fake_ctypes(monkeypatch, kernel32):
    """Install a fake ctypes module with a scriptable kernel32 object."""
    import types

    fake_ctypes = types.SimpleNamespace(windll=SimpleNamespace(kernel32=kernel32))
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    return fake_ctypes


def _fake_open(monkeypatch):
    files: list[_FakeFile] = []

    def factory(*args, **kwargs):
        f = _FakeFile()
        files.append(f)
        return f

    monkeypatch.setattr("builtins.open", factory)
    return files


# ---------------------------------------------------------------------------
# _ensure_dashboard
# ---------------------------------------------------------------------------


def test_ensure_dashboard_no_pid_file_starts(monkeypatch):
    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: False)
    files = _fake_open(monkeypatch)
    procs = []
    monkeypatch.setattr(
        "agent_core.server.daemon.subprocess.Popen",
        lambda *a, **kw: procs.append((a, kw)) or SimpleNamespace(pid=777),
    )
    monkeypatch.setattr("agent_core.server.daemon.os.makedirs", lambda *a, **kw: None)
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")

    assert daemon._ensure_dashboard(port=9000) is False
    assert len(procs) == 1
    assert procs[0][1]["creationflags"] == 0
    assert "--port" in procs[0][0][0]
    assert any("777" in w for f in files for w in f.writes)


def test_ensure_dashboard_win32_already_running(monkeypatch):
    class _Kernel32:
        def __init__(self):
            self.opened = []
            self.closed = []

        def OpenProcess(self, access, inherit, pid):
            self.opened.append((access, pid))
            return 123

        def CloseHandle(self, handle):
            self.closed.append(handle)

    kernel32 = _Kernel32()
    _fake_ctypes(monkeypatch, kernel32)
    monkeypatch.setattr(
        "agent_core.server.daemon.os.path.exists", lambda p: p.endswith("dashboard.pid")
    )
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("123"))
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "win32")

    assert daemon._ensure_dashboard() is True
    assert kernel32.opened == [(0x0400, 123)]
    assert kernel32.closed == [123]


def test_ensure_dashboard_win32_stale_pid_starts(monkeypatch):
    class _Kernel32:
        def OpenProcess(self, access, inherit, pid):
            return 0  # no such process

        def CloseHandle(self, handle):
            pass

    _fake_ctypes(monkeypatch, _Kernel32())
    procs = []
    files: list[_FakeFile] = []

    def _open(*args, **kwargs):
        f = _FakeFile("123" if not files else "")
        files.append(f)
        return f

    monkeypatch.setattr("builtins.open", _open)
    monkeypatch.setattr(
        "agent_core.server.daemon.subprocess.Popen",
        lambda *a, **kw: procs.append(kw) or SimpleNamespace(pid=888),
    )
    monkeypatch.setattr("agent_core.server.daemon.os.makedirs", lambda *a, **kw: None)
    monkeypatch.setattr(
        "agent_core.server.daemon.os.path.exists", lambda p: p.endswith("dashboard.pid")
    )
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "win32")

    assert daemon._ensure_dashboard() is False
    assert len(procs) == 1
    # Windows detached-process flags must be passed through.
    assert procs[0]["creationflags"] != 0
    assert any("888" in w for f in files for w in f.writes)


def test_ensure_dashboard_bad_pid_file_starts(monkeypatch):
    """A non-integer PID file is stale and the dashboard is started."""
    monkeypatch.setattr(
        "agent_core.server.daemon.os.path.exists", lambda p: p.endswith("dashboard.pid")
    )
    files: list[_FakeFile] = []
    procs = []
    monkeypatch.setattr(
        "agent_core.server.daemon.subprocess.Popen",
        lambda *a, **kw: procs.append(kw) or SimpleNamespace(pid=999),
    )
    monkeypatch.setattr("agent_core.server.daemon.os.makedirs", lambda *a, **kw: None)
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")
    monkeypatch.setattr("agent_core.server.daemon.os.kill", lambda pid, sig: None)

    # First call to open returns the pid file containing junk; subsequent
    # calls return the log/pid write files.
    contents = iter(["not-an-int", "", ""])

    def _open(*args, **kwargs):
        f = _FakeFile(next(contents))
        files.append(f)
        return f

    monkeypatch.setattr("builtins.open", _open)

    assert daemon._ensure_dashboard() is False
    assert len(procs) == 1
    assert any("999" in w for f in files for w in f.writes)


# ---------------------------------------------------------------------------
# _stop_dashboard
# ---------------------------------------------------------------------------


def test_stop_dashboard_win32_terminates(monkeypatch):
    class _Kernel32:
        def __init__(self):
            self.terminated = []
            self.closed = []

        def OpenProcess(self, access, inherit, pid):
            self.opened_access = access
            return 456

        def TerminateProcess(self, handle, code):
            self.terminated.append((handle, code))

        def CloseHandle(self, handle):
            self.closed.append(handle)

    kernel32 = _Kernel32()
    _fake_ctypes(monkeypatch, kernel32)
    unlinked = []
    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("456"))
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "win32")
    monkeypatch.setattr("agent_core.server.daemon.os.unlink", lambda p: unlinked.append(p))

    daemon._stop_dashboard()

    assert kernel32.opened_access == 0x0001
    assert kernel32.terminated == [(456, 0)]
    assert kernel32.closed == [456]
    assert unlinked == ["data/dashboard.pid"]


def test_stop_dashboard_win32_already_stopped(monkeypatch):
    class _Kernel32:
        def OpenProcess(self, access, inherit, pid):
            return 0

        def CloseHandle(self, handle):
            pass

    _fake_ctypes(monkeypatch, _Kernel32())
    unlinked = []
    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("456"))
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "win32")
    monkeypatch.setattr("agent_core.server.daemon.os.unlink", lambda p: unlinked.append(p))

    daemon._stop_dashboard()  # must not raise
    assert unlinked == ["data/dashboard.pid"]


def test_stop_dashboard_unix_process_not_found(monkeypatch):
    unlinked = []

    def _kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("123"))
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")
    monkeypatch.setattr("agent_core.server.daemon.os.kill", _kill)
    monkeypatch.setattr("agent_core.server.daemon.os.unlink", lambda p: unlinked.append(p))

    daemon._stop_dashboard()  # must not raise
    assert unlinked == ["data/dashboard.pid"]


def test_stop_dashboard_cleanup_unlink_error_swallowed(monkeypatch):
    """If unlink fails while cleaning a stale PID file, it is swallowed."""
    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("not-an-int"))
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")

    def _unlink(p):
        raise OSError("denied")

    monkeypatch.setattr("agent_core.server.daemon.os.unlink", _unlink)

    daemon._stop_dashboard()  # must not raise
