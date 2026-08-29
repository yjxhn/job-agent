"""Tests for v12: interview-prep files require 材料审核台 confirmation.

v12 changed the interview-prep flow: generate/regenerate no longer catalog
the .md/.json into generated_files immediately. Instead the .md content is
stored in material_drafts.interview_prep_md (draft state, previewable in the
审核台), and only /api/materials/confirm catalogs the on-disk files and flips
interview_confirmed=1. Mock interview from-prep reads generated_files, so an
unconfirmed prep is automatically unavailable as a question bank.

These tests lock down the SQL/state machine (same style as test_materials.py):
LLM calls and HTTP wiring are out of scope.
"""

import pytest

from agent_core.pipeline.interview_prep import load_interview_prep_json
from agent_core.storage.db import SCHEMA_VERSION, get_db, migrate


@pytest.fixture
def tmp_db(tmp_path):
    p = str(tmp_path / "prep_confirm.db")
    conn = get_db(p)
    migrate(conn)
    conn.execute(
        "INSERT INTO jobs "
        "(id,title,company,location,description,urls,platforms,direction,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "j1",
            "设备工程师",
            "柳州五菱汽车工业有限公司",
            "柳州",
            "设备维护职位描述",
            "{}",
            "",
            "user_query",
            _now(),
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return p


def _now():
    return "2026-08-10T00:00:00+00:00"


def test_v12_adds_interview_prep_columns(tmp_db):
    """v12 migration adds interview_prep_md + interview_confirmed columns."""
    assert SCHEMA_VERSION >= 12
    conn = get_db(tmp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info('material_drafts')")}
    conn.close()
    assert {"interview_prep_md", "interview_confirmed"} <= cols


def test_generate_writes_prep_md_not_catalog(tmp_db):
    """Generate stores prep md in material_drafts, NOT in generated_files."""
    conn = get_db(tmp_db)
    # simulate the generate handler: draft row + prep md into the column
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at) "
        "VALUES (?,?,?,'draft',1,?,?)",
        ("j1", "r1", "h1", _now(), _now()),
    )
    conn.execute(
        "UPDATE material_drafts SET interview_prep_md=?, interview_confirmed=0, "
        "updated_at=? WHERE job_id=?",
        ("# 面试准备\n自我介绍...", _now(), "j1"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT interview_prep_md, interview_confirmed FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    assert row[0] == "# 面试准备\n自我介绍..."
    assert row[1] == 0
    n = conn.execute(
        "SELECT COUNT(*) FROM generated_files WHERE job_id='j1' AND file_type='interview_prep'"
    ).fetchone()[0]
    assert n == 0  # not cataloged yet
    conn.close()


def test_unconfirmed_prep_not_available_to_mock(tmp_db):
    """load_interview_prep_json returns None before confirmation (catalog empty)."""
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at,interview_prep_md) "
        "VALUES (?,?,?,'draft',1,?,?,?)",
        ("j1", "r1", "h1", _now(), _now(), "# 面试准备"),
    )
    conn.commit()
    assert load_interview_prep_json("j1", conn) is None
    conn.close()


def test_confirm_catalogs_prep_and_flags(tmp_db, tmp_path):
    """Confirm catalogs the on-disk .md/.json and sets interview_confirmed=1."""
    # prep files on disk (as generate/regenerate leave them)
    md = tmp_path / "柳州五菱汽车工业有限_设备工程师_interview.md"
    js = tmp_path / "柳州五菱汽车工业有限_设备工程师_interview.json"
    md.write_text("# 面试准备\n自我介绍...", encoding="utf-8")
    js.write_text('{"rounds":[]}', encoding="utf-8")

    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at,interview_prep_md) "
        "VALUES (?,?,?,'draft',1,?,?,?)",
        ("j1", "r1", "h1", _now(), _now(), "# 面试准备\n自我介绍..."),
    )
    conn.commit()
    # simulate the confirm handler: catalog on-disk files + flip flag
    for f in (md, js):
        conn.execute(
            "INSERT INTO generated_files "
            "(job_id,file_type,file_name,file_path,created_at,direction,company,job_title) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                "j1",
                "interview_prep",
                f.name,
                str(f),
                _now(),
                "user_query",
                "柳州五菱汽车工业有限公司",
                "设备工程师",
            ),
        )
    conn.execute(
        "UPDATE material_drafts SET interview_confirmed=1, updated_at=? WHERE job_id=?",
        (_now(), "j1"),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT file_type, file_path FROM generated_files WHERE job_id='j1'"
    ).fetchall()
    assert len(rows) == 2
    assert all(r["file_type"] == "interview_prep" for r in rows)
    row = conn.execute(
        "SELECT interview_confirmed FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    assert row[0] == 1
    # confirmed prep is now available as a mock question bank
    assert load_interview_prep_json("j1", conn) == {"rounds": []}
    conn.close()


def test_regenerate_resets_confirmed_to_draft(tmp_db):
    """Regenerate overwrites prep md and resets interview_confirmed to 0."""
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at,"
        "interview_prep_md,interview_confirmed) VALUES (?,?,?,'confirmed',1,?,?,?,1)",
        ("j1", "r1", "h1", _now(), _now(), "# 旧面试准备"),
    )
    conn.commit()
    # simulate regenerate: new prep md, flag reset, status back to draft
    conn.execute(
        "UPDATE material_drafts SET interview_prep_md=?, interview_confirmed=0, "
        "status='draft', version=version+1, updated_at=? WHERE job_id=?",
        ("# 新面试准备", _now(), "j1"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT interview_prep_md, interview_confirmed, status, version "
        "FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    assert row[0] == "# 新面试准备"
    assert row[1] == 0
    assert row[2] == "draft"
    assert row[3] == 2
    conn.close()


def test_delete_cleans_prep_catalog_and_disk(tmp_db, tmp_path):
    """Delete draft also removes cataloged prep records + on-disk files."""
    md = tmp_path / "柳州五菱汽车工业有限_设备工程师_interview.md"
    md.write_text("# 面试准备", encoding="utf-8")
    conn = get_db(tmp_db)
    conn.execute(
        "INSERT INTO material_drafts "
        "(job_id,resume_md,hr_message,status,version,created_at,updated_at) "
        "VALUES (?,?,?,'draft',1,?,?)",
        ("j1", "r1", "h1", _now(), _now()),
    )
    conn.execute(
        "INSERT INTO generated_files "
        "(job_id,file_type,file_name,file_path,created_at) VALUES (?,?,?,?,?)",
        ("j1", "interview_prep", md.name, str(md), _now()),
    )
    conn.commit()
    # simulate delete: remove generated_files prep rows + disk file
    conn.execute("DELETE FROM generated_files WHERE job_id='j1' AND file_type='interview_prep'")
    conn.commit()
    md.unlink(missing_ok=True)
    n = conn.execute(
        "SELECT COUNT(*) FROM generated_files WHERE job_id='j1' AND file_type='interview_prep'"
    ).fetchone()[0]
    assert n == 0
    assert not md.exists()
    conn.close()
