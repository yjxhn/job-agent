"""Tests for dashboard auth-token injection into the HTML shell."""

import io

from agent_core.server.serve import _serve_index


class _CaptureHandler:
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


def test_serve_index_injects_token_meta_when_env_set(monkeypatch):
    monkeypatch.setenv("AGENT_DASHBOARD_TOKEN", "s3cret")
    h = _CaptureHandler()
    _serve_index(h)
    body = h.wfile.getvalue().decode("utf-8")
    assert 'name="dashboard-token" content="s3cret"' in body


def test_serve_index_no_token_meta_when_dev_mode(monkeypatch):
    monkeypatch.delenv("AGENT_DASHBOARD_TOKEN", raising=False)
    h = _CaptureHandler()
    _serve_index(h)
    body = h.wfile.getvalue().decode("utf-8")
    assert '<meta name="dashboard-token"' not in body
