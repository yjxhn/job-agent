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
    return {"enabled": False, "last_run": None, "runs": 0, "directions": [], "last_error": None}


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
    local_h = datetime.now().hour
    qh = config.schedule.quiet_hours
    if qh and qh[0] <= local_h < qh[1]:
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
            stages=["search", "filter", "prescreen", "match"],
            directions=s["directions"] or config.schedule.directions,
            headless=True,
        )
        matched = data.get("matched", [])
        total = len(matched)
        try:
            from agent_core.notify.windows_toast import notify_search_complete

            notify_search_complete(total, data.get("skipped", 0))
        except Exception as e:
            # F5: was `except: pass`
            logger.warning(f"Notify failed: {e}")
        s["last_run"] = now.isoformat()
        s["runs"] = s.get("runs", 0) + 1
        s["last_error"] = None
        _save(s)
        for pn in config.platforms:
            if config.platforms[pn].enabled:
                db.execute(
                    "INSERT INTO search_status(search_id,platform,status,"
                    "result_count,created_at) VALUES(?,?,?,?,?)",
                    (
                        f"sched_{now.isoformat()}",
                        pn,
                        "success" if total > 0 else "no_results",
                        total,
                        now.isoformat(),
                    ),
                )
        db.commit()
        logger.info(f"Scheduler done: {total} jobs")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")
        s["last_run"] = now.isoformat()
        s["last_error"] = str(e)
        _save(s)
