"""Scheduled search with catch-up + PID-locked daemon."""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# F9: absolute paths (CWD-independent) — <project_root>/data/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "data" / "scheduler_state.json"
LOCK_FILE = _PROJECT_ROOT / "data" / "scheduler.lock"


def _default_state():
    return {
        "enabled": False,
        "last_run": None,
        "runs": 0,
        "directions": [],
        "last_error": None,
        "last_reminder_at": None,
    }


def _load():
    """Load scheduler state. First run returns defaults; corruption is logged loudly."""
    if not STATE_FILE.exists():
        return _default_state()  # legitimate first run
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # F5: state file corrupted — log ERROR + back up, do NOT silently disable
        logger.error(
            f"Scheduler state file corrupted ({STATE_FILE}): {e}. "
            f"Backing up and resetting to defaults."
        )
        _backup_corrupt()
        return _default_state()
    except Exception as e:
        logger.error(f"Scheduler state load failed: {e}. Resetting to defaults.")
        return _default_state()


def _backup_corrupt():
    try:
        import shutil

        corrupt = STATE_FILE.with_suffix(".json.corrupt")
        shutil.move(str(STATE_FILE), str(corrupt))
        logger.warning(f"Corrupt state moved to {corrupt}")
    except Exception as e:
        logger.warning(f"Could not back up corrupt state file: {e}")


def _save(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def _pid_alive(pid: int) -> bool:
    """Cross-platform check whether a PID is still running."""
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only API
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock() -> bool:
    """F9: prevent two daemon instances from double-running.

    Returns True if this process now holds the lock.
    Stale locks from dead processes are taken over.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            if _pid_alive(old_pid):
                logger.warning(f"Another scheduler daemon is running (pid={old_pid}); aborting.")
                return False
            logger.warning(f"Stale lock from dead pid={old_pid}; taking over.")
        except (ValueError, OSError):
            logger.warning("Corrupt scheduler lock file; overwriting.")
    try:
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except OSError as e:
        logger.error(f"Cannot write scheduler lock: {e}")
        return False


def release_lock():
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except OSError:
        pass


def schedule_on(config):
    s = _load()
    s["enabled"] = True
    s["directions"] = config.schedule.directions
    _save(s)
    logger.info("Scheduler ON")
    return s


def schedule_off():
    s = _load()
    s["enabled"] = False
    _save(s)
    logger.info("Scheduler OFF")
    return s


def schedule_status():
    s = _load()
    return {
        "enabled": s.get("enabled", False),
        "last_run": s.get("last_run"),
        "runs": s.get("runs", 0),
        "directions": s.get("directions", []),
        "last_error": s.get("last_error"),
    }


async def run_scheduled_search(config, llm_provider, db):
    s = _load()
    if not s.get("enabled"):
        return
    now = datetime.now(UTC)
    hours = config.schedule.interval_hours
    # Quiet hours are configured in LOCAL wall-clock time; resolve the local
    # hour explicitly with a timezone so the two clock bases never get mixed
    # (UTC clock above is for persistence/catch-up, this one for the user's
    # quiet-hours window).
    local_h = datetime.now().astimezone().hour
    qh = config.schedule.quiet_hours
    # Support both non-wrapping ([8,18]) and midnight-wrapping ([22,8]) ranges.
    if qh and len(qh) >= 2:
        start, end = qh[0], qh[1]
        if (start < end and start <= local_h < end) or (
            start > end and (local_h >= start or local_h < end)
        ):
            logger.debug(f"Quiet hours {qh}, skip")
            return

    is_catchup = False
    last = s.get("last_run")
    if last:
        try:
            lt = datetime.fromisoformat(last)
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=UTC)
            if now - lt > timedelta(hours=hours * 1.5):
                is_catchup = True
        except Exception as e:
            # F5: was `except: pass` — now logged
            logger.warning(f"Bad last_run timestamp '{last}': {e}; treating as catch-up")
            is_catchup = True

    logger.info(f"Scheduler: {'catch-up' if is_catchup else 'scheduled'} search")
    try:
        from agent_core.pipeline.orchestrator import run_pipeline

        data = await run_pipeline(
            config,
            llm_provider,
            stages=["search", "filter", "enrich", "match"],
            directions=s["directions"] or config.schedule.directions,
            headless=True,
            interactive=False,
        )
        matched = data.get("matched", [])
        total = len(matched)
        # NOTE: run_pipeline() already sends notify_search_complete() at the end
        # of a successful run. Sending it again here produced duplicate toasts.
        s["last_run"] = now.isoformat()
        s["runs"] = s.get("runs", 0) + 1
        s["last_error"] = None
        _save(s)
        # Per-platform search_status rows are persisted by run_pipeline()
        # (search stage) using real per-platform counts.
        db.commit()
        logger.info(f"Scheduler done: {total} jobs")
        # Application follow-up reminders (independent of search).
        try:
            check_application_reminders(config, db)
        except Exception as e:
            logger.warning(f"Application reminder check failed: {e}")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")
        s["last_run"] = now.isoformat()
        s["last_error"] = str(e)
        _save(s)


def check_application_reminders(config, db) -> int:
    """Toast-remind applications not updated in `reminder_days` (skips 已终止).

    Reads reminder_days from scheduler_state (set via dashboard UI) or
    config.schedule.reminder_days. Returns count of reminded applications.
    """
    from datetime import datetime, timedelta

    state = _load()
    now = datetime.now(UTC)
    last_reminder_at = state.get("last_reminder_at")
    if last_reminder_at:
        try:
            last_reminder = datetime.fromisoformat(last_reminder_at)
            if last_reminder.tzinfo is None:
                last_reminder = last_reminder.replace(tzinfo=UTC)
            # 最多每天提醒一次，避免后台循环/定时任务重复弹 Toast
            if now - last_reminder < timedelta(hours=24):
                return 0
        except ValueError:
            logger.warning(f"Bad last_reminder_at '{last_reminder_at}'; resetting")
    days = state.get("reminder_days") or config.schedule.reminder_days
    cutoff = now - timedelta(days=days)
    try:
        rows = db.execute(
            "SELECT COUNT(*) FROM applications WHERE status != '已终止' AND updated_at < ?",
            (cutoff.isoformat(),),
        ).fetchone()
        count = rows[0] if rows else 0
    except Exception as e:
        logger.warning(f"Application reminder query failed: {e}")
        return 0
    if count > 0:
        try:
            from agent_core.notify.windows_toast import notify_application_reminder

            notify_application_reminder(count)
            state["last_reminder_at"] = now.isoformat()
            _save(state)
        except Exception as e:
            logger.warning(f"notify_application_reminder failed: {e}")
    return count
