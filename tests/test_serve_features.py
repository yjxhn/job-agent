"""Tests for new serve.py features: auth, pagination, openapi, error handling."""

import io
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate

# ==================================================================== helpers ---


@pytest.fixture(autouse=True)
def _restore_handler_db_path():
    """Restore serve.Handler.db_path after each test.

    Several tests mutate the class attribute (serve.Handler.db_path = ...) and
    never restore it; a later assertion in tests/test_serve.py expecting the
    default "data/agent.db" then fails intermittently depending on collection
    order. This autouse fixture guarantees the attribute is always reset.
    """
    yield
    serve.Handler.db_path = "data/agent.db"


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
    assert "/api/flag/{job_id}" in spec["paths"]
    assert "/api/offer/evaluate" in spec["paths"]
    # /api/timeline was removed (no such route in serve.py); ensure it's gone
    assert "/api/timeline" not in spec["paths"]
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
    assert "<title>JobAgent</title>" in wfile_val


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


# =========================================================== _api_offer_compare regression ---


class TestApiOfferCompareRegression:
    """Regression tests for POST /api/offer/compare (2026-07-24 fix).

    Before the fix, _api_offer_compare called _send_json twice (the second
    after write-to-disk + catalog), causing headers-already-sent / BrokenPipe.
    After the fix: single _send_json, no write-to-disk, no catalog.
    """

    def test_offer_compare_single_response_no_side_effects(self, tmp_path, monkeypatch):
        # --- db with offer_evaluations rows ---
        db_path = str(tmp_path / "agent.db")
        conn = get_db(db_path)
        migrate(conn)
        now = "2026-07-24T00:00:00"
        conn.execute(
            "INSERT INTO offer_evaluations "
            "(offer_file_name, offer_file_path, company, title, parsed_fields, eval_input, "
            "result, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a.txt",
                "/f/a.txt",
                "ACorp",
                "SDE",
                '{"company":"ACorp"}',
                "{}",
                '{"overall_score":8}',
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO offer_evaluations "
            "(offer_file_name, offer_file_path, company, title, parsed_fields, eval_input, "
            "result, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "b.txt",
                "/f/b.txt",
                "BCorp",
                "PM",
                '{"company":"BCorp"}',
                "{}",
                '{"overall_score":7}',
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
        serve.Handler.db_path = db_path

        # --- tmp offers dir with .txt files ---
        offers_dir = tmp_path / "offers"
        offers_dir.mkdir()
        (offers_dir / "a.txt").write_text("公司名: ACorp\n职位名: SDE\n", encoding="utf-8")
        (offers_dir / "b.txt").write_text("公司名: BCorp\n职位名: PM\n", encoding="utf-8")

        # --- build handler ---
        h = _mock_request(path="/api/offer/compare")
        body = json.dumps({"file_names": ["a.txt", "b.txt"]}).encode()
        h.rfile = io.BytesIO(body)
        h.headers = {"Content-Length": str(len(body))}
        monkeypatch.setattr(serve.Handler, "_offers_dir", lambda self: str(offers_dir))

        # --- mock external dependencies ---
        mock_config = MagicMock()
        mock_provider = MagicMock()

        async def _fake_compare(_config, _provider, _offers):
            return "对比分析markdown"

        with (
            patch("agent_core.config.load_config", return_value=mock_config),
            patch("agent_core.llm.providers.create_provider", return_value=mock_provider),
            patch("agent_core.pipeline.offer_eval.compare", side_effect=_fake_compare),
        ):
            serve.Handler._api_offer_compare(h)

        # === assertions ===
        # 1. Single response: send_response called exactly once (core regression fix)
        assert (
            h.send_response.call_count == 1
        ), f"Expected 1 send_response, got {h.send_response.call_count}"

        # 2. Response body is valid JSON with expected fields
        resp = json.loads(h.wfile.getvalue())
        assert resp.get("ok") is True
        assert len(resp.get("offers", [])) == 2
        assert resp.get("best") is not None
        assert resp["analysis"] == "对比分析markdown"

        # 3. No write-to-disk side effects
        compare_files = list(offers_dir.glob("*offer对比*"))
        output_dir = tmp_path / "output"
        output_files = list(output_dir.glob("*offer_compare*")) if output_dir.exists() else []
        assert len(compare_files) == 0, f"Unexpected compare files in offers dir: {compare_files}"
        assert len(output_files) == 0, f"Unexpected output files: {output_files}"

    def test_offer_compare_save_is_separate_endpoint(self):
        """Confirm write-disk logic lives in _api_offer_compare_save, not _api_offer_compare."""
        import re

        serve_py = os.path.join(os.path.dirname(__file__), "..", "agent_core", "server", "serve.py")
        src = open(serve_py, encoding="utf-8").read()
        m = re.search(r"(?ms)^    def _api_offer_compare\b.*?(?=^    def )", src)
        assert m is not None, "Could not find _api_offer_compare method in serve.py"
        body = m.group(0)
        assert "catalog_file" not in body, (
            "catalog_file found in _api_offer_compare; "
            "write-disk logic should be in _api_offer_compare_save"
        )
        write_opens = re.findall(r'open\([^)]*["\']w["\']', body)
        assert (
            len(write_opens) == 0
        ), f"Write-mode open() found in _api_offer_compare: {write_opens}"


# ==================================================== dashboard JS syntax ---


def test_dashboard_embedded_js_syntax(tmp_path):
    """Inline dashboard JS must parse with node --check when Node is available."""
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    scripts = re.findall(r"<script>(.*?)</script>", serve.HTML, re.S)
    assert scripts, "dashboard HTML must contain inline scripts"
    for idx, js in enumerate(scripts):
        f = tmp_path / f"dashboard_{idx}.js"
        f.write_text(js, encoding="utf-8")
        subprocess.run([node, "--check", str(f)], check=True, capture_output=True)
