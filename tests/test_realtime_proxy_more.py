"""Additional coverage tests for ``agent_core.server.realtime_proxy``.

These tests deliberately avoid real WebSocket / ASR / TTS / LLM connections.
They use fake websocket objects and monkeypatched pipeline/storage entry points.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from types import SimpleNamespace

import pytest

from agent_core.server.realtime_proxy import (
    EVT_CONFIG_UPDATED,
    EVT_REPLY_CONTENT,
    EVT_REPLY_ENDED,
    EVT_REPLY_STARTED,
    EVT_TASK_REQUEST,
    EVT_TTS_ENDED,
    EVT_TTS_RESPONSE,
    EVT_TTS_SENTENCE_END,
    EVT_TTS_SENTENCE_START,
    GZIP,
    JSON,
    MSG_WITH_EVENT,
    NO_COMPRESSION,
    NO_SERIALIZATION,
    SERVER_ACK,
    SERVER_ERROR_RESPONSE,
    SERVER_FULL_RESPONSE,
    RealtimeSession,
    _parse_response,
    handle_browser_connection,
    start_proxy_in_thread,
)


def _make_session() -> RealtimeSession:
    job = SimpleNamespace(id="j1", title="设备工程师", company="测试公司")
    return RealtimeSession("rt_test", job, None, None, "manifest", None)


def _server_frame(
    payload,
    event=EVT_TASK_REQUEST,
    sid="sess-1",
    msg_type=SERVER_FULL_RESPONSE,
    flags=MSG_WITH_EVENT,
    serial=JSON,
    compression=GZIP,
    raw_payload: bytes | None = None,
):
    """Hand-build a server frame, optionally with raw bytes payload."""
    header = bytes(
        [
            0x11,
            (msg_type << 4) | flags,
            (serial << 4) | compression,
            0x00,
        ]
    )
    sid_bytes = sid.encode("utf-8")
    body = bytearray()
    if flags & MSG_WITH_EVENT:
        body.extend(event.to_bytes(4, "big"))
    body.extend(len(sid_bytes).to_bytes(4, "big"))
    body.extend(sid_bytes)
    if raw_payload is not None:
        pbytes = raw_payload
    elif serial == JSON and compression == GZIP:
        pbytes = gzip.compress(json.dumps(payload).encode("utf-8"))
    elif serial == JSON and compression == NO_COMPRESSION:
        pbytes = json.dumps(payload).encode("utf-8")
    else:
        pbytes = payload if isinstance(payload, bytes) else bytes(payload)
    body.extend(len(pbytes).to_bytes(4, "big"))
    body.extend(pbytes)
    return bytes(header) + bytes(body)


class _FakeWs:
    def __init__(self, recv_results=None, state: int = 1):
        self.state = state
        self.sent: list = []
        self.closed = 0
        self._recv_results = list(recv_results or [])

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self._recv_results:
            raise AssertionError("unexpected recv with no queued result")
        return self._recv_results.pop(0)

    async def close(self):
        self.closed += 1
        self.state = 3


class _AsyncIterWs(_FakeWs):
    def __init__(self, messages, state: int = 1):
        super().__init__(state=state)
        self.messages = list(messages)

    def __aiter__(self):
        self._iter = iter(self.messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _FakeServeCM:
    def __init__(self):
        self.handler = None
        self.host = None
        self.port = None
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return False


# ---------------------------------------------------------------------------
# Protocol parsing edge branches
# ---------------------------------------------------------------------------


def test_parse_full_response_without_event_flag():
    frame = _server_frame({"ok": 1}, event=EVT_TASK_REQUEST, flags=0, msg_type=SERVER_FULL_RESPONSE)
    parsed = _parse_response(frame)
    assert parsed["message_type"] == SERVER_FULL_RESPONSE
    assert parsed["event"] == 0
    assert parsed["session_id"] == "sess-1"
    assert parsed["payload"] == {"ok": 1}


def test_parse_full_response_uncompressed_raw_payload():
    raw = b"\x00\x01\x02"
    frame = _server_frame(
        raw,
        event=EVT_TASK_REQUEST,
        msg_type=SERVER_ACK,
        serial=NO_SERIALIZATION,
        compression=NO_COMPRESSION,
        raw_payload=raw,
    )
    parsed = _parse_response(frame)
    assert parsed["payload"] == raw
    assert parsed["payload_size"] == len(raw)


def _error_frame(
    code: int, payload_bytes: bytes, serial=NO_SERIALIZATION, compression=NO_COMPRESSION
):
    header = bytes(
        [
            0x11,
            (SERVER_ERROR_RESPONSE << 4) | 0,
            (serial << 4) | compression,
            0x00,
        ]
    )
    return header + code.to_bytes(4, "big") + len(payload_bytes).to_bytes(4, "big") + payload_bytes


def test_parse_error_response_uncompressed_string_payload():
    parsed = _parse_response(_error_frame(42, b"boom"))
    assert parsed["code"] == 42
    assert parsed["payload"] == "boom"


# ---------------------------------------------------------------------------
# connect_volc / _build_start_session
# ---------------------------------------------------------------------------


def _realtime_config():
    return SimpleNamespace(
        realtime=SimpleNamespace(
            resource_id="res-1",
            resolved_app_key="app-key",
            volc_endpoint="ws://fake.volc.invalid",
            voice="zh_female",
            model="sc2.0",
            ws_port=8765,
        ),
        volc_app_id="app-id",
        volc_access_key="access-key",
    )


async def test_connect_volc_sends_start_sequence(monkeypatch):
    session = _make_session()
    session.config = _realtime_config()
    fake_ws = _FakeWs(recv_results=[b"", b""])

    async def fake_connect(*args, **kwargs):
        fake_ws.sent.append(("connect", args, kwargs))
        return fake_ws

    monkeypatch.setattr("websockets.connect", fake_connect)
    await session.connect_volc()

    assert session.volc_ws is fake_ws
    # StartConnection, StartSession and the ChatTextQuery trigger are sent.
    assert fake_ws.sent[0][0] == "connect"
    assert len(fake_ws.sent) == 4
    first = int.from_bytes(fake_ws.sent[1][4:8], "big")
    second = int.from_bytes(fake_ws.sent[2][4:8], "big")
    third = int.from_bytes(fake_ws.sent[3][4:8], "big")
    assert first == 1
    assert second == 100
    assert third == 501


async def test_connect_volc_raises_when_start_session_errors(monkeypatch):
    session = _make_session()
    session.config = _realtime_config()
    error_frame = _error_frame(
        52000042,
        gzip.compress(json.dumps({"msg": "bad"}).encode("utf-8")),
        serial=JSON,
        compression=GZIP,
    )
    fake_ws = _FakeWs(recv_results=[b"", error_frame])

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("websockets.connect", fake_connect)
    with pytest.raises(RuntimeError, match="StartSession failed"):
        await session.connect_volc()


def test_build_start_session_contains_expected_config():
    session = _make_session()
    session.config = _realtime_config()
    start = session._build_start_session()
    assert start["asr"]["audio_info"]["sample_rate"] == 16000
    assert start["tts"]["speaker"] == "zh_female"
    assert start["dialog"]["extra"]["model"] == "sc2.0"
    assert start["dialog"]["character_manifest"] == "manifest"


# ---------------------------------------------------------------------------
# Relay loops
# ---------------------------------------------------------------------------


async def test_relay_browser_to_volc_forwards_audio_and_handles_end():
    session = _make_session()
    session.browser_ws = _AsyncIterWs([b"\x00audio", json.dumps({"type": "end"})])
    session.volc_ws = _FakeWs()

    async def fake_end_session(manual=False):
        session._end_called = manual

    session._end_session = fake_end_session  # type: ignore[method-assign]
    await session.relay_browser_to_volc()

    assert len(session.volc_ws.sent) == 1
    sent_frame = session.volc_ws.sent[0]
    assert int.from_bytes(sent_frame[4:8], "big") == EVT_TASK_REQUEST
    assert session._end_called is True


async def test_relay_browser_to_volc_handles_abandon():
    session = _make_session()
    session.browser_ws = _AsyncIterWs([json.dumps({"type": "abandon"})])
    session.volc_ws = _FakeWs()
    abandoned = []

    async def fake_abandon():
        abandoned.append(True)

    session._abandon = fake_abandon  # type: ignore[method-assign]
    await session.relay_browser_to_volc()
    assert abandoned == [True]


async def test_relay_browser_to_volc_skips_when_volc_closed():
    session = _make_session()
    session.browser_ws = _AsyncIterWs([b"\x00audio"])
    session.volc_ws = _FakeWs(state=3)
    await session.relay_browser_to_volc()
    assert session.volc_ws.sent == []


async def test_relay_volc_to_browser_dispatches_parsed_event():
    session = _make_session()
    frame = _server_frame({"content": "hi"}, event=EVT_REPLY_CONTENT)
    session.volc_ws = _AsyncIterWs([frame, "text msg"])
    seen = []

    async def fake_handle(parsed, raw):
        seen.append((parsed, raw))

    session._handle_volc_event = fake_handle  # type: ignore[method-assign]
    await session.relay_volc_to_browser()
    assert seen[0][0]["event"] == EVT_REPLY_CONTENT
    assert seen[0][1] == frame


# ---------------------------------------------------------------------------
# _handle_volc_event branches
# ---------------------------------------------------------------------------


async def test_handle_server_error_idle_timeout_ends_gracefully():
    session = _make_session()
    ended = []

    async def fake_end(manual=False):
        ended.append(manual)

    session._end_session = fake_end  # type: ignore[method-assign]
    await session._handle_volc_event(
        {
            "message_type": SERVER_ERROR_RESPONSE,
            "code": 52000042,
            "payload": {},
        },
        b"",
    )
    assert ended == [False]


async def test_handle_server_error_silence_sends_hint():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event(
        {"message_type": SERVER_ERROR_RESPONSE, "code": 45000003, "payload": {}},
        b"",
    )
    assert json.loads(session.browser_ws.sent[0])["type"] == "hint"


async def test_handle_server_error_unknown_sends_error():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event(
        {"message_type": SERVER_ERROR_RESPONSE, "code": 999, "payload": {"x": 1}},
        b"",
    )
    sent = json.loads(session.browser_ws.sent[0])
    assert sent["type"] == "error"
    assert "999" in sent["text"]


async def test_handle_tts_response_forwards_bytes_to_browser():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event({"event": EVT_TTS_RESPONSE, "payload": b"\x00\x01\x02"}, b"")
    assert session.browser_ws.sent == [b"\x00\x01\x02"]


async def test_handle_server_ack_bytearray_forwards_bytes():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event(
        {"message_type": SERVER_ACK, "event": EVT_TASK_REQUEST, "payload": bytearray(b"abc")},
        b"",
    )
    assert session.browser_ws.sent == [b"abc"]


async def test_handle_audio_event_skips_when_browser_closed():
    session = _make_session()
    session.browser_ws = _FakeWs(state=3)
    await session._handle_volc_event({"event": EVT_TTS_RESPONSE, "payload": b"abc"}, b"")
    assert session.browser_ws.sent == []


async def test_handle_non_dict_payload_returns():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event({"event": 451, "payload": "not-dict"}, b"")
    assert session.browser_ws.sent == []


async def test_handle_reply_content_new_rid():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event(
        {"event": EVT_REPLY_CONTENT, "payload": {"content": "你", "reply_id": "r1"}}, b""
    )
    await session._handle_volc_event(
        {"event": EVT_REPLY_CONTENT, "payload": {"content": "好", "reply_id": "r1"}}, b""
    )
    await session._handle_volc_event(
        {"event": EVT_REPLY_CONTENT, "payload": {"content": "next", "reply_id": "r2"}}, b""
    )
    await session._handle_volc_event(
        {"event": EVT_REPLY_CONTENT, "payload": {"content": "tail"}}, b""
    )
    await session._handle_volc_event({"event": EVT_REPLY_CONTENT, "payload": {"content": ""}}, b"")
    assert session._reply_buf == "nexttail"
    texts = [json.loads(x)["text"] for x in session.browser_ws.sent]
    assert texts == ["你", "好", "next", "tail"]


async def test_handle_reply_started_resets_and_sends_tts_new():
    session = _make_session()
    session.browser_ws = _FakeWs()
    session._reply_buf = "old"
    session._cur_reply_id = "r-old"
    session._reply_ended_exit_marker = True
    await session._handle_volc_event({"event": EVT_REPLY_STARTED, "payload": {}}, b"")
    assert session._reply_buf == ""
    assert session._cur_reply_id is None
    assert session._reply_ended_exit_marker is False
    assert json.loads(session.browser_ws.sent[0])["type"] == "tts_new"


async def test_handle_reply_ended_truncates_exit_marker():
    session = _make_session()
    session.browser_ws = _FakeWs()
    session._reply_buf = "面试结束。后续内容"
    await session._handle_volc_event({"event": EVT_REPLY_ENDED, "payload": {}}, b"")
    assert session.transcript[-1] == "面试官: 面试结束。\n"
    assert session._reply_ended_exit_marker is True
    assert session._interviewer_indices == [1]


async def test_handle_tts_sentence_start_and_end():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event({"event": EVT_TTS_SENTENCE_START, "payload": {}}, b"")
    await session._handle_volc_event({"event": EVT_TTS_SENTENCE_END, "payload": {}}, b"")
    assert [json.loads(x)["type"] for x in session.browser_ws.sent] == [
        "tts_ogg_start",
        "tts_ogg_end",
    ]


async def test_handle_tts_ended_force_continue_when_questions_remain():
    session = _make_session()
    session._reply_ended_exit_marker = True
    calls = []

    async def fake_force():
        calls.append("force")
        return True

    async def fake_assessment():
        calls.append("assessment")

    session._maybe_force_continue = fake_force  # type: ignore[method-assign]
    session._trigger_assessment = fake_assessment  # type: ignore[method-assign]
    await session._handle_volc_event(
        {"event": EVT_TTS_ENDED, "payload": {"status_code": "20000002"}}, b""
    )
    assert calls == ["force"]


async def test_handle_asr_ignores_empty_and_interim_results():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event(
        {
            "event": 451,
            "payload": {
                "results": [
                    {"text": "", "is_interim": False},
                    {"text": "半句", "is_interim": True},
                ]
            },
        },
        b"",
    )
    assert session.browser_ws.sent == []


async def test_handle_asr_info_and_config_updated_are_noops():
    session = _make_session()
    session.browser_ws = _FakeWs()
    await session._handle_volc_event({"event": 450, "payload": {}}, b"")
    await session._handle_volc_event({"event": 459, "payload": {}}, b"")
    await session._handle_volc_event({"event": EVT_CONFIG_UPDATED, "payload": {}}, b"")
    assert session.browser_ws.sent == []


# ---------------------------------------------------------------------------
# Transcript placement helpers
# ---------------------------------------------------------------------------


def test_turn_has_candidate_branches():
    session = _make_session()
    session.transcript = [
        "header\n",
        "面试官: 第一题\n",
        "你: 回答\n",
        "面试官: 第二题\n",
    ]
    assert session._turn_has_candidate(1) is True
    assert session._turn_has_candidate(3) is False


def test_record_candidate_asr_no_interviewer_appends():
    session = _make_session()
    session.transcript = ["header\n"]
    session._record_candidate_asr("你好")
    assert session.transcript[-1] == "你: 你好\n"


def test_record_candidate_asr_uses_first_unanswered_turn():
    session = _make_session()
    session.transcript = [
        "header\n",
        "面试官: 第一题\n",
        "面试官: 第二题\n",
        "你: 已有回答\n",
    ]
    session._interviewer_indices = [1, 2]
    session._record_candidate_asr("第一题回答")
    assert session.transcript[2] == "你: 第一题回答\n"
    assert session.transcript[3] == "面试官: 第二题\n"


def test_record_candidate_asr_falls_back_to_last_turn():
    session = _make_session()
    session.transcript = [
        "header\n",
        "面试官: 第一题\n",
        "你: 已有回答\n",
        "面试官: 第二题\n",
    ]
    session._interviewer_indices = [1, 3]
    session._record_candidate_asr("晚到回答")
    assert session.transcript[-1] == "你: 晚到回答\n"


def test_is_exit_intent_empty_false():
    session = _make_session()
    assert session._is_exit_intent("") is False
    assert session._is_exit_intent("   ") is False


def test_reverse_phase_pending_false_after_next_interviewer():
    session = _make_session()
    session.transcript = [
        "header\n",
        "面试官: 我的问题问完了，你有什么想问我的吗？\n",
        "面试官: 这是反问后的回复\n",
    ]
    assert session._reverse_phase_pending() is False


# ---------------------------------------------------------------------------
# _maybe_force_continue
# ---------------------------------------------------------------------------


async def test_maybe_force_continue_free_form_returns_false():
    session = _make_session()
    session.total_questions = 0
    assert await session._maybe_force_continue() is False


async def test_maybe_force_continue_all_questions_asked_returns_false():
    session = _make_session()
    session.total_questions = 1
    session.transcript = ["header\n", "面试官: 唯一问题\n"]
    assert await session._maybe_force_continue() is False


async def test_maybe_force_continue_sends_when_open(monkeypatch):
    session = _make_session()
    session.total_questions = 3
    session.transcript = [
        "header\n",
        "面试官: 开场\n",
        "面试官: 问题一\n",
    ]
    session.volc_ws = _FakeWs()
    monkeypatch.setattr(
        "agent_core.server.realtime_proxy._build_request",
        lambda *a, **k: b"req",
    )
    assert await session._maybe_force_continue() is True
    assert session.volc_ws.sent == [b"req"]


async def test_maybe_force_continue_send_failure_returns_false(monkeypatch):
    session = _make_session()
    session.total_questions = 3
    session.transcript = ["header\n", "面试官: 开场\n", "面试官: 问题一\n"]
    volc = _FakeWs()

    async def boom(_):
        raise RuntimeError("send failed")

    volc.send = boom
    session.volc_ws = volc
    monkeypatch.setattr(
        "agent_core.server.realtime_proxy._build_request",
        lambda *a, **k: b"req",
    )
    assert await session._maybe_force_continue() is False


# ---------------------------------------------------------------------------
# Assessment / session termination paths
# ---------------------------------------------------------------------------


async def test_trigger_assessment_already_ended_returns_immediately():
    session = _make_session()
    session.ended = True
    sent = []

    async def fake_send(data):
        sent.append(data)

    session._send_browser = fake_send  # type: ignore[method-assign]
    await session._trigger_assessment()
    assert sent == []


async def test_trigger_assessment_falls_back_to_inline_parse_when_empty(monkeypatch):
    session = _make_session()
    session.ended = False
    session.browser_ws = _FakeWs()
    session.transcript = ["header\n", "面试官: 面试结束\n"]
    calls = []

    async def fake_send(data):
        calls.append(data)

    session._send_browser = fake_send  # type: ignore[method-assign]
    session._save_artifacts = lambda _t, _a, interrupted=False: calls.append(("save", _a))
    session._send_finish_session = lambda: _noop()
    session._close_connections = lambda: _noop()

    async def fake_generate(*a, **k):
        return None

    def fake_parse(text):
        return {"inline": True}

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_generate,
    )
    monkeypatch.setattr("agent_core.pipeline.interview_prep._parse_assessment", fake_parse)

    await session._trigger_assessment()
    assert calls[-1]["assessment"] == {"inline": True}


async def test_trigger_assessment_exception_falls_back_to_inline(monkeypatch):
    session = _make_session()
    session.ended = False
    session.browser_ws = _FakeWs()
    session.transcript = ["header\n", "面试官: 面试结束\n"]
    calls = []

    async def fake_send(data):
        calls.append(data)

    session._send_browser = fake_send  # type: ignore[method-assign]
    session._save_artifacts = lambda _t, _a, interrupted=False: calls.append(("save", _a))
    session._send_finish_session = lambda: _noop()
    session._close_connections = lambda: _noop()

    async def fake_generate(*a, **k):
        raise RuntimeError("llm down")

    def fake_parse(text):
        return {"inline": True}

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_generate,
    )
    monkeypatch.setattr("agent_core.pipeline.interview_prep._parse_assessment", fake_parse)

    await session._trigger_assessment()
    assert calls[-1]["assessment"] == {"inline": True}


async def test_trigger_assessment_exception_and_parse_failure_yields_none(monkeypatch):
    session = _make_session()
    session.ended = False
    session.browser_ws = _FakeWs()
    session.transcript = ["header\n"]

    async def fake_send(data):
        pass

    session._send_browser = fake_send  # type: ignore[method-assign]
    session._save_artifacts = lambda _t, _a, interrupted=False: None
    session._send_finish_session = lambda: _noop()
    session._close_connections = lambda: _noop()

    async def fake_generate(*a, **k):
        raise RuntimeError("llm down")

    def fake_parse(text):
        raise ValueError("parse fail")

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_generate,
    )
    monkeypatch.setattr("agent_core.pipeline.interview_prep._parse_assessment", fake_parse)

    await session._trigger_assessment()
    assert session.ended is True


async def test_send_finish_session_sends_when_open(monkeypatch):
    session = _make_session()
    session.volc_ws = _FakeWs()
    monkeypatch.setattr(
        "agent_core.server.realtime_proxy._build_request",
        lambda *a, **k: b"finish",
    )
    await session._send_finish_session()
    assert session.volc_ws.sent == [b"finish"]


async def test_send_finish_session_swallows_send_error():
    session = _make_session()
    volc = _FakeWs()

    async def boom(_):
        raise RuntimeError("boom")

    volc.send = boom
    session.volc_ws = volc
    await session._send_finish_session()
    assert volc.sent == []


async def test_abandon_already_ended_returns_immediately():
    session = _make_session()
    session.ended = True
    session.volc_ws = _FakeWs()
    await session._abandon()
    assert session.volc_ws.closed == 0


async def test_end_session_already_ended_returns_immediately():
    session = _make_session()
    session.ended = True
    session.browser_ws = _FakeWs()
    await session._end_session(manual=True)
    assert session.browser_ws.sent == []


async def test_end_session_manual_false(monkeypatch):
    session = _make_session()
    session.ended = False
    session.browser_ws = _FakeWs()
    sent = []

    async def fake_send(data):
        sent.append(data)

    session._send_browser = fake_send  # type: ignore[method-assign]
    session._save_artifacts = lambda _t, _a, interrupted=False: sent.append(("save", interrupted))
    session._send_finish_session = lambda: _noop()
    session._close_connections = lambda: _noop()

    await session._end_session(manual=False)
    assert session.ended is True
    assert any(isinstance(d, dict) and d.get("type") == "ended" for d in sent)


async def test_end_session_manual_assessment_failure_degrades_gracefully(monkeypatch):
    session = _make_session()
    session.ended = False
    session.browser_ws = _FakeWs()
    sent = []

    async def fake_send(data):
        sent.append(data)

    session._send_browser = fake_send  # type: ignore[method-assign]
    session._save_artifacts = lambda _t, _a, interrupted=False: sent.append(("save", _a))
    session._send_finish_session = lambda: _noop()
    session._close_connections = lambda: _noop()

    async def fake_generate(*a, **k):
        raise RuntimeError("assessment boom")

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_generate,
    )
    await session._end_session(manual=True)
    assert any(isinstance(d, dict) and d.get("type") == "ended" for d in sent)
    assert any(isinstance(d, tuple) and d[0] == "save" and d[1] is None for d in sent)


async def test_close_connections_swallows_close_errors():
    session = _make_session()

    class _BoomWs(_FakeWs):
        async def close(self):
            self.closed += 1
            raise RuntimeError("close boom")

    session.volc_ws = _BoomWs()
    session.browser_ws = _BoomWs()
    await session._close_connections()
    assert session.volc_ws.closed == 1
    assert session.browser_ws.closed == 1


async def _noop():
    return None


# ---------------------------------------------------------------------------
# _save_artifacts edge branches
# ---------------------------------------------------------------------------


def test_save_artifacts_removes_zero_byte_assessment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _make_session()
    session.db_path = str(tmp_path / "a.db")

    def fake_format(*a, **k):
        return ""

    monkeypatch.setattr("agent_core.pipeline.interview_prep.format_assessment_txt", fake_format)
    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", lambda *a, **k: None)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: _FakeDb())
    session._save_artifacts("记录", {"overall": 8})
    assert not list(tmp_path.glob("*_assessment.txt"))


def test_save_artifacts_removes_stale_empty_assessment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _make_session()
    session.db_path = str(tmp_path / "b.db")
    assessment_path = tmp_path / "output" / "测试公司_设备工程师_realtime_mock_assessment.txt"
    assessment_path.parent.mkdir(parents=True, exist_ok=True)
    assessment_path.write_text("stale", encoding="utf-8")

    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", lambda *a, **k: None)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: _FakeDb())
    session._save_artifacts("记录", None)
    assert not assessment_path.exists()


def test_save_artifacts_swallows_catalog_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _make_session()
    session.db_path = str(tmp_path / "c.db")

    def fake_catalog(*a, **k):
        raise RuntimeError("catalog down")

    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", fake_catalog)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: _FakeDb())
    session._save_artifacts("记录", None)
    assert (tmp_path / "output" / "测试公司_设备工程师_realtime_mock.md").exists()


class _FakeDb:
    def close(self):
        pass


# ---------------------------------------------------------------------------
# handle_browser_connection
# ---------------------------------------------------------------------------


class _BrowserWs:
    def __init__(self, recv_results):
        self._recv_results = list(recv_results)
        self.sent = []

    async def recv(self):
        if not self._recv_results:
            await asyncio.sleep(3600)
        return self._recv_results.pop(0)

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        pass


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def _patch_success_deps(monkeypatch):
    conn = SimpleNamespace(execute=lambda *a, **k: _FakeCursor(("row",)), close=lambda: None)

    def fake_get_db(path=None):
        return conn

    monkeypatch.setattr("agent_core.storage.db.get_db", fake_get_db)
    monkeypatch.setattr(
        "agent_core.platforms.base.Job.from_storage",
        staticmethod(lambda row: SimpleNamespace(id="j1", title="设备工程师", company="测试公司")),
    )
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep._prep_bank_question_texts",
        lambda bank, focus=None: ["q1"],
    )
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.build_character_manifest",
        lambda *a, **k: "manifest",
    )
    monkeypatch.setattr(
        "agent_core.llm.providers.create_provider",
        lambda config: object(),
    )

    async def fake_connect(self):
        self.volc_ws = _FakeWs()

    async def fake_relay_browser(self):
        return None

    async def fake_relay_volc(self):
        return None

    monkeypatch.setattr(RealtimeSession, "connect_volc", fake_connect)
    monkeypatch.setattr(RealtimeSession, "relay_browser_to_volc", fake_relay_browser)
    monkeypatch.setattr(RealtimeSession, "relay_volc_to_browser", fake_relay_volc)


async def test_handle_browser_connection_start_success(monkeypatch):
    ws = _BrowserWs([json.dumps({"type": "start", "job_id": "j1"})])
    _patch_success_deps(monkeypatch)
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert any("started" in s for s in ws.sent)


async def test_handle_browser_connection_rejects_non_start():
    ws = _BrowserWs([json.dumps({"type": "hello"})])
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert json.loads(ws.sent[0]) == {"type": "error", "text": "expected start"}


async def test_handle_browser_connection_requires_job_id():
    ws = _BrowserWs([json.dumps({"type": "start"})])
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert json.loads(ws.sent[0]) == {"type": "error", "text": "missing job_id"}


async def test_handle_browser_connection_job_not_found(monkeypatch):
    ws = _BrowserWs([json.dumps({"type": "start", "job_id": "missing"})])
    conn = SimpleNamespace(execute=lambda *a, **k: _FakeCursor(None), close=lambda: None)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: conn)
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert json.loads(ws.sent[0]) == {"type": "error", "text": "job not found"}


async def test_handle_browser_connection_focus_no_match(monkeypatch):
    ws = _BrowserWs(
        [json.dumps({"type": "start", "job_id": "j1", "focus": "AI", "from_prep": True})]
    )
    conn = SimpleNamespace(execute=lambda *a, **k: _FakeCursor(("row",)), close=lambda: None)

    def fake_get_db(path=None):
        return conn

    monkeypatch.setattr("agent_core.storage.db.get_db", fake_get_db)
    monkeypatch.setattr(
        "agent_core.platforms.base.Job.from_storage",
        staticmethod(lambda row: SimpleNamespace(id="j1", title="设备工程师", company="测试公司")),
    )
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.load_interview_prep_json",
        lambda job_id, conn: {"rounds": []},
    )
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep._prep_bank_question_texts",
        lambda bank, focus=None: [],
    )
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert "未命中题库题目" in ws.sent[0]


async def test_handle_browser_connection_start_timeout():
    async def boom_recv():
        raise TimeoutError("timeout")

    ws = _BrowserWs([])
    ws.recv = boom_recv
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert json.loads(ws.sent[0]) == {"type": "error", "text": "start timeout"}


async def test_handle_browser_connection_generic_error():
    async def boom_recv():
        raise ValueError("bad payload")

    ws = _BrowserWs([])
    ws.recv = boom_recv
    await handle_browser_connection(ws, _realtime_config(), db_path=":memory:")
    assert json.loads(ws.sent[0]) == {"type": "error", "text": "bad payload"}


# ---------------------------------------------------------------------------
# Server bootstrap helpers
# ---------------------------------------------------------------------------


async def test_run_proxy_server_enters_serve(monkeypatch):
    import agent_core.server.realtime_proxy as rp

    serve_cm = _FakeServeCM()

    def fake_serve(handler, host, port):
        serve_cm.handler = handler
        serve_cm.host = host
        serve_cm.port = port
        return serve_cm

    async def fake_future():
        return None

    monkeypatch.setattr("websockets.serve", fake_serve)
    monkeypatch.setattr("asyncio.Future", fake_future)
    await rp._run_proxy_server(_realtime_config(), db_path=":memory:")
    assert serve_cm.exited is True
    assert serve_cm.host == "127.0.0.1"
    assert serve_cm.port == 8765


def test_start_proxy_in_thread_disabled_returns_none():
    config = _realtime_config()
    config.realtime.enabled = False
    assert start_proxy_in_thread(config) is None


def test_start_proxy_in_thread_missing_creds_returns_none():
    config = _realtime_config()
    config.realtime.enabled = True
    config.volc_app_id = ""
    assert start_proxy_in_thread(config) is None


def test_start_proxy_in_thread_starts_daemon(monkeypatch):
    async def fake_run(config, db_path):
        return None

    monkeypatch.setattr("agent_core.server.realtime_proxy._run_proxy_server", fake_run)
    config = _realtime_config()
    config.realtime.enabled = True
    thread = start_proxy_in_thread(config, db_path=":memory:")
    assert thread is not None
    assert thread.daemon is True
    thread.join(timeout=2)
    assert not thread.is_alive()
