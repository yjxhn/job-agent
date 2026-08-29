"""Unified browser lifecycle manager.

2026-08-18: introduces a single place for the "one browser instance + idle
timeout" pattern used by boss_browser / zhilian_browser / playwright_jd.
Existing modules still have their own singletons; they can be migrated to this
class incrementally without changing their public functions.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class BrowserManager:
    """Holds one optional browser object and manages an idle-close deadline.

    The manager itself is backend-agnostic: it stores the active browser
    instance (Playwright browser/context or custom wrapper) and provides the
    idle bookkeeping shared by the platform browser singletons.
    """

    def __init__(self, idle_close_seconds: float = 60.0):
        self._browser: Any = None
        self._idle_deadline: float | None = None
        self._idle_close_seconds = idle_close_seconds

    @property
    def browser(self) -> Any:
        return self._browser

    def set_browser(self, browser: Any) -> None:
        self._browser = browser
        self.touch()

    def clear_browser(self) -> None:
        self._browser = None
        self._idle_deadline = None

    def touch(self) -> None:
        """Record that the browser was just used, pushing out the idle deadline."""
        self._idle_deadline = time.monotonic() + self._idle_close_seconds

    def idle_expired(self) -> bool:
        """True when the browser has been idle beyond the configured window."""
        return self._idle_deadline is not None and time.monotonic() > self._idle_deadline

    async def close_browser(self) -> None:
        """Best-effort close of the managed browser instance."""
        browser = self._browser
        self.clear_browser()
        if browser is None:
            return
        close = getattr(browser, "close", None)
        if close is None:
            return
        try:
            result = close()
            if hasattr(result, "__await__"):
                await result
        except Exception as e:  # noqa: BLE001 -- close is best-effort
            logger.warning("BrowserManager close failed: %s", e)
