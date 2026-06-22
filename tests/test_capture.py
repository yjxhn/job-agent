"""Tests for Zhilian browser-capture server (capture.py)."""

import json
import threading
import time
from http.client import HTTPConnection

from agent_core.server.capture import (
    CaptureHandler,
    _ingest_jobs,
    _stats,
    _stats_lock,
    start_capture_server,
)
from agent_core.storage.db import get_db, migrate
from tests.test_zhilian import make_zhilian_item

# ── Unit: _ingest_jobs ──


def test_ingest_jobs_inserts_new(tmp_path):
    """A single new job item is inserted into the jobs table."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    item = make_zhilian_item(name="Python后端", company_name="字节跳动")
    ingested, deduped = _ingest_jobs([item], db_path)

    assert ingested == 1
    assert deduped == 0

    conn = get_db(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE company='字节跳动'").fetchone()
    assert row is not None
    assert row["title"] == "Python后端"
    assert "zhilian" in row["platforms"]
    conn.close()


def test_ingest_jobs_dedup_by_id(tmp_path):
    """Re-inserting the same item (same id) is deduped, not duplicated."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    item = make_zhilian_item(name="Go开发", company_name="腾讯")
    ingested1, deduped1 = _ingest_jobs([item], db_path)
    assert ingested1 == 1
    assert deduped1 == 0

    ingested2, deduped2 = _ingest_jobs([item], db_path)
    assert ingested2 == 0
    assert deduped2 == 1

    conn = get_db(db_path)
    count = conn.execute("SELECT COUNT(*) FROM jobs WHERE company='腾讯'").fetchone()[0]
    assert count == 1
    conn.close()


def test_ingest_jobs_mixed_new_and_dup(tmp_path):
    """Batch of 3 items all new on first ingest, all dups on second."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    items = [
        make_zhilian_item(
            name="A",
            company_name="CA",
            position_url="https://j/1.htm",
            number="001",
        ),
        make_zhilian_item(
            name="B",
            company_name="CB",
            position_url="https://j/2.htm",
            number="002",
        ),
        make_zhilian_item(
            name="C",
            company_name="CC",
            position_url="https://j/3.htm",
            number="003",
        ),
    ]
    ingested, deduped = _ingest_jobs(items, db_path)
    assert ingested == 3
    assert deduped == 0

    ingested2, deduped2 = _ingest_jobs(items, db_path)
    assert ingested2 == 0
    assert deduped2 == 3


def test_ingest_jobs_empty_list(tmp_path):
    """Empty list returns (0, 0)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    ingested, deduped = _ingest_jobs([], db_path)
    assert ingested == 0
    assert deduped == 0


def test_ingest_jobs_minimal_item(tmp_path):
    """A minimal API item (no name) still maps and ingests via hash-based id."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    ingested, deduped = _ingest_jobs([{"not_a_real_field": 1}], db_path)
    # ZhilianAdapter._api_item_to_job always produces a hash-based id
    # from empty companyName+name, so the item is ingested
    assert ingested == 1
    assert deduped == 0


def test_ingest_jobs_updates_last_seen_on_dup(tmp_path):
    """When a duplicate arrives, last_seen is updated."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    item = make_zhilian_item(name="更新测试", company_name="更新公司")
    _ingest_jobs([item], db_path)

    conn = get_db(db_path)
    row1 = conn.execute("SELECT last_seen FROM jobs WHERE company='更新公司'").fetchone()
    original_last_seen = row1["last_seen"]
    conn.close()

    time.sleep(0.1)

    _ingest_jobs([item], db_path)

    conn = get_db(db_path)
    row2 = conn.execute("SELECT last_seen FROM jobs WHERE company='更新公司'").fetchone()
    updated_last_seen = row2["last_seen"]
    conn.close()

    assert updated_last_seen != original_last_seen


# ── Unit: CaptureHandler routing ──


