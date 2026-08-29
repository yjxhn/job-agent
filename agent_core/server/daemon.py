"""Dashboard process lifecycle helpers (daemon start/stop).

Kept out of serve.py so the request-handler module focuses on HTTP routing.
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 -- fixed argv below, no shell/user input
import sys

logger = logging.getLogger(__name__)


def _ensure_dashboard(port: int = 8765, db_path: str = "data/agent.db") -> bool:
    """Ensure dashboard process is running. Returns True if already running, False if started."""
    # Check pid file
    pid_path = os.path.join(os.path.dirname(db_path), "dashboard.pid")
    if os.path.exists(pid_path):
        try:
            with open(pid_path) as f:
                old_pid = int(f.read().strip())
            # Check if process is still alive
            if sys.platform == "win32":
                import ctypes

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, old_pid)  # PROCESS_QUERY_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True  # Process still alive
                # Process is dead, fall through to start
            else:
                # Unix: send signal 0 to check
                os.kill(old_pid, 0)
                return True  # Process still alive
        except (OSError, ValueError, FileNotFoundError):
            pass  # Stale pid file, fall through

    # Need to start a new detached process
    # Use the serve module's run_dashboard entry point
    cmd = [sys.executable, "-m", "agent_core.server.serve", "--port", str(port)]
    creation_flags = 0
    if sys.platform == "win32":
        # getattr guards: these Windows-only constants do not exist on POSIX,
        # and tests that monkeypatch sys.platform="win32" run on Linux runners.
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    # 2026-08-12: daemon 日志接 data/dashboard.log（原来 DEVNULL 导致实时语音
    # 等后端错误完全不可见，排查靠猜）。句柄由子进程持有，勿 close。
    _log_fh = open(
        os.path.join(os.path.dirname(db_path), "dashboard.log"),
        "a",
        encoding="utf-8",
    )
    proc = subprocess.Popen(  # nosec B603 -- argv is sys.executable + constants
        cmd,
        creationflags=creation_flags,
        stdout=_log_fh,
        stderr=_log_fh,
        stdin=subprocess.DEVNULL,
    )
    # Write pid file
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w") as f:
        f.write(str(proc.pid))
    logger.info("Dashboard started as pid %d on http://localhost:%d", proc.pid, port)
    return False


def _stop_dashboard() -> None:
    """Stop the dashboard process by pid file."""
    pid_path = "data/dashboard.pid"
    if not os.path.exists(pid_path):
        logger.info("No dashboard pid file found (not running)")
        return
    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
                logger.info("Dashboard pid %d stopped", pid)
            else:
                logger.info("Dashboard pid %d not found (already stopped)", pid)
        else:
            try:
                os.kill(pid, 15)
                logger.info("Dashboard pid %d stopped", pid)
            except ProcessLookupError:
                logger.info("Dashboard pid %d not found (already stopped)", pid)
        os.unlink(pid_path)
    except (OSError, ValueError, FileNotFoundError):
        logger.warning("Failed to stop dashboard from pid file")
        # Stale pid file
        try:
            os.unlink(pid_path)
        except OSError:
            pass
