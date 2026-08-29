"""Unit tests for REPL helpers and turn processing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.agent.repl import _process_turn, _trim_history, _truncate
from agent_core.llm.base import ChatResponse


def test_truncate_short_text():
    assert _truncate("abc", 5) == "abc"
    assert _truncate("abcdef", 3) == "abc..."


def test_trim_history_removes_old_plain_exchanges():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(5):
        messages.append({"role": "user", "content": f"u{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    _trim_history(messages, max_msgs=3)
    assert len(messages) <= 3
    assert messages[0]["role"] == "system"


def test_trim_history_stops_at_tool_calls():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
    ]
    _trim_history(messages, max_msgs=4)
    # Tool-call round must never be split.
    assert any(m.get("tool_calls") for m in messages)
    assert any(m.get("role") == "tool" for m in messages)


@pytest.mark.asyncio
async def test_process_turn_no_tool_calls(capsys, monkeypatch):
    async def fake_call(*a, **kw):
        return ChatResponse(content="你好", tool_calls=None, reasoning_content=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(_search_rounds=0)
    await _process_turn(messages, dispatcher, None)
    assert messages[-1]["role"] == "assistant"
    assert "你好" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_process_turn_executes_tool(capsys, monkeypatch):
    class _FakeResp:
        tool_calls = [SimpleNamespace(id="1", name="search_jobs", arguments="{}")]
        content = None
        reasoning_content = None

    async def fake_call(*a, **kw):
        return _FakeResp()

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(_search_rounds=0, dispatch=AsyncMock(return_value="ok"))
    await _process_turn(messages, dispatcher, None, max_tool_rounds=1)
    assert any(m.get("role") == "tool" for m in messages)
