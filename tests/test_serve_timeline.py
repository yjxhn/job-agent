"""Tests for application timeline history (tracker.get_timeline).

The former /api/timeline HTTP endpoint was removed from serve.py; these
tests exercise the underlying tracker module (still used by the 投递追踪
tab and scheduler) directly.
"""

import json

from agent_core.storage.db import get_db, migrate
from agent_core.tracking import tracker


def _setup(tmp_path):
    """Create a migrated temp DB and return (db, app_id) for a tracked job."""
    db_path = str(tmp_path / "agent.db")
    db = get_db(db_path)
    migrate(db)
    # Job must exist before add_application (tracker skips placeholder creation
    # when the job row is present).
    db.execute(
        "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        ("job_t", "AI Engineer", "Acme Corp", "Beijing", "default"),
    )
    db.commit()
    app_id = tracker.add_application(db, "job_t", resume_version="v1")
    return db, app_id


def test_timeline_empty_database(tmp_path):
    """No status changes yet -> get_timeline returns an empty list."""
    db, app_id = _setup(tmp_path)
    try:
        assert tracker.get_timeline(db, app_id) == []
    finally:
        db.close()


def test_timeline_records_status_changes(tmp_path):
    """Each status advance appends a timeline row with from/to statuses."""
    db, app_id = _setup(tmp_path)
    try:
        tracker.update_status(db, app_id, "HR已读")
        tracker.update_status(db, app_id, "约面")
        rows = tracker.get_timeline(db, app_id)
        assert len(rows) == 2
        # get_timeline orders ASC (oldest first)
        assert rows[0]["from_status"] == "已投递"
        assert rows[0]["to_status"] == "HR已读"
        assert rows[1]["from_status"] == "HR已读"
        assert rows[1]["to_status"] == "约面"
    finally:
        db.close()


def test_timeline_filtered_by_application(tmp_path):
    """Timelines are scoped per application: other apps' rows don't leak in."""
    db, app_a = _setup(tmp_path)
    try:
        db.execute(
            "INSERT INTO jobs (id, title, company, location, direction, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("job_b", "Developer", "Beta Inc", "Shanghai", "default"),
        )
        db.commit()
        app_b = tracker.add_application(db, "job_b")
        tracker.update_status(db, app_a, "HR已读")
        tracker.update_status(db, app_b, "约面")
        rows_a = tracker.get_timeline(db, app_a)
        rows_b = tracker.get_timeline(db, app_b)
        assert len(rows_a) == 1
        assert rows_a[0]["application_id"] == app_a
        assert rows_a[0]["to_status"] == "HR已读"
        assert len(rows_b) == 1
        assert rows_b[0]["application_id"] == app_b
        assert rows_b[0]["to_status"] == "约面"
    finally:
        db.close()


def test_timeline_order_is_chronological(tmp_path):
    """Rows come back in insertion order regardless of timestamps."""
    db, app_id = _setup(tmp_path)
    try:
        tracker.update_status(db, app_id, "HR已读")
        tracker.update_status(db, app_id, "约面")
        tracker.update_status(db, app_id, "一面")
        rows = tracker.get_timeline(db, app_id)
        assert [r["to_status"] for r in rows] == ["HR已读", "约面", "一面"]
    finally:
        db.close()


def test_timeline_json_serializable(tmp_path):
    """Timeline rows are plain dicts, safe for JSON responses."""
    db, app_id = _setup(tmp_path)
    try:
        tracker.update_status(db, app_id, "HR已读")
        rows = tracker.get_timeline(db, app_id)
        json_str = json.dumps(rows, ensure_ascii=False, default=str)
        parsed = json.loads(json_str)
        assert len(parsed) == 1
        assert parsed[0]["to_status"] == "HR已读"
    finally:
        db.close()


def test_timeline_unknown_application_returns_empty(tmp_path):
    """get_timeline for an app with no history returns [] (never raises)."""
    db, app_id = _setup(tmp_path)
    try:
        assert tracker.get_timeline(db, app_id) == []
        assert tracker.get_timeline(db, 999999) == []
    finally:
        db.close()
