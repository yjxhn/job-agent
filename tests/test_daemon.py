"""Unit tests for dashboard daemon lifecycle helpers."""

from agent_core.server import daemon


def test_stop_dashboard_no_pid_file(monkeypatch):
    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: False)
    daemon._stop_dashboard()  # should not raise


def test_stop_dashboard_stale_pid_file(monkeypatch):
    unlinked = []

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "not-an-int"

    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: _FakeFile())
    monkeypatch.setattr("agent_core.server.daemon.os.unlink", lambda p: unlinked.append(p))
    daemon._stop_dashboard()
    assert len(unlinked) == 1 and unlinked[0].endswith("dashboard.pid")


def test_ensure_dashboard_already_running(monkeypatch):
    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "123"

    monkeypatch.setattr(
        "agent_core.server.daemon.os.path.exists", lambda p: p.endswith("dashboard.pid")
    )
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: _FakeFile())
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")
    monkeypatch.setattr("agent_core.server.daemon.os.kill", lambda _pid, _sig: None)
    assert daemon._ensure_dashboard() is True


def test_ensure_dashboard_stale_pid_starts(monkeypatch):
    from types import SimpleNamespace

    written = []

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "999"

        def write(self, s):
            written.append(s)

    monkeypatch.setattr(
        "agent_core.server.daemon.os.path.exists", lambda p: p.endswith("dashboard.pid")
    )
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: _FakeFile())
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")

    def _kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("agent_core.server.daemon.os.kill", _kill)
    monkeypatch.setattr(
        "agent_core.server.daemon.subprocess.Popen",
        lambda *_a, **_k: SimpleNamespace(pid=456),
    )
    monkeypatch.setattr("agent_core.server.daemon.os.makedirs", lambda *_a, **_k: None)
    assert daemon._ensure_dashboard() is False
    assert any("456" in s for s in written)


def test_stop_dashboard_unix_kill(monkeypatch):
    unlinked = []
    killed = []

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "123"

    monkeypatch.setattr("agent_core.server.daemon.os.path.exists", lambda _p: True)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: _FakeFile())
    monkeypatch.setattr("agent_core.server.daemon.sys.platform", "linux")
    monkeypatch.setattr("agent_core.server.daemon.os.kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr("agent_core.server.daemon.os.unlink", lambda p: unlinked.append(p))
    daemon._stop_dashboard()
    assert killed == [123]
    assert len(unlinked) == 1 and unlinked[0].endswith("dashboard.pid")
