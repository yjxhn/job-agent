"""Unit tests for materials API DB logic + v9 material_drafts migration.

Each test exercises the SQL that the corresponding _api_materials_* handler in
serve.py runs, against an isolated tmp DB. LLM calls and HTTP wiring are out of
scope here (covered by the pipeline tests for tailor/cover_letter); this file
locks down the draft-table state machine: generate (insert+version), regenerate
(update+version+feedback), confirm (status flip), drafts (status filter).
"""

import pytest

from agent_core.storage.db import SCHEMA_VERSION, get_db, migrate


@pytest.fixture
def tmp_db(tmp_path):
    p = str(tmp_path / "materials.db")
    conn = get_db(p)
    migrate(conn)
    conn.execute(
        "INSERT INTO jobs (id,title,company,location,description,urls,platforms,direction,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "j1",
            "前端工程师",
            "字节跳动",
            "北京",
            "React/TS 职位描述",
            "{}",
            "",
            "web",
            _now(),
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return p


def _now():
    return "2026-07-17T00:00:00+00:00"


def test_v9_creates_material_drafts_table(tmp_db):
    """v9 migration creates material_drafts with the expected columns."""
    assert SCHEMA_VERSION >= 9
    conn = get_db(tmp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info('material_drafts')")}
    conn.close()
    assert {
        "job_id",
        "resume_md",
        "hr_message",
        "status",
        "feedback",
        "version",
        "created_at",
        "updated_at",
    } <= cols


def test_generate_insert_overwrites_and_increments_version(tmp_db):
    """POST /api/materials/generate SQL: INSERT OR REPLACE + COALESCE(version)+1."""
    conn = get_db(tmp_db)
    sql = (
        "INSERT OR REPLACE INTO material_drafts "
        "(job_id,resume_md,hr_message,status,feedback,version,created_at,updated_at) "
        "VALUES (?,?,?,'draft','',"
        "COALESCE((SELECT version FROM material_drafts WHERE job_id=?),0)+1,?,?)"
    )
    conn.execute(sql, ("j1", "r1", "h1", "j1", _now(), _now()))
    conn.execute(sql, ("j1", "r2", "h2", "j1", _now(), _now()))
    conn.commit()
    row = conn.execute(
        "SELECT resume_md,hr_message,version,status FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    conn.close()
    assert row[0] == "r2" and row[1] == "h2"
    assert row[2] == 2
    assert row[3] == "draft"


def test_regenerate_update_increments_version_and_saves_feedback(tmp_db):
    """POST /api/materials/regenerate SQL: UPDATE ... version+1, feedback persisted."""
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,feedback,version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("j1", "r1", "h1", "draft", "", 1, _now(), _now()),
    )
    conn.commit()
    conn.execute(
        "UPDATE material_drafts SET resume_md=?,hr_message=?,feedback=?,"
        "version=version+1,status='draft',updated_at=? WHERE job_id=?",
        ("r2", "h2", "再短一点，突出 React", _now(), "j1"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT resume_md,feedback,version,status FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    conn.close()
    assert row[0] == "r2" and row[1] == "再短一点，突出 React"
    assert row[2] == 2 and row[3] == "draft"


def test_confirm_flips_status_to_confirmed(tmp_db):
    """POST /api/materials/confirm SQL: UPDATE status='confirmed'."""
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("j1", "r1", "h1", "draft", 1, _now(), _now()),
    )
    conn.commit()
    conn.execute(
        "UPDATE material_drafts SET status='confirmed',updated_at=? WHERE job_id=?",
        (_now(), "j1"),
    )
    conn.commit()
    row = conn.execute("SELECT status FROM material_drafts WHERE job_id='j1'").fetchone()
    conn.close()
    assert row[0] == "confirmed"


def test_drafts_returns_only_draft_rows(tmp_db):
    """GET /api/materials/drafts SQL: WHERE status='draft' (confirmed excluded)."""
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("j1", "r1", "h1", "draft", 1, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO jobs (id,title,company,first_seen,last_seen) VALUES (?,?,?,?,?)",
        ("j2", "后端工程师", "阿里巴巴", _now(), _now()),
    )
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("j2", "r2", "h2", "confirmed", 1, _now(), _now()),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT job_id FROM material_drafts WHERE status='draft' ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    ids = [r["job_id"] for r in rows]
    assert "j1" in ids and "j2" not in ids
