"""Tests for shared text-completeness helpers."""

import pytest

from agent_core.pipeline.text_utils import has_all_sections, retry_if_incomplete


def test_has_all_sections():
    text = "## 教育背景\n\n## 核心能力\n\n## 工作经历\n\n## 技能\n\n## 自我评价"
    assert has_all_sections(text, ("## 教育背景", "## 自我评价")) is True
    assert has_all_sections(text, ("## 缺失",)) is False


@pytest.mark.asyncio
async def test_retry_if_incomplete_retries_until_complete():
    calls = {"n": 0}

    async def gen():
        calls["n"] += 1
        return "ok" if calls["n"] >= 2 else "bad"

    result = await retry_if_incomplete(gen, is_complete=lambda s: s == "ok", max_attempts=3)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_retry_if_incomplete_returns_last_when_never_complete():
    calls = {"n": 0}

    async def gen():
        calls["n"] += 1
        return "bad"

    result = await retry_if_incomplete(gen, is_complete=lambda s: s == "ok", max_attempts=2)
    assert result == "bad"
    assert calls["n"] == 2
