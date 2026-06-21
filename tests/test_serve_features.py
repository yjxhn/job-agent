"""Tests for new serve.py features: auth, pagination, openapi, error handling."""

import io
import json
import os
from unittest.mock import MagicMock, patch

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate

# ==================================================================== helpers ---


def _make_handler(db_path=None):
    """Construct a minimal handler for testing helper methods."""
    if db_path:
        serve.Handler.db_path = db_path
    h = type(
        "TestHandler",
        (serve.Handler,),
        {"do_GET": serve.Handler.do_GET},
    )
    return h


def _mock_request(path="/api/results", headers=None):
    """Build a bare handler for calling helper methods directly."""
    h = serve.Handler.__new__(serve.Handler)
    h.path = path
    h.headers = headers or {}
    h.wfile = io.BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    return h


# ============================================================== P2-3 logging ---


def test_logger_exists():
    """Test that logger is set up (print→logging)."""
    assert hasattr(serve, "logger")
    assert serve.logger.name == "agent_core.server.serve"


def test_start_server_logging():
    """Test start_server configures logging."""
    with patch.object(serve, "HTTPServer") as mock_server:
        mock_server.return_value.serve_forever = MagicMock()
        serve.start_server(port=1, db_path=":memory:")
    assert serve.logger.name == "agent_core.server.serve"


# ===================================================== _get_int_param ---


def test_get_int_param_valid():
    params = {"page": ["3"], "page_size": ["50"]}
    assert serve._get_int_param(params, "page", 1) == 3
    assert serve._get_int_param(params, "page_size", 30) == 50


def test_get_int_param_missing():
    params: dict[str, list[str]] = {}
    assert serve._get_int_param(params, "page", 0) == 0
    assert serve._get_int_param(params, "limit", 100) == 100


def test_get_int_param_invalid():
    params = {"page": ["abc"], "nope": ["x"]}
    assert serve._get_int_param(params, "page", 1) == 1  # falls back


# ========================================================== _authenticate ---


def test_authenticate_dev_mode():
    """No token env = dev mode, always allowed."""
    with patch.dict(os.environ, {}, clear=True):
        h = _mock_request()
        allowed, err = serve._authenticate(h)
        assert allowed is True
        assert err is None


def test_authenticate_no_header():
    with patch.dict(os.environ, {"AGENT_DASHBOARD_TOKEN": "secret-token"}):
        h = _mock_request(headers={})
        allowed, err = serve._authenticate(h)
        assert allowed is False
        assert "Missing" in (err or "")


def test_authenticate_wrong_token():
    with patch.dict(os.environ, {"AGENT_DASHBOARD_TOKEN": "secret-token"}):
        h = _mock_request(headers={"Authorization": "Bearer wrong"})
        allowed, err = serve._authenticate(h)
        assert allowed is False
        assert "Invalid" in (err or "")


def test_authenticate_correct_token():
    with patch.dict(os.environ, {"AGENT_DASHBOARD_TOKEN": "secret-token"}):
        h = _mock_request(headers={"Authorization": "Bearer secret-token"})
        allowed, err = serve._authenticate(h)
        assert allowed is True


def test_authenticate_non_bearer():
    with patch.dict(os.environ, {"AGENT_DASHBOARD_TOKEN": "secret-token"}):
        h = _mock_request(headers={"Authorization": "Basic secret-token"})
        allowed, err = serve._authenticate(h)
        assert allowed is False


# =========================================================== _send_error ---


def test_send_error():
    h = _mock_request()
    serve._send_error(h, 404, "Not Found", "No route for /x")
    h.send_response.assert_called_once_with(404)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["error"] == "Not Found"
    assert data["details"] == "No route for /x"


def test_send_error_no_details():
    h = _mock_request()
    serve._send_error(h, 500, "Internal Server Error")
    h.send_response.assert_called_once_with(500)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert "details" not in data


# ============================================================== _send_json ---


def test_send_json():
    h = _mock_request()
    serve._send_json(h, {"items": [], "total": 0}, status=200)
    h.send_response.assert_called_once_with(200)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data == {"items": [], "total": 0}


# ============================================================= _send_html ---


def test_send_html():
    h = _mock_request()
    serve._send_html(h, "<html></html>")
    h.send_response.assert_called_once_with(200)


# ============================================================= OpenAPI ---


def test_openapi_spec_loaded():
    """Test that OPENAPI_SPEC is a valid OpenAPI 3.0 object."""
    spec = serve.OPENAPI_SPEC
    assert spec["openapi"] == "3.0.3"
    assert "info" in spec
    assert "paths" in spec
    assert "/api/results" in spec["paths"]
    assert "/api/timeline" in spec["paths"]
    assert "/api/openapi.json" in spec["paths"]


def test_serve_openapi():
    h = _mock_request()
    serve.Handler._serve_openapi(h)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["openapi"] == "3.0.3"


# ============================================================== /docs ---


