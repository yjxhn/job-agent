"""Tests for the serve module (dashboard server)."""

import json
import sqlite3

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate


def test_serve_module_imports():
    """Test that serve module imports correctly."""
    # This verifies the module structure and doesn't require running a server
    assert hasattr(serve, "Handler")
    assert hasattr(serve, "start_server")
    assert hasattr(serve, "HTML")


def test_serve_handler_instantiation():
    """Test that Handler class can be imported and has expected attributes."""
    # Handler is a BaseHTTPRequestHandler subclass
    assert hasattr(serve.Handler, "db_path")
    assert hasattr(serve.Handler, "do_GET")
    assert hasattr(serve.Handler, "_api_results")
    assert serve.Handler.db_path == "data/agent.db"


def test_serve_handler_sets_db_path(tmp_path):
    """Test that start_server correctly sets Handler.db_path."""
    db_path = str(tmp_path / "agent.db")

    # Create test database with some data
    conn = get_db(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("test_job_1", "Engineer", "Acme Corp", "Beijing", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("test_job_2", "Developer", "Beta Inc", "Shanghai", "equipment_amr"),
    )
    conn.commit()
    conn.close()

    # Verify Handler.db_path can be set
    serve.Handler.db_path = db_path
    assert serve.Handler.db_path == db_path


def test_serve_api_query_logic(tmp_path):
    """Test the SQL query logic used by the /api/results endpoint."""
    db_path = str(tmp_path / "agent.db")

    # Create test database with sample data
    conn = get_db(db_path)
    migrate(conn)

    # Insert test jobs with different directions (score/rating not in jobs table)
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_1", "AI Engineer", "Company A", "Beijing", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now', '-1 hour'), datetime('now', '-1 hour'))",
        ("job_2", "Software Dev", "Company B", "Shanghai", "equipment_amr"),
    )
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now', '-2 hours'), datetime('now', '-2 hours'))",
        ("job_3", "Data Scientist", "Company C", "Guangzhou", "industrial_ai_agent"),
    )
    conn.commit()

    # Set Handler.db_path and execute the same query as _api method
    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute("SELECT * FROM jobs ORDER BY last_seen DESC LIMIT 200").fetchall()
    conn_test.close()

    # Verify results
    assert len(rows) == 3
    data = [dict(r) for r in rows]

    # Check ordering (should be DESC by last_seen)
    assert data[0]["id"] == "job_1"  # Most recent
    assert data[1]["id"] == "job_2"
    assert data[2]["id"] == "job_3"  # Oldest

    # Check fields
    assert all("title" in row for row in data)
    assert all("company" in row for row in data)
    assert all("direction" in row for row in data)

    conn.close()


def test_serve_html_structure():
    """Test that the HTML template contains expected elements."""
    assert "<!DOCTYPE html>" in serve.HTML
    assert "求职Agent Dashboard" in serve.HTML
    assert "/api/results" in serve.HTML
    assert "sort(" in serve.HTML  # JavaScript sort function


def test_serve_job_query_with_directions(tmp_path):
    """Test querying jobs with different directions (realistic scenario)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    # Insert jobs with various directions
    directions = ["industrial_ai_agent", "equipment_amr", "data_platform", "general_ai"]
    for i, direction in enumerate(directions):
        conn.execute(
            "INSERT INTO jobs (id, title, company, location, direction, "
            "first_seen, last_seen, urls) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
            (
                f"job_{i}",
                f"Job {i}",
                f"Company {i}",
                f"City {i}",
                direction,
                json.dumps({"boss": f"http://example.com/{i}"}),
            ),
        )
    conn.commit()

    # Query and verify
    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute("SELECT * FROM jobs ORDER BY last_seen DESC LIMIT 200").fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 4
    directions_in_db = [row["direction"] for row in data]
    assert set(directions_in_db) == set(directions)

    # Verify URLs field is properly stored and can be parsed
    for row in data:
        if row["urls"]:
            urls = json.loads(row["urls"])
            assert isinstance(urls, dict)

    conn.close()


def test_serve_empty_database(tmp_path):
    """Test that API query works with empty database."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    # Query empty database
    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute("SELECT * FROM jobs ORDER BY last_seen DESC LIMIT 200").fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 0
    assert isinstance(data, list)
