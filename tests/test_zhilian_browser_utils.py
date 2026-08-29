"""Unit tests for zhilian_browser cookie backup/restore helpers."""

import json
from pathlib import Path

import pytest

from agent_core.platforms.zhilian_browser import _backup_cookies, _restore_cookies


@pytest.mark.asyncio
async def test_backup_cookies_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    await _backup_cookies([{"name": "at", "value": "x"}], Path("profile"))
    p = tmp_path / "data" / "zhilian_cookies_backup" / "zhilian_cookies.json"
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8"))[0]["name"] == "at"


class _FakePage:
    async def goto(self, *a, **k):
        return None

    async def close(self):
        return None


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies
        self.added = []

    async def new_page(self):
        return _FakePage()

    async def add_cookies(self, cookies):
        self.added.extend(cookies)

    async def cookies(self):
        return self._cookies


@pytest.mark.asyncio
async def test_restore_cookies_success(tmp_path):
    backup_dir = tmp_path / "zhilian_cookies_backup"
    backup_dir.mkdir()
    (backup_dir / "zhilian_cookies.json").write_text(
        json.dumps([{"name": "at", "value": "1"}, {"name": "rt", "value": "2"}]),
        encoding="utf-8",
    )
    ctx = _FakeContext([{"name": "at"}, {"name": "rt"}])
    assert await _restore_cookies(ctx, Path(tmp_path / "profile")) is True
    assert len(ctx.added) == 2


@pytest.mark.asyncio
async def test_restore_cookies_missing_backup(tmp_path):
    ctx = _FakeContext([])
    assert await _restore_cookies(ctx, Path(tmp_path / "profile")) is False
