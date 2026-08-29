"""Additional REPL coverage: loop behavior, trimming edges, and tool-turn handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent_core.agent.repl import (
    _process_turn,
    _trim_history,
    _truncate,
    _ts,
    run_chat_repl,
)
from agent_core.llm.base import ChatResponse


def test_ts_returns_project_timestamp_format():
    value = _ts()
    assert len(value) == 19
    assert value[4] == "-" and value[7] == "-" and value[10] == " "


def test_truncate_edge_cases():
    assert _truncate("", 3) == ""
    assert _truncate("abc", 3) == "abc"
    assert _truncate("abcd", 3) == "abc..."


def test_trim_history_noop_when_within_limit():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]
    _trim_history(messages, max_msgs=3)
    assert len(messages) == 3


def test_trim_history_does_not_split_tool_round_at_front():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
    ]
    _trim_history(messages, max_msgs=2)
    assert len(messages) == 4
    assert messages[1]["role"] == "user"
    assert messages[2].get("tool_calls")


async def test_run_chat_repl_quits_on_exit_keyword(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "exit")
    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    out = capsys.readouterr().out
    assert "再见" in out
    assert "fake" in out


async def test_run_chat_repl_ignores_empty_input_then_exits(capsys, monkeypatch):
    inputs = iter(["", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    out = capsys.readouterr().out
    assert "再见" in out


async def test_run_chat_repl_stops_on_eof(capsys, monkeypatch):
    def raise_eof(_prompt=None):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    assert "再见" in capsys.readouterr().out


async def test_run_chat_repl_stops_on_keyboard_interrupt(capsys, monkeypatch):
    def raise_ki(_prompt=None):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_ki)
    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    assert "再见" in capsys.readouterr().out


async def test_run_chat_repl_handles_turn_exception_and_continues(capsys, monkeypatch):
    monkeypatch.setattr(
        "agent_core.agent.repl._process_turn",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    # First input raises; the loop catches it and then reads 'quit'.
    inputs = iter(["hi", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    out = capsys.readouterr().out
    assert "出错了: boom" in out
    assert "再见" in out


async def test_run_chat_repl_calls_process_turn(capsys, monkeypatch):
    inputs = iter(["hello", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))
    process = AsyncMock()
    monkeypatch.setattr("agent_core.agent.repl._process_turn", process)
    await run_chat_repl(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(model="fake"))
    assert process.await_count == 1
    assert "hello" in str(process.await_args.args[0][-1]["content"])


async def test_process_turn_invalid_tool_json_uses_empty_args(capsys, monkeypatch):
    class _FakeResp:
        tool_calls = [SimpleNamespace(id="1", name="some_tool", arguments="{bad")]
        content = None
        reasoning_content = None

    calls = {"n": 0}

    async def fake_call(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp()
        return ChatResponse(content="done", tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(_search_rounds=0, dispatch=AsyncMock(return_value="ok"))
    await _process_turn(messages, dispatcher, None, max_tool_rounds=1)

    out = capsys.readouterr().out
    assert "调用工具: some_tool({bad)" in out
    dispatcher.dispatch.assert_awaited_once_with("some_tool", {})
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "done"


async def test_process_turn_multiple_tool_calls_and_reasoning(capsys, monkeypatch):
    class _FakeResp:
        tool_calls = [
            SimpleNamespace(id="1", name="a", arguments="{}"),
            SimpleNamespace(id="2", name="b", arguments='{"x":1}'),
        ]
        content = "thinking..."
        reasoning_content = "chain of thought"

    calls = {"n": 0}

    async def fake_call(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp()
        return ChatResponse(content="final", tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(
        _search_rounds=0,
        dispatch=AsyncMock(side_effect=["r1", "r2"]),
    )
    await _process_turn(messages, dispatcher, None, max_tool_rounds=1)

    assistant = messages[-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "final"
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert any(m.get("reasoning_content") == "chain of thought" for m in messages)
    out = capsys.readouterr().out
    assert "调用工具: a({})" in out
    assert '调用工具: b({"x":1})' in out


async def test_process_turn_max_rounds_exhausted(capsys, monkeypatch):
    class _FakeToolResp:
        tool_calls = [SimpleNamespace(id="1", name="a", arguments="{}")]
        content = None
        reasoning_content = None

    calls = {"n": 0}

    async def fake_call(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _FakeToolResp()
        return ChatResponse(content="final answer", tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(_search_rounds=0, dispatch=AsyncMock(return_value="ok"))
    await _process_turn(messages, dispatcher, None, max_tool_rounds=2)

    out = capsys.readouterr().out
    assert "达到最大工具调用轮次" in out
    assert "助手: final answer" in out
    assert messages[-1]["content"] == "final answer"


async def test_process_turn_no_tool_calls_empty_content(capsys, monkeypatch):
    async def fake_call(*a, **kw):
        return ChatResponse(content=None, tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = SimpleNamespace(_search_rounds=0)
    await _process_turn(messages, dispatcher, None)
    assert messages[-1] == {"role": "assistant", "content": ""}
    assert "助手:" not in capsys.readouterr().out


class _SearchDispatcher:
    def __init__(self):
        self._search_rounds = 0

    async def dispatch(self, name, args):
        self._search_rounds += 1
        return "ok"


async def test_process_turn_opens_dashboard_after_search(capsys, monkeypatch):
    calls = {"n": 0}

    async def fake_call(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(
                tool_calls=[SimpleNamespace(id="1", name="search_jobs", arguments="{}")],
                content=None,
                reasoning_content=None,
            )
        return ChatResponse(content="done", tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)
    opened = []

    def fake_open():
        opened.append(True)

    monkeypatch.setattr("agent_core.pipeline.orchestrator._open_dashboard", fake_open)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = _SearchDispatcher()
    await _process_turn(messages, dispatcher, None)
    assert opened == [True]


async def test_process_turn_ignores_dashboard_open_error(capsys, monkeypatch):
    calls = {"n": 0}

    async def fake_call(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(
                tool_calls=[SimpleNamespace(id="1", name="search_jobs", arguments="{}")],
                content=None,
                reasoning_content=None,
            )
        return ChatResponse(content="done", tool_calls=None)

    monkeypatch.setattr("agent_core.agent.repl.call_llm_with_tools_retry", fake_call)

    def fake_open():
        raise RuntimeError("no dashboard")

    monkeypatch.setattr("agent_core.pipeline.orchestrator._open_dashboard", fake_open)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    dispatcher = _SearchDispatcher()
    await _process_turn(messages, dispatcher, None)  # should not raise
