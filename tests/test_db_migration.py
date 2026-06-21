"""Tests for schema-versioned database migration."""

import sqlite3

import pytest

from agent_core.storage.db import SCHEMA_VERSION, get_db, migrate


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a fresh SQLite database file."""
    return str(tmp_path / "test.db")


# ---------- clean database: migrate from 0 to latest ----------


def test_clean_db_migrates_to_latest(tmp_db):
    """A brand-new database should migrate from nothing to SCHEMA_VERSION."""
    conn = get_db(tmp_db)
    migrate(conn)

    # Verify schema_version table contains the final version
    row = conn.execute(
        "SELECT version, applied_at FROM schema_version WHERE version = ?",
        (SCHEMA_VERSION,),
    ).fetchone()
    assert row is not None, f"schema_version should have v{SCHEMA_VERSION}"
    assert row["applied_at"] is not None

    # Verify core tables exist
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in (
        "jobs",
        "applications",
        "platform_sessions",
        "schedules",
        "search_status",
        "timelines",
        "schema_version",
    ):
        assert expected in tables, f"Table '{expected}' should exist"

    # Verify indexes exist
    indexes = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    for expected in (
        "idx_jobs_direction",
        "idx_jobs_company",
        "idx_applications_job",
        "idx_timelines_app",
        "idx_search_status_search",
    ):
        assert expected in indexes, f"Index '{expected}' should exist"

    # Verify the version trace: should have entries for v1 and v2
    versions = [
        row["version"]
        for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
    ]
    assert versions == [1, 2], f"Expected versions [1, 2], got {versions}"

    conn.close()


# ---------- legacy database: upgrade from pre-versioning state ----------


def test_legacy_db_upgrades_from_existing_tables(tmp_db):
    """A database that predates schema_version should be detected and upgraded."""
    # Create a "legacy" DB: create the jobs table manually, no schema_version
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            company_normalized TEXT NOT NULL DEFAULT '',
            location TEXT DEFAULT '',
            salary_min INTEGER,
            salary_max INTEGER,
            description TEXT DEFAULT '',
            platforms TEXT DEFAULT '[]',
            urls TEXT DEFAULT '{}',
            direction TEXT DEFAULT '',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_new INTEGER DEFAULT 1
        )
    """
    )
    conn.execute(
        "INSERT INTO jobs (id, title, company, first_seen, last_seen) VALUES (?,?,?,?,?)",
        ("j1", "Engineer", "ACME", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    # Now connect and migrate — should detect v1, then apply v2
    conn = get_db(tmp_db)
    migrate(conn)

    # Verify the legacy data survived
    row = conn.execute("SELECT * FROM jobs WHERE id = 'j1'").fetchone()
    assert row is not None
    assert row["title"] == "Engineer"
    assert row["company"] == "ACME"
    # v2 migration should have added security_id and lid columns
    assert row["security_id"] == ""
    assert row["lid"] == ""

    # Verify version is now at SCHEMA_VERSION
    max_v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert max_v == SCHEMA_VERSION

    conn.close()


# ---------- idempotent: repeated migrate is safe ----------


def test_migrate_is_idempotent(tmp_db):
    """Running migrate multiple times should not error or duplicate version entries."""
    conn = get_db(tmp_db)

    migrate(conn)
    v1_count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]

    # Run again — should be safe
    migrate(conn)
    v2_count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]

    assert v1_count == v2_count == SCHEMA_VERSION, (
        f"Version count should remain {SCHEMA_VERSION}, " f"got v1={v1_count}, v2={v2_count}"
    )

    conn.close()


# ---------- SCHEMA_VERSION constant is kept in sync ----------


def test_schema_version_matches_migrations():
    """Ensure SCHEMA_VERSION matches the highest migration number."""
    from agent_core.storage import db

    max_migration = max(v for v, _ in db._MIGRATIONS)
    assert db.SCHEMA_VERSION == max_migration, (
        f"SCHEMA_VERSION ({db.SCHEMA_VERSION}) does not match "
        f"highest migration ({max_migration})"
    )
