"""Tests for generated_files cataloging and backfill."""

from pathlib import Path

from agent_core.pipeline.file_catalog import (
    TYPE_COVER_LETTER,
    TYPE_INTERVIEW_PREP,
    TYPE_MOCK_INTERVIEW,
    TYPE_TAILORED_RESUME,
    backfill_from_disk,
    catalog_file,
)
from agent_core.storage.db import get_db, migrate


def _db(tmp_path):
    db = str(tmp_path / "catalog.db")
    conn = get_db(db)
    migrate(conn)
    return conn


def test_catalog_file_inserts_and_replaces(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO jobs (id, title, company, first_seen, last_seen) "
        "VALUES ('j1', '工程师', 'ACME', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    path = str(tmp_path / "out.md")
    Path(path).write_text("x", encoding="utf-8")
    catalog_file(conn, "j1", TYPE_TAILORED_RESUME, path, company="ACME", job_title="工程师")
    row = conn.execute("SELECT * FROM generated_files").fetchone()
    assert row["job_id"] == "j1"
    assert row["file_type"] == TYPE_TAILORED_RESUME
    assert row["company"] == "ACME"

    # Re-run same path -> replace, not duplicate.
    catalog_file(conn, "j1", TYPE_TAILORED_RESUME, path, company="ACME", job_title="工程师")
    count = conn.execute("SELECT COUNT(*) FROM generated_files").fetchone()[0]
    assert count == 1
    conn.close()


def test_backfill_from_disk_catalogs_legacy_files(tmp_path):
    conn = _db(tmp_path)
    out = tmp_path / "output"
    out.mkdir()
    (out / "公司_岗位_mock_interview.md").write_text("m", encoding="utf-8")
    (out / "公司_岗位_realtime_mock.md").write_text("r", encoding="utf-8")
    (out / "公司_岗位_interview.md").write_text("i", encoding="utf-8")
    (out / "公司_岗位_hrmsg.md").write_text("h", encoding="utf-8")
    (out / "公司_岗位.md").write_text("t", encoding="utf-8")
    (out / "公司_岗位.docx").write_text("d", encoding="utf-8")

    n = backfill_from_disk(conn, output_dir=str(out))
    assert n == 6
    types = {r["file_type"] for r in conn.execute("SELECT DISTINCT file_type FROM generated_files")}
    assert TYPE_MOCK_INTERVIEW in types
    assert TYPE_INTERVIEW_PREP in types
    assert TYPE_COVER_LETTER in types
    assert TYPE_TAILORED_RESUME in types

    # Second run should not duplicate.
    assert backfill_from_disk(conn, output_dir=str(out)) == 0
    conn.close()


def test_backfill_from_disk_missing_dir_returns_zero(tmp_path):
    conn = _db(tmp_path)
    assert backfill_from_disk(conn, output_dir=str(tmp_path / "nope")) == 0
    conn.close()