def test_docs_html():
    """Test /docs HTML page content."""
    assert "<!DOCTYPE html>" in serve.DOCS_HTML
    assert "swagger-ui" in serve.DOCS_HTML
    assert "/api/openapi.json" in serve.DOCS_HTML


# ============================================================ dashboard ---


def test_html_has_docs_link():
    """Test dashboard HTML has link to /docs."""
    assert "/docs" in serve.HTML


def test_html_has_pagination_elements():
    """Test dashboard HTML has pagination JS elements."""
    assert "jobsPgn" in serve.HTML
    assert "tlPgn" in serve.HTML
    assert "loadJobs" in serve.HTML
    assert "loadTimeline" in serve.HTML


# ===================================================== paginated results ---


def test_api_results_paginated(tmp_path):
    """Test /api/results with page param returns paginated envelope."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    for i in range(25):
        conn.execute(
            "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (f"job_{i:03d}", f"Job {i}", f"Co {i}", f"City {i}", "industrial_ai_agent"),
        )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["1"], "page_size": ["10"]}
    h = _mock_request()
    serve.Handler._api_results(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total"] == 25
    assert data["pages"] == 3
    assert len(data["items"]) == 10
    assert "title" in data["items"][0]


def test_api_results_paginated_page2(tmp_path):
    """Test /api/results page 2 of paginated results."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    for i in range(15):
        conn.execute(
            "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (f"pg2_{i:03d}", f"P2 Job {i}", f"Co {i}", f"City {i}", "equipment_amr"),
        )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["2"], "page_size": ["10"]}
    h = _mock_request()
    serve.Handler._api_results(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["page"] == 2
    assert data["total"] == 15
    assert data["pages"] == 2
    assert len(data["items"]) == 5  # page 2 of 15 with size 10 = 5 remaining


def test_api_results_paginated_empty(tmp_path):
    """Test pagination on empty table."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["1"], "page_size": ["10"]}
    h = _mock_request()
    serve.Handler._api_results(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["total"] == 0
    assert data["pages"] == 1
    assert data["items"] == []


def test_api_results_legacy_no_page(tmp_path):
    """Test /api/results without page param returns flat list (backward compat)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("legacy_job", "Legacy", "Co", "City", "industrial_ai_agent"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params: dict[str, list[str]] = {}
    h = _mock_request()
    serve.Handler._api_results(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert isinstance(data, list)  # flat list, not envelope
    assert len(data) == 1


def test_api_timeline_paginated(tmp_path):
    """Test /api/timeline with page param returns paginated envelope."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("tp_job", "Tl Paginated", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("tp_job", "Offer", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in range(12):
        conn.execute(
            "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
            "VALUES (?, ?, ?, datetime('now', ? || ' hours'))",
            (app_id, f"from_{i}", f"to_{i}", str(-i)),
        )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["1"], "page_size": ["5"]}
    h = _mock_request()
    serve.Handler._api_timeline(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["page"] == 1
    assert data["page_size"] == 5
    assert data["total"] == 12
    assert data["pages"] == 3
    assert len(data["items"]) == 5


def test_api_timeline_paginated_page3(tmp_path):
    """Test /api/timeline last page."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("tp3_job", "Tl P3", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("tp3_job", "已投递", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in range(7):
        conn.execute(
            "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
            "VALUES (?, ?, ?, datetime('now', ? || ' hours'))",
            (app_id, f"f_{i}", f"t_{i}", str(-i)),
        )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["2"], "page_size": ["5"]}
    h = _mock_request()
    serve.Handler._api_timeline(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["page"] == 2
    assert data["total"] == 7
    assert data["pages"] == 2
    assert len(data["items"]) == 2


def test_api_timeline_legacy_no_page(tmp_path):
    """Test /api/timeline without page returns flat list (backward compat)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("tl_legacy", "Legacy TL", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("tl_legacy", "已投递", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (app_id, "", "已投递"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params: dict[str, list[str]] = {}
    h = _mock_request()
    serve.Handler._api_timeline(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert isinstance(data, list)  # flat list
    assert len(data) == 1


# =========================================== paginated with combined filters ---


def test_api_timeline_paginated_with_event_filter(tmp_path):
    """Test /api/timeline page + event_type filter."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("tf_job", "Tl F", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("tf_job", "Offer", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-2 hours'))",
        (app_id, "", "已投递"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'))",
        (app_id, "已投递", "约面"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now') )",
        (app_id, "约面", "Offer"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["1"], "page_size": ["5"], "event_type": ["Offer"]}
    h = _mock_request()
    serve.Handler._api_timeline(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["total"] == 1
    assert data["items"][0]["to_status"] == "Offer"


# ==================================================== 404 / error handling ---


def test_handler_unknown_route():
    """Test that unknown path returns 404 JSON."""
    h = _mock_request(path="/api/nonexistent")
    serve.Handler.do_GET(h)
    h.send_response.assert_called_once_with(404)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert "Not Found" in data["error"]


# ============================================================ module attrs ---


def test_module_exports():
    """Verify what the module exposes."""
    assert hasattr(serve, "Handler")
    assert hasattr(serve, "start_server")
    assert hasattr(serve, "HTML")
    assert hasattr(serve, "DOCS_HTML")
    assert hasattr(serve, "OPENAPI_SPEC")
    assert hasattr(serve, "logger")
    assert hasattr(serve, "_get_int_param")
    assert hasattr(serve, "_authenticate")
    assert hasattr(serve, "_send_json")
    assert hasattr(serve, "_send_html")
    assert hasattr(serve, "_send_error")


# ============================================================ misc coverage ---


def test_handler_class_attributes():
    """Test handler has all expected methods."""
    assert hasattr(serve.Handler, "db_path")
    assert hasattr(serve.Handler, "do_GET")
    assert hasattr(serve.Handler, "_api_results")
    assert hasattr(serve.Handler, "_api_timeline")
    assert hasattr(serve.Handler, "_serve_openapi")
    assert hasattr(serve.Handler, "_require_auth")
    assert hasattr(serve.Handler, "log_message")


# ============================== do_GET dispatch coverage ---


def test_do_get_root_path(tmp_path):
    """Test do_GET for / returns HTML."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()
    serve.Handler.db_path = db_path

    h = _mock_request(path="/")
    serve.Handler.do_GET(h)
    h.send_response.assert_called_once_with(200)
    wfile_val = h.wfile.getvalue().decode("utf-8")
    assert "<!DOCTYPE html>" in wfile_val
    assert "求职Agent Dashboard" in wfile_val


def test_do_get_docs_path():
    """Test do_GET for /docs returns Swagger UI."""
    h = _mock_request(path="/docs")
    serve.Handler.do_GET(h)
    h.send_response.assert_called_once_with(200)
    wfile_val = h.wfile.getvalue().decode("utf-8")
    assert "swagger-ui" in wfile_val


def test_do_get_openapi_json_path():
    """Test do_GET for /api/openapi.json."""
    h = _mock_request(path="/api/openapi.json")
    serve.Handler.do_GET(h)
    h.send_response.assert_called_once_with(200)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["openapi"] == "3.0.3"


def test_do_get_results_with_auth_dev(tmp_path):
    """Test do_GET for /api/results (dev mode, no token needed)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()
    serve.Handler.db_path = db_path

    with patch.dict(os.environ, {}, clear=True):
        h = _mock_request(path="/api/results")
        serve.Handler.do_GET(h)
        h.send_response.assert_called_once_with(200)


def test_do_get_timeline_with_auth_dev(tmp_path):
    """Test do_GET for /api/timeline (dev mode)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()
    serve.Handler.db_path = db_path

    with patch.dict(os.environ, {}, clear=True):
        h = _mock_request(path="/api/timeline")
        serve.Handler.do_GET(h)
        h.send_response.assert_called_once_with(200)


def test_do_get_results_auth_blocked():
    """Test do_GET /api/results blocked when token is wrong."""
    with patch.dict(os.environ, {"AGENT_DASHBOARD_TOKEN": "secret-token"}):
        h = _mock_request(
            path="/api/results",
            headers={"Authorization": "Bearer wrong"},
        )
        serve.Handler.do_GET(h)
        h.send_response.assert_called_once_with(401)
        wfile_val = h.wfile.getvalue()
        data = json.loads(wfile_val)
        assert "Invalid" in data["error"]


def test_require_auth_allowed():
    """Test _require_auth in dev mode (no raise)."""
    with patch.dict(os.environ, {}, clear=True):
        h = _mock_request()
        # Should not call send_response — just returns
        serve.Handler._require_auth(h)
        h.send_response.assert_not_called()


def test_do_get_exception_handling():
    """Test that do_GET catches exceptions gracefully (500 JSON)."""
    h = _mock_request(path="/api/results")
    serve.Handler.db_path = "/nonexistent/path.db"
    serve.Handler.do_GET(h)
    h.send_response.assert_called_once_with(500)
    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert "Internal Server Error" in data["error"]


def test_log_message():
    """Test log_message uses logger."""
    h = _mock_request()
    with patch.object(serve.logger, "info") as mock_log:
        serve.Handler.log_message(h, "GET %s", "/api/results")
        mock_log.assert_called_once()


def test_timeline_paginated_with_job_id_filter(tmp_path):
    """Test timeline pagination with job_id filter (covers lines 466-467)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("tjf_job", "TJF", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("tjf_job", "已投递", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (app_id, "", "已投递"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    params = {"page": ["1"], "page_size": ["10"], "job_id": ["tjf_job"]}
    h = _mock_request()
    serve.Handler._api_timeline(h, params)

    wfile_val = h.wfile.getvalue()
    data = json.loads(wfile_val)
    assert data["total"] == 1
    assert data["items"][0]["job_id"] == "tjf_job"
