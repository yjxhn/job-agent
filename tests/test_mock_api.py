"""HTTP integration tests for /api/mock-interview/* handlers.

Uses direct BaseHTTPRequestHandler method invocation with faked dependencies,
so no live HTTP server or LLM is required.
"""

import io
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import agent_core.config as config_mod
import agent_core.llm.providers as providers_mod
import agent_core.pipeline.interview_prep as ip_mod
import agent_core.storage.db as db_mod
from agent_core.server import serve


@pytest.fixture(autouse=True)
def _restore_db_path():
    yield
    serve.Handler.db_path = "data/agent.db"


def _handler(body: dict) -> serve.Handler:
    h = serve.Handler.__new__(serve.Handler)
    raw = json.dumps(body).encode("utf-8")
    h.headers = {"Content-Length": str(len(raw))}
    h.rfile = io.BytesIO(raw)
    h.wfile = io.BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    return h


def _json_out(h) -> dict:
    return json.loads(h.wfile.getvalue() or b"{}")


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row is not None else []


class _FakeConn:
    def __init__(self, row=None):
        self._row = row
        self.closed = False

    def execute(self, *a, **kw):
        return _FakeCursor(self._row)

    def close(self):
        self.closed = True


def test_api_mock_interview_start_routes_pipeline_failure(monkeypatch):
    """start_mock_session 返回 ok=False 时 HTTP 层必须原样透传。"""
    monkeypatch.setattr(config_mod, "load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(providers_mod, "create_provider", lambda cfg: object())
    monkeypatch.setattr(
        db_mod,
        "get_db",
        lambda *a: _FakeConn(
            {
                "id": "j1",
                "title": "设备工程师",
                "company": "测试公司",
                "location": "",
                "description": "",
                "urls": "{}",
                "platforms": "",
                "direction": "default",
            }
        ),
    )
    monkeypatch.setattr(
        ip_mod,
        "start_mock_session",
        lambda *a, **kw: {"ok": False, "message": "focus=X 未命中题库题目，请修改或清空后重试"},
    )
    h = _handler({"job_id": "j1", "from_prep": True, "focus": "X"})
    serve.Handler._api_mock_interview_start(h)
    data = _json_out(h)
    assert data["ok"] is False
    assert "未命中" in data["message"]


def test_api_mock_interview_start_ok(monkeypatch):
    monkeypatch.setattr(config_mod, "load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(providers_mod, "create_provider", lambda cfg: object())
    monkeypatch.setattr(
        db_mod,
        "get_db",
        lambda *a: _FakeConn(
            {
                "id": "j1",
                "title": "设备工程师",
                "company": "测试公司",
                "location": "",
                "description": "",
                "urls": "{}",
                "platforms": "",
                "direction": "default",
            }
        ),
    )
    monkeypatch.setattr(
        ip_mod,
        "start_mock_session",
        lambda *a, **kw: {
            "ok": True,
            "session_id": "mock_1",
            "note": "已加载 prep 题库: 3 题",
            "job_title": "设备工程师",
            "job_company": "测试公司",
        },
    )
    h = _handler({"job_id": "j1"})
    serve.Handler._api_mock_interview_start(h)
    data = _json_out(h)
    assert data["ok"] is True
    assert data["session_id"] == "mock_1"


def test_api_mock_interview_abandon(monkeypatch):
    monkeypatch.setattr(ip_mod, "abandon_mock_session", lambda sid: sid == "s1")
    h = _handler({"session_id": "s1"})
    serve.Handler._api_mock_interview_abandon(h)
    assert _json_out(h) == {"ok": True}
    h2 = _handler({"session_id": "s2"})
    serve.Handler._api_mock_interview_abandon(h2)
    assert _json_out(h2) == {"ok": False}


def test_api_mock_interview_end_returns_assessment_optional(monkeypatch):

    async def fake_end(session_id):
        return {"ok": True, "md": "x.md", "assessment": None}

    monkeypatch.setattr(ip_mod, "end_mock_session", fake_end)
    h = _handler({"session_id": "s1"})
    serve.Handler._api_mock_interview_end(h)
    assert _json_out(h) == {"ok": True, "md": "x.md", "assessment": None}


def test_api_mock_interview_latest_transcript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep "output/" test files out of the real tree

    job_id = "mock-api-job"
    fname = "接口测试公司_测试工程师_mock_interview.md"
    fpath = os.path.join("output", fname)
    os.makedirs("output", exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as fh:
        fh.write("文字面试记录\n面试官: 你好")
    try:
        monkeypatch.setattr(
            db_mod,
            "get_db",
            lambda *a: _FakeConn({"title": "测试工程师", "company": "接口测试公司"}),
        )
        h = serve.Handler.__new__(serve.Handler)
        h.wfile = io.BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        serve.Handler._api_mock_latest_transcript(h, {"job_id": [job_id], "mode": ["text"]})
        h.end_headers.assert_called_once()
        body = h.wfile.getvalue()
        assert "文字面试记录" in body.decode("utf-8")
    finally:
        if os.path.exists(fpath):
            os.remove(fpath)


def test_api_mock_assessment_preview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep "output/" test files out of the real tree

    name = "接口测试公司_测试工程师_mock_interview_assessment.txt"
    fpath = os.path.join("output", name)
    os.makedirs("output", exist_ok=True)
    nl = chr(10)
    content = (
        "文字面试评估"
        + nl
        + "🎯 总分: 8.5/10"
        + nl
        + nl
        + "【维度评分】"
        + nl
        + "技术能力(technical): 8/10"
        + nl
        + nl
        + "【优势】"
        + nl
        + "- 表达清晰"
        + nl
        + "【改进点】"
        + nl
        + "- 多展开"
        + nl
    )
    with open(fpath, "w", encoding="utf-8") as fh:
        fh.write(content)
    try:
        h = serve.Handler.__new__(serve.Handler)
        h.wfile = io.BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        serve.Handler._api_mock_assessment_preview(h, {"name": [name]})
        data = json.loads(h.wfile.getvalue())
        assert data["ok"] is True
        assert data["assessment"]["overall"] == 8.5
        assert data["assessment"]["dimensions"]["technical"] == 8.0
        assert data["assessment"]["strengths"] == ["表达清晰"]
    finally:
        if os.path.exists(fpath):
            os.remove(fpath)


def test_openapi_has_mock_lifecycle_paths():
    paths = serve.OPENAPI_SPEC["paths"]
    for path in (
        "/api/mock-interview/start",
        "/api/mock-interview/reply",
        "/api/mock-interview/end",
        "/api/mock-interview/abandon",
    ):
        assert path in paths
