"""Application tracking: 7-stage lifecycle, timeline, manual entry."""

import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

STATUS_FLOW = {
    "已投递": ["HR已读", "约面", "已终止"],
    "HR已读": ["约面", "已终止"],
    "约面": ["一面", "已终止"],
    "一面": ["二面", "已终止"],
    "二面": ["Offer", "已终止"],
    "Offer": ["入职", "已终止"],
    "入职": [],
    "已终止": [],
}


def add_application(db, job_id, resume_version="", notes="") -> int:
    """Record a new job application. Creates minimal job entry if not in DB. Skips duplicate."""
    # Check for existing application for same job (avoid duplicates)
    dup = db.execute(
        "SELECT id FROM applications WHERE job_id=? AND status='已投递'", (job_id,)
    ).fetchone()
    if dup:
        logger.warning(f"[Track] Job {job_id[:8]} already tracked as #{dup['id']} — skipping")
        return dup["id"]

    # Check if job exists; if not, create minimal record for external applications
    existing = db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not existing:
        now = _now()
        db.execute(
            "INSERT OR IGNORE INTO jobs (id,title,company,first_seen,last_seen) "
            "VALUES (?,?,?,?,?)",
            (job_id, f"外部投递-{job_id[:8]}", "未知公司", now, now),
        )
        db.commit()
        logger.info(f"[Track] Created placeholder job for external application: {job_id[:8]}")

    now = _now()
    cur = db.execute(
        "INSERT INTO applications (job_id,status,resume_version,applied_at,updated_at,notes) "
        "VALUES (?,'已投递',?,?,?,?)",
        (job_id, resume_version, now, now, notes),
    )
    db.commit()
    logger.info(f"[Track] #{cur.lastrowid}: job {job_id[:8]}")
    return cur.lastrowid


def update_status(db, app_id, new_status) -> dict:
    """Advance application to a valid next status."""
    row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise ValueError(f"Application #{app_id} not found")
    current = row["status"]
    allowed = STATUS_FLOW.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"Invalid: {current} -> {new_status}. Allowed: {allowed}")
    now = _now()
    db.execute(
        "UPDATE applications SET status=?, updated_at=? WHERE id=?",
        (new_status, now, app_id),
    )
    db.commit()
    _add_timeline(db, app_id, current, new_status, now)
    logger.info(f"[Track] #{app_id}: {current} -> {new_status}")
    return get_application(db, app_id)


def list_applications(db, status_filter=None) -> list[dict]:
    """List applications, optionally filtered by status."""
    if status_filter:
        rows = db.execute(
            "SELECT * FROM applications WHERE status=? ORDER BY updated_at DESC", (status_filter,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    return [_enrich(dict(r), db) for r in rows]


def get_application(db, app_id) -> dict:
    """Get single application with enriched job info."""
    row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise ValueError(f"Application #{app_id} not found")
    return _enrich(dict(row), db)


def _enrich(app, db):
    try:
        job = db.execute(
            "SELECT title,company,location,urls FROM jobs WHERE id=?", (app["job_id"],)
        ).fetchone()
        if job:
            app["job_title"] = job["title"]
            app["job_company"] = job["company"]
            app["job_location"] = job["location"]
            app["job_urls"] = json.loads(job.get("urls", "{}"))
    except Exception as e:
        # F5: was `except: pass` — surface enrichment failures
        logger.warning(f"[Track] _enrich failed for app {app.get('id','?')}: {e}")
    return app


def _add_timeline(db, app_id, frm, to, ts):
    try:
        db.execute(
            "INSERT INTO timelines (application_id,from_status,to_status,created_at) "
            "VALUES (?,?,?,?)",
            (app_id, frm, to, ts),
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Timeline: {e}")


def get_timeline(db, app_id) -> list[dict]:
    """Get status change history for an application."""
    rows = db.execute(
        "SELECT * FROM timelines WHERE application_id=? ORDER BY created_at ASC", (app_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def create_timeline_table(db):
    """Migration helper: ensure timelines table exists."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS timelines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (application_id) REFERENCES applications(id))"""
    )
    db.commit()


def _now():
    return datetime.now(UTC).isoformat()
