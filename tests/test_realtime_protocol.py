"""Realtime proxy protocol-layer tests (T5-2).

Covers the binary frame building/parsing of the Volcengine SC2.0 protocol
(_generate_header / _build_request / _parse_response) which previously had
no coverage beyond three session helpers.
"""

import gzip
import json

from agent_core.server.realtime_proxy import (
    CLIENT_AUDIO_ONLY_REQUEST,
    CLIENT_FULL_REQUEST,
    DEFAULT_HEADER_SIZE,
    EVT_TASK_REQUEST,
    GZIP,
    JSON,
    MSG_WITH_EVENT,
    NO_SERIALIZATION,
    PROTOCOL_VERSION,
    SERVER_ACK,
    SERVER_ERROR_RESPONSE,
    SERVER_FULL_RESPONSE,
    _build_request,
    _generate_header,
    _parse_response,
)


def _server_frame(
    payload_dict,
    event=EVT_TASK_REQUEST,
    sid="sess-1",
    msg_type=SERVER_FULL_RESPONSE,
):
    """Hand-build a server response frame (gzip + JSON)."""
    header = _generate_header(
        message_type=msg_type, flags=MSG_WITH_EVENT, serial=JSON, compression=GZIP
    )
    sid_bytes = sid.encode("utf-8")
    payload = gzip.compress(json.dumps(payload_dict).encode("utf-8"))
    return (
        header
        + event.to_bytes(4, "big")
        + len(sid_bytes).to_bytes(4, "big")
        + sid_bytes
        + len(payload).to_bytes(4, "big")
        + payload
    )


def test_generate_header_layout():
    h = _generate_header()
    assert len(h) == 4
    assert h[0] == (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE
    assert h[1] == (CLIENT_FULL_REQUEST << 4) | MSG_WITH_EVENT
    assert h[2] == (JSON << 4) | GZIP
    assert h[3] == 0x00


def test_parse_full_response_frame():
    frame = _server_frame({"text": "你好"})
    parsed = _parse_response(frame)
    assert parsed["message_type"] == SERVER_FULL_RESPONSE
    assert parsed["event"] == EVT_TASK_REQUEST
    assert parsed["session_id"] == "sess-1"
    assert parsed["payload"] == {"text": "你好"}


def test_parse_server_ack():
    frame = _server_frame({"ok": 1}, event=251, msg_type=SERVER_ACK)
    parsed = _parse_response(frame)
    assert parsed["message_type"] == SERVER_ACK
    assert parsed["event"] == 251
    assert parsed["payload"] == {"ok": 1}


def test_parse_error_response():
    header = _generate_header(
        message_type=SERVER_ERROR_RESPONSE, flags=0, serial=JSON, compression=GZIP
    )
    payload = gzip.compress(json.dumps({"code": 52000042}).encode("utf-8"))
    frame = header + (52000042).to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload
    parsed = _parse_response(frame)
    assert parsed["code"] == 52000042
    assert parsed["payload"] == {"code": 52000042}


def test_parse_short_or_string_input_returns_empty():
    assert _parse_response(b"") == {}
    assert _parse_response(b"ab") == {}
    assert _parse_response("not bytes") == {}


def test_build_request_full_frame_layout():
    frame = _build_request(EVT_TASK_REQUEST, "sess-9", {"key": "v"})
    assert frame[0] == (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE
    assert frame[1] == (CLIENT_FULL_REQUEST << 4) | MSG_WITH_EVENT
    assert frame[2] == (JSON << 4) | GZIP
    event = int.from_bytes(frame[4:8], "big")
    sid_len = int.from_bytes(frame[8:12], "big")
    sid = frame[12 : 12 + sid_len].decode("utf-8")
    psize = int.from_bytes(frame[12 + sid_len : 16 + sid_len], "big")
    payload = json.loads(gzip.decompress(frame[16 + sid_len : 16 + sid_len + psize]))
    assert event == EVT_TASK_REQUEST
    assert sid == "sess-9"
    assert payload == {"key": "v"}


def test_build_request_audio_frame_uses_raw_gzip():
    audio = bytes(range(256)) * 4
    frame = _build_request(EVT_TASK_REQUEST, "sess-9", is_audio=True, audio_bytes=audio)
    assert frame[1] == (CLIENT_AUDIO_ONLY_REQUEST << 4) | MSG_WITH_EVENT
    assert frame[2] == (NO_SERIALIZATION << 4) | GZIP
    sid_len = int.from_bytes(frame[8:12], "big")
    psize = int.from_bytes(frame[12 + sid_len : 16 + sid_len], "big")
    payload = gzip.decompress(frame[16 + sid_len : 16 + sid_len + psize])
    assert payload == audio
