"""Additional unit tests for agent_core.scheduler.scheduler.

Focused on error branches, stale/corrupt lock handling, quiet-hour edge
cases, catch-up detection, and application reminder checks.  No real DB,
network, daemon process, or timer is used.
"""

import asyncio
import logging
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_core.scheduler import scheduler as S

# ---------------------------------------------------------------------------
# _load / _backup_corrupt error branches
# ---------------------------------------------------------------------------


def test_load_generic_exception_resets_to_defaults(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "STATE_FILE", state)

    def boom(_f):
        raise RuntimeError("read failed")

    monkeypatch.setattr(S.json, "load", boom)

    assert S._load()["enabled"] is False


def test_backup_corrupt_move_failure_is_swallowed(tmp_path, monkeypatch, caplog):
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(S, "STATE_FILE", state)

    def fail_move(src, dst):
        raise OSError("denied")

    monkeypatch.setattr(shutil, "move", fail_move)

    S._backup_corrupt()  # must not raise
    assert "Could not back up corrupt state file" in caplog.text


# ---------------------------------------------------------------------------
# _pid_alive
# ---------------------------------------------------------------------------


def test_pid_alive_unix_success_and_lookup_error(monkeypatch):
    monkeypatch.setattr(S.os, "name", "posix")
    killed = []

    def fake_kill(pid, sig):
        killed.append(pid)

    monkeypatch.setattr(S.os, "kill", fake_kill)
    assert S._pid_alive(42) is True
    assert killed == [42]

    def lookup_error(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(S.os, "kill", lookup_error)
    assert S._pid_alive(42) is False


def test_pid_alive_unix_oserror_returns_false(monkeypatch):
    monkeypatch.setattr(S.os, "name", "posix")

    def permission_error(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(S.os, "kill", permission_error)
    assert S._pid_alive(42) is False


def test_pid_alive_nt_success_and_missing(monkeypatch):
    class _Kernel32:
        def __init__(self):
            self.closed = []

        def OpenProcess(self, access, inherit, pid):
            return 1 if pid == 100 else 0

        def CloseHandle(self, handle):
            self.closed.append(handle)

    import types

    monkeypatch.setattr(S.os, "name", "nt")
    fake_ctypes = types.SimpleNamespace(windll=SimpleNamespace(kernel32=_Kernel32()))
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert S._pid_alive(100) is True
    assert S._pid_alive(200) is False


# ---------------------------------------------------------------------------
# acquire_lock / release_lock edge cases
# ---------------------------------------------------------------------------


def test_acquire_lock_takes_over_stale_lock(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    lock.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(S, "LOCK_FILE", lock)
    monkeypatch.setattr(S, "_pid_alive", lambda pid: False)

    assert S.acquire_lock() is True
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_lock_overwrites_corrupt_lock(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    lock.write_text("not-a-pid", encoding="utf-8")
    monkeypatch.setattr(S, "LOCK_FILE", lock)

    assert S.acquire_lock() is True
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_lock_write_failure_returns_false(tmp_path, monkeypatch):
    class _Lock:
        def __init__(self):
            self.parent = tmp_path
            self.exists_result = False

        def exists(self):
            return self.exists_result

        def write_text(self, text):
            raise OSError("denied")

    monkeypatch.setattr(S, "LOCK_FILE", _Lock())
    assert S.acquire_lock() is False


def test_release_lock_does_not_remove_foreign_pid(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    lock.write_text("999", encoding="utf-8")
    monkeypatch.setattr(S, "LOCK_FILE", lock)

    S.release_lock()

    assert lock.exists()


def test_release_lock_unlink_error_swallowed(monkeypatch):
    class _Lock:
        def exists(self):
            return True

        def read_text(self):
            return str(os.getpid())

        def unlink(self):
            raise OSError("denied")

    monkeypatch.setattr(S, "LOCK_FILE", _Lock())

    S.release_lock()  # must not raise


# ---------------------------------------------------------------------------
# schedule status/on/off helpers
# ---------------------------------------------------------------------------


def test_schedule_status_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save(
        {
            "enabled": True,
            "last_run": "2026-01-01T00:00:00+00:00",
            "runs": 7,
            "directions": ["equipment_amr"],
            "last_error": "boom",
        }
    )

    status = S.schedule_status()

    assert status["enabled"] is True
    assert status["last_run"] == "2026-01-01T00:00:00+00:00"
    assert status["runs"] == 7
    assert status["directions"] == ["equipment_amr"]
    assert status["last_error"] == "boom"


def test_schedule_on_and_off(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    cfg = SimpleNamespace(schedule=SimpleNamespace(directions=["d1", "d2"]))

    on_state = S.schedule_on(cfg)
    assert on_state["enabled"] is True
    assert on_state["directions"] == ["d1", "d2"]

    off_state = S.schedule_off()
    assert off_state["enabled"] is False


# ---------------------------------------------------------------------------
# run_scheduled_search edge cases
# ---------------------------------------------------------------------------


def _scheduler_config(quiet_hours=None, interval_hours=6, directions=None, reminder_days=3):
    return SimpleNamespace(
        schedule=SimpleNamespace(
            quiet_hours=quiet_hours or [],
            interval_hours=interval_hours,
            directions=directions or ["equipment_amr"],
            reminder_days=reminder_days,
        )
    )


def _fake_db():
    return SimpleNamespace(commit=MagicMock())


def _run_search(state, cfg, monkeypatch, tmp_path, caplog, run_result=None):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save(state)
    captured = {}

    async def fake_run_pipeline(config, llm_provider, stages=None, **kwargs):
        captured["stages"] = stages
        captured["directions"] = kwargs.get("directions")
        return run_result if run_result is not None else {"matched": []}

    monkeypatch.setattr("agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)
    db = _fake_db()
    asyncio.run(S.run_scheduled_search(cfg, None, db))
    return S._load(), captured, db


def test_run_scheduled_search_catchup_for_old_last_run(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    cfg = _scheduler_config()
    old = (datetime.now(UTC) - timedelta(hours=20)).isoformat()
    state, captured, _ = _run_search(
        {
            "enabled": True,
            "last_run": old,
            "runs": 0,
            "directions": ["equipment_amr"],
            "last_error": None,
        },
        cfg,
        monkeypatch,
        tmp_path,
        caplog,
    )

    assert state["runs"] == 1
    assert captured["stages"] == ["search", "filter", "enrich", "match"]
    assert "catch-up" in caplog.text


def test_run_scheduled_search_catchup_for_naive_last_run(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    cfg = _scheduler_config()
    old_naive = (datetime.now(UTC) - timedelta(hours=20)).replace(tzinfo=None).isoformat()
    state, _, _ = _run_search(
        {
            "enabled": True,
            "last_run": old_naive,
            "runs": 0,
            "directions": ["equipment_amr"],
            "last_error": None,
        },
        cfg,
        monkeypatch,
        tmp_path,
        caplog,
    )

    assert state["runs"] == 1
    assert "catch-up" in caplog.text


def test_run_scheduled_search_bad_last_run_is_catchup(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    cfg = _scheduler_config()
    state, captured, _ = _run_search(
        {
            "enabled": True,
            "last_run": "not-a-timestamp",
            "runs": 0,
            "directions": ["equipment_amr"],
            "last_error": None,
        },
        cfg,
        monkeypatch,
        tmp_path,
        caplog,
    )

    assert state["runs"] == 1
    assert captured["directions"] == ["equipment_amr"]
    assert "catch-up" in caplog.text


def test_run_scheduled_search_quiet_hours_wrapping_skip(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    real_datetime = datetime

    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return real_datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            return real_datetime(2026, 1, 1, 23, 0, tzinfo=timezone(timedelta(hours=8)))

    monkeypatch.setattr(S, "datetime", FakeDatetime)
    cfg = _scheduler_config(quiet_hours=[23, 8])

    state = {
        "enabled": True,
        "last_run": None,
        "runs": 0,
        "directions": ["equipment_amr"],
        "last_error": None,
    }
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save(state)
    asyncio.run(S.run_scheduled_search(cfg, None, _fake_db()))

    assert S._load()["runs"] == 0
    assert "Quiet hours" in caplog.text


def test_run_scheduled_search_reminder_failure_does_not_fail_search(tmp_path, monkeypatch, caplog):
    cfg = _scheduler_config()
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save(
        {
            "enabled": True,
            "last_run": None,
            "runs": 0,
            "directions": ["equipment_amr"],
            "last_error": None,
        }
    )

    async def fake_run_pipeline(config, llm_provider, stages=None, **kwargs):
        return {"matched": []}

    monkeypatch.setattr("agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)

    def boom(config, db):
        raise RuntimeError("reminder failed")

    monkeypatch.setattr(S, "check_application_reminders", boom)

    asyncio.run(S.run_scheduled_search(cfg, None, _fake_db()))

    s = S._load()
    assert s["runs"] == 1
    assert "Application reminder check failed" in caplog.text


# ---------------------------------------------------------------------------
# check_application_reminders
# ---------------------------------------------------------------------------


def test_check_application_reminders_recent_reminder_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save(
        {
            "enabled": True,
            "last_reminder_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
    )
    db = MagicMock()

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 0
    db.execute.assert_not_called()


def test_check_application_reminders_bad_last_reminder_resets(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({"last_reminder_at": "not-a-date", "reminder_days": 3})
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (0,)

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 0
    assert "Bad last_reminder_at" in caplog.text
    assert db.execute.call_args.args[0].startswith("SELECT COUNT(*)")


def test_check_application_reminders_old_naive_last_reminder_proceeds(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    old_naive = (datetime.now(UTC) - timedelta(days=10)).replace(tzinfo=None).isoformat()
    S._save({"last_reminder_at": old_naive, "reminder_days": 3})
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (0,)

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 0
    assert db.execute.call_args.args[0].startswith("SELECT COUNT(*)")


def test_check_application_reminders_db_error_returns_zero(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({})
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db down")

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 0
    assert "Application reminder query failed" in caplog.text


def test_check_application_reminders_count_zero_no_notify(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({})
    notified = []

    def fake_notify(count):
        notified.append(count)

    monkeypatch.setattr("agent_core.notify.windows_toast.notify_application_reminder", fake_notify)
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (0,)

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 0
    assert notified == []
    assert S._load().get("last_reminder_at") is None


def test_check_application_reminders_notifies_and_saves_state(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({})
    notified = []
    monkeypatch.setattr(
        "agent_core.notify.windows_toast.notify_application_reminder",
        lambda count: notified.append(count),
    )
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (3,)

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 3
    assert notified == [3]
    assert S._load()["last_reminder_at"] is not None


def test_check_application_reminders_notify_failure_returns_count(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({})

    def boom(count):
        raise RuntimeError("toast failed")

    monkeypatch.setattr("agent_core.notify.windows_toast.notify_application_reminder", boom)
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (2,)

    count = S.check_application_reminders(_scheduler_config(), db)

    assert count == 2
    assert "notify_application_reminder failed" in caplog.text
    assert S._load().get("last_reminder_at") is None
