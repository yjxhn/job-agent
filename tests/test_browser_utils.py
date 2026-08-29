"""Tests for shared persistent-browser helpers."""

from agent_core.platforms.browser_utils import (
    LAUNCH_FAIL_MARKERS,
    STALE_LOCK_FILES,
    remove_stale_lock_files,
)


def test_stale_lock_files_removed(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("x", encoding="utf-8")
    (profile / "SingletonSocket").write_text("x", encoding="utf-8")
    (profile / "SingletonCookie").write_text("x", encoding="utf-8")
    (profile / "Preferences").write_text("keep", encoding="utf-8")

    remove_stale_lock_files(profile)

    for name in STALE_LOCK_FILES:
        assert not (profile / name).exists()
    assert (profile / "Preferences").exists()


def test_remove_stale_lock_files_missing_profile_is_noop(tmp_path):
    missing = tmp_path / "does-not-exist"
    remove_stale_lock_files(missing)  # should not raise


def test_launch_fail_markers_cover_common_crash_messages():
    for marker in ("Target page, context or browser has been closed", "SingletonLock"):
        assert marker in LAUNCH_FAIL_MARKERS