def test_handler_health(tmp_path):
    """GET /health returns ok."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    handler = _make_handler(CaptureHandler, "GET", "/health")
    handler.do_GET()
    assert handler._response_status == 200
    body = json.loads(handler._response_body)
    assert body["status"] == "ok"


def test_handler_capture_status(tmp_path):
    """GET /zhilian/capture/status returns stats."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    with _stats_lock:
        _stats["total_captured"] = 10
        _stats["total_ingested"] = 8
        _stats["total_deduped"] = 2
        _stats["last_captured_at"] = "2026-06-22T00:00:00Z"

    handler = _make_handler(CaptureHandler, "GET", "/zhilian/capture/status")
    handler.do_GET()
    assert handler._response_status == 200
    body = json.loads(handler._response_body)
    assert body["total_captured"] == 10
    assert body["total_ingested"] == 8


def test_handler_capture_post_rejects_non_list(tmp_path):
    """POST with jobs=string is rejected."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    body = json.dumps({"jobs": "not a list"}).encode()
    handler = _make_handler(CaptureHandler, "POST", "/zhilian/capture", body)
    handler.do_POST()
    assert handler._response_status == 400
    resp = json.loads(handler._response_body)
    assert "must be a list" in resp["error"]


def test_handler_capture_post_rejects_bad_item(tmp_path):
    """POST with a list item missing required fields is rejected."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    body = json.dumps({"jobs": [{"bad": "item"}]}).encode()
    handler = _make_handler(CaptureHandler, "POST", "/zhilian/capture", body)
    handler.do_POST()
    assert handler._response_status == 400
    resp = json.loads(handler._response_body)
    assert "name" in resp["error"]


def test_handler_capture_post_success(tmp_path):
    """Full POST /zhilian/capture with real data.list items."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    CaptureHandler.db_path = db_path
    item = make_zhilian_item(name="测试职位", company_name="测试公司", salary60="20K-30K")
    payload = {
        "jobs": [item],
        "kw": "Python",
        "page": 1,
        "captured_at": "2026-06-22T12:00:00Z",
    }
    body = json.dumps(payload).encode()

    handler = _make_handler(CaptureHandler, "POST", "/zhilian/capture", body)
    handler.do_POST()

    assert handler._response_status == 200
    resp = json.loads(handler._response_body)
    assert resp["ok"] is True
    assert resp["ingested"] == 1
    assert resp["deduped"] == 0


def test_handler_not_found(tmp_path):
    """Unknown paths return 404."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    handler = _make_handler(CaptureHandler, "GET", "/unknown")
    handler.do_GET()
    assert handler._response_status == 404

    body = json.dumps({"jobs": []}).encode()
    handler2 = _make_handler(CaptureHandler, "POST", "/bad-path", body)
    handler2.do_POST()
    assert handler2._response_status == 404


def test_handler_invalid_json_body(tmp_path):
    """Non-JSON body returns 400."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    handler = _make_handler(CaptureHandler, "POST", "/zhilian/capture", b"not json")
    handler.do_POST()
    assert handler._response_status == 400
    resp = json.loads(handler._response_body)
    assert "invalid JSON" in resp["error"]


def test_handler_capture_empty_jobs(tmp_path):
    """POST with empty jobs array returns ok with 0 counts."""
    CaptureHandler.db_path = str(tmp_path / "agent.db")
    body = json.dumps({"jobs": []}).encode()
    handler = _make_handler(CaptureHandler, "POST", "/zhilian/capture", body)
    handler.do_POST()
    assert handler._response_status == 200
    resp = json.loads(handler._response_body)
    assert resp["ingested"] == 0


# ── Integration: start_capture_server ──


def test_server_starts_and_stops(tmp_path):
    """Server starts, responds to /health, and stops cleanly."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    port = _find_free_port()
    t = threading.Thread(
        target=start_capture_server,
        args=(port, db_path, ""),
        daemon=True,
    )
    t.start()
    time.sleep(0.5)

    c = HTTPConnection("127.0.0.1", port, timeout=3)
    c.request("GET", "/health")
    resp = c.getresponse()
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["status"] == "ok"
    c.close()


