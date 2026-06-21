"""Integration tests for Windows Toast notifications.

These tests require a real Windows desktop environment (winotify or PowerShell).
On Linux/macOS/CI they are skipped automatically via platform check.
Use --run-integration to enable.
"""

import sys
import platform

import pytest

_IS_WINDOWS = sys.platform == "win32"


def _platform_reason() -> str:
    if _IS_WINDOWS:
        return ""
    return f"requires Windows desktop, current platform is {platform.system()}"


# Class-level skip applies only when platform is non-Windows OR --run-integration
# is not passed.  The conftest skips based on the "integration" marker, so if
# the flag is not passed these tests are skipped even before the platform check.
# The platform check is an additional guard for non-Windows environments even when
# --run-integration is given (e.g. local Linux dev machine).
@pytest.mark.integration
class TestWindowsToastIntegration:
    """Integration tests that exercise the real toast notification path."""

    def test_notify_smoke_real(self):
        """Trigger a real toast notification (winotify or PowerShell fallback).

        On Windows this emits a visible toast.  On non-Windows this is skipped.
        """
        if not _IS_WINDOWS:
            pytest.skip(_platform_reason())
        from agent_core.notify.windows_toast import notify

        # This will show a real toast on Windows — expected to succeed silently
        notify("Integration Test", "This is a test toast from pytest --run-integration")

    def test_notify_search_complete_real(self):
        """Trigger notify_search_complete with a realistic count."""
        if not _IS_WINDOWS:
            pytest.skip(_platform_reason())
        from agent_core.notify.windows_toast import notify_search_complete

        notify_search_complete(3, skipped=1)

    def test_notify_captcha_real(self):
        """Trigger notify_captcha (real toast)."""
        if not _IS_WINDOWS:
            pytest.skip(_platform_reason())
        from agent_core.notify.windows_toast import notify_captcha

        notify_captcha("Boss直聘")

    def test_notify_cookie_expired_real(self):
        """Trigger notify_cookie_expired (real toast)."""
        if not _IS_WINDOWS:
            pytest.skip(_platform_reason())
        from agent_core.notify.windows_toast import notify_cookie_expired

        notify_cookie_expired("猎聘")

    def test_notify_anti_bot_real(self):
        """Trigger notify_anti_bot (real toast)."""
        if not _IS_WINDOWS:
            pytest.skip(_platform_reason())
        from agent_core.notify.windows_toast import notify_anti_bot

        notify_anti_bot("猎聘")
