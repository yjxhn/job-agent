"""Shared helpers for persistent Playwright browser profiles.

Both zhilian_browser.py and boss_browser.py use headed persistent Chromium
profiles. These helpers centralize the stale-lock cleanup and launch-failure
markers that otherwise got copy-pasted between the two modules.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Chromium lock files that prevent launch_persistent_context from reusing a
# profile after a crash or unclean shutdown.
STALE_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")

# Error substrings that indicate a persistent-context launch failed because of
# a previous browser instance/profile lock rather than a permanent code error.
LAUNCH_FAIL_MARKERS = (
    "Target page, context or browser has been closed",
    "Failed to launch",
    "Another instance",
    "SingletonLock",
)


def remove_stale_lock_files(profile_dir: str | Path) -> None:
    """Best-effort delete Chromium singleton lock files under a profile dir."""
    profile = Path(profile_dir)
    for name in STALE_LOCK_FILES:
        lock_path = profile / name
        try:
            if lock_path.exists():
                lock_path.unlink()
                logger.debug("Removed stale %s under %s", name, profile)
        except Exception:
            logger.debug("Could not remove stale %s under %s", name, profile, exc_info=True)