def test_server_capture_endpoint(tmp_path):
    """Full roundtrip: start server, POST capture, verify DB and status."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    port = _find_free_port()
    t = threading.Thread(
        target=start_capture_server,
        args=(port, db_path, ""),
        daemon=True,
    )
    t.start()
    time.sleep(0.5)

    item = {
        "name": "全栈工程师",
        "companyName": "阿里巴巴",
        "salary60": "25K-40K",
        "workCity": "杭州",
        "education": "本科",
        "workingExp": "3-5年",
        "positionURL": "https://jobs.zhaopin.com/999.htm",
        "number": "ZL999",
        "workType": "全职",
    }
    payload = json.dumps({"jobs": [item], "kw": "全栈", "page": 1}).encode()

    c = HTTPConnection("127.0.0.1", port, timeout=3)
    c.request(
        "POST",
        "/zhilian/capture",
        body=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = c.getresponse()
    assert resp.status == 200
    result = json.loads(resp.read())
    assert result["ok"] is True
    assert result["ingested"] == 1
    c.close()

    # Status endpoint
    c2 = HTTPConnection("127.0.0.1", port, timeout=3)
    c2.request("GET", "/zhilian/capture/status")
    resp2 = c2.getresponse()
    assert resp2.status == 200
    status = json.loads(resp2.read())
    assert status["total_ingested"] >= 1
    c2.close()

    # Verify DB
    conn3 = get_db(db_path)
    row = conn3.execute("SELECT * FROM jobs WHERE company='阿里巴巴'").fetchone()
    assert row is not None
    assert row["title"] == "全栈工程师"
    conn3.close()


# ── Helpers ──


class _MockHandler(CaptureHandler):  # type: ignore[misc]
    """Substitute wfile/socket so we can test handler logic offline."""

    def __init__(self, method, path, body_bytes=None):
        self._body_bytes = body_bytes or b""
        self._response_status = 0
        self._response_body = b""
        self._response_headers: dict = {}
        self.rfile = _MockRFile(self._body_bytes)  # type: ignore[assignment]
        self.wfile = _MockWFile(self)  # type: ignore[assignment]
        self.command = method
        self.path = path
        self.headers = {  # type: ignore[assignment]
            "Content-Length": str(len(self._body_bytes)),
        }
        self.requestline = f"{method} {path} HTTP/1.1"
        self.request_version = "HTTP/1.1"
        self.server_version = "TestServer/1.0"
        # Override BaseHTTPRequestHandler methods at instance level
        self.send_response = self._send_response  # type: ignore[assignment]
        self.send_header = self._send_header  # type: ignore[assignment]
        self.end_headers = self._end_headers  # type: ignore[assignment]
        self.log_request = self._log_request  # type: ignore[assignment]

    def _send_response(self, code):
        self._response_status = code

    def _send_header(self, key, value):
        self._response_headers[key] = value

    def _end_headers(self):
        pass

    def _log_request(self, _code="-", _size="-"):
        pass

    def log_message(self, *args):  # noqa: ARG002
        pass


class _MockRFile:
    def __init__(self, data):
        self._data = data
        self._pos = 0

    def read(self, length):
        chunk = self._data[self._pos : self._pos + length]
        self._pos += length
        return chunk


class _MockWFile:
    def __init__(self, handler):
        self._handler = handler

    def write(self, data):
        self._handler._response_body += data if isinstance(data, bytes) else data.encode("utf-8")

    def flush(self):
        pass


def _make_handler(cls, method, path, body_bytes=None):
    """Instantiate a mock handler for testing."""
    h = _MockHandler.__new__(_MockHandler)
    _MockHandler.__init__(h, method, path, body_bytes)
    return h


def _find_free_port():
    """Find an available port for testing."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
