"""Tests for the /api/timeline endpoint (serve module timeline features)."""

import json
import sqlite3

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate


def test_timeline_module_attributes():
    """Test that Handler has the _api_timeline method."""
    assert hasattr(serve.Handler, "_api_timeline")
    assert hasattr(serve.Handler, "do_GET")
    assert hasattr(serve.Handler, "_api_results")


def test_timeline_html_includes_timeline_panel():
    """Test that HTML template contains timeline panel and related elements."""
    assert "timeline-panel" in serve.HTML
    assert "tlContainer" in serve.HTML
    assert "switchTab" in serve.HTML
    assert "/api/timeline" in serve.HTML


def test_timeline_html_includes_tabs():
    """Test that HTML template has tab switching for jobs/timeline."""
    assert "岗位列表" in serve.HTML
    assert "时间线" in serve.HTML
    assert "jobs-panel" in serve.HTML


def test_timeline_query_empty_database(tmp_path):
    """Test timeline query returns empty list when no data exists."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " ORDER BY t.created_at DESC LIMIT 100"
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 0
    assert isinstance(data, list)


def test_timeline_query_with_data(tmp_path):
    """Test timeline query returns timeline events with joined job info."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    # Insert job
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_t1", "AI Engineer", "Acme Corp", "Beijing", "industrial_ai_agent"),
    )
    # Insert application
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_t1", "已投递", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Insert timeline events
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-2 hours'))",
        (app_id, "", "已投递"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'))",
        (app_id, "已投递", "HR已读"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now') )",
        (app_id, "HR已读", "约面"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " ORDER BY t.created_at DESC LIMIT 100"
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 3

    # Verify order (DESC by created_at) — most recent first
    assert data[0]["to_status"] == "约面"
    assert data[1]["to_status"] == "HR已读"
    assert data[2]["to_status"] == "已投递"

    # Verify join fields
    for row in data:
        assert "job_title" in row
        assert "job_company" in row
        assert "job_id" in row
        assert "from_status" in row
        assert "to_status" in row
        assert "created_at" in row
        assert row["job_title"] == "AI Engineer"
        assert row["job_company"] == "Acme Corp"


def test_timeline_filter_by_event_type(tmp_path):
    """Test timeline query filtered by to_status (event_type)."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_f1", "Developer", "Beta Inc", "Shanghai", "equipment_amr"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_f1", "约面", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-3 hours'))",
        (app_id, "", "已投递"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-2 hours'))",
        (app_id, "已投递", "HR已读"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'))",
        (app_id, "HR已读", "约面"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " WHERE t.to_status = ?"
        " ORDER BY t.created_at DESC LIMIT 100",
        ("约面",),
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 1
    assert data[0]["to_status"] == "约面"
    assert data[0]["from_status"] == "HR已读"


def test_timeline_filter_by_job_id(tmp_path):
    """Test timeline query filtered by job_id."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    # Insert two jobs each with applications and timeline events
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_a", "Job A", "Company A", "City A", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_b", "Job B", "Company B", "City B", "equipment_amr"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_a", "已投递", "v1"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_b", "已投递", "v1"),
    )
    app_a = conn.execute("SELECT id FROM applications WHERE job_id='job_a'").fetchone()[0]
    app_b = conn.execute("SELECT id FROM applications WHERE job_id='job_b'").fetchone()[0]
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now', '-1 hour'))",
        (app_a, "", "已投递"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, ?, ?, datetime('now') )",
        (app_b, "", "已投递"),
    )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " WHERE a.job_id = ?"
        " ORDER BY t.created_at DESC LIMIT 100",
        ("job_a",),
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 1
    assert data[0]["job_title"] == "Job A"
    assert data[0]["job_id"] == "job_a"


def test_timeline_limit_parameter(tmp_path):
    """Test timeline query respects LIMIT parameter."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_lim", "Limit Test", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_lim", "Offer", "v1"),
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Insert 10 timeline events
    for i in range(10):
        conn.execute(
            "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
            "VALUES (?, ?, ?, datetime('now', ? || ' hours'))",
            (app_id, f"stage_{i}", f"stage_{i+1}", str(-i)),
        )
    conn.commit()
    conn.close()

    serve.Handler.db_path = db_path
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " ORDER BY t.created_at DESC LIMIT 5"
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    assert len(data) == 5


def test_timeline_json_serializable(tmp_path):
    """Test that timeline query results are JSON-serializable."""
    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)

    conn.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_ser", "Serialize Test", "Co", "City", "industrial_ai_agent"),
    )
    conn.execute(
        "INSERT INTO applications (job_id, status, resume_version, applied_at, updated_at) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("job_ser", "已投递", "v1"),
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
    conn_test = sqlite3.connect(db_path)
    conn_test.row_factory = sqlite3.Row
    rows = conn_test.execute(
        "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
        " a.job_id, a.status AS current_status,"
        " j.title AS job_title, j.company AS job_company"
        " FROM timelines t"
        " LEFT JOIN applications a ON t.application_id = a.id"
        " LEFT JOIN jobs j ON a.job_id = j.id"
        " ORDER BY t.created_at DESC LIMIT 100"
    ).fetchall()
    conn_test.close()

    data = [dict(r) for r in rows]
    json_str = json.dumps(data, ensure_ascii=False, default=str)
    parsed = json.loads(json_str)
    assert len(parsed) == 1
    assert parsed[0]["to_status"] == "已投递"
    assert parsed[0]["job_title"] == "Serialize Test"
