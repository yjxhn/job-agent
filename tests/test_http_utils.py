"""Tests for the shared dashboard HTTP helpers."""

import io
import json

from agent_core.server.http_utils import (
    _authenticate,
    _read_json_body,
    _send_error,
    _send_json,
)


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


def _body(handler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_send_json_writes_utf8_and_content_type():
    h = _FakeHandler()
    _send_json(h, {"msg": "中文"})
    assert h.status == 200
    assert h.headers["Content-Type"].startswith("application/json")
    assert _body(h) == {"msg": "中文"}


def test_send_error_uses_json_payload():
    h = _FakeHandler()
    _send_error(h, 404, "Not Found", "detail")
    assert h.status == 404
    assert _body(h) == {"error": "Not Found", "details": "detail"}


def test_read_json_body_empty_returns_empty_dict():
    h = _FakeHandler()
    h.headers = {"Content-Length": "0"}
    h.rfile = io.BytesIO(b"")
    assert _read_json_body(h) == {}


def test_read_json_body_utf8():
    h = _FakeHandler()
    raw = json.dumps({"a": 1}, ensure_ascii=False).encode("utf-8")
    h.headers = {"Content-Length": str(len(raw))}
    h.rfile = io.BytesIO(raw)
    assert _read_json_body(h) == {"a": 1}


def test_authenticate_dev_mode_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_DASHBOARD_TOKEN", raising=False)
    h = _FakeHandler()
    h.headers = {}
    allowed, err = _authenticate(h)
    assert allowed is True
    assert err is None


def test_authenticate_requires_bearer(monkeypatch):
    monkeypatch.setenv("AGENT_DASHBOARD_TOKEN", "secret")
    h = _FakeHandler()
    h.headers = {"Authorization": "Basic abc"}
    allowed, err = _authenticate(h)
    assert allowed is False
    assert "Authorization" in (err or "")


def test_authenticate_valid_token(monkeypatch):
    monkeypatch.setenv("AGENT_DASHBOARD_TOKEN", "secret")
    h = _FakeHandler()
    h.headers = {"Authorization": "Bearer secret"}
    allowed, err = _authenticate(h)
    assert allowed is True
    assert err is None
