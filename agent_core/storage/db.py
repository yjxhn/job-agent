"""SQLite database connection and migration with schema versioning."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Current schema version — bump this when adding new migrations below
SCHEMA_VERSION = 2


def get_db(db_path: str = "data/agent.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)


def _get_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if row[0] is not None else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, now),
    )


def _detect_existing_version(conn: sqlite3.Connection) -> int:
    """Detect schema version for databases created before versioning was added."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if row[0] > 0:
        return 1  # Core tables exist, mark v1 as done
    return 0


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Create core tables and indexes."""
    sql = """
        CREATE TABLE IF NOT EXISTS jobs (
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
            is_new INTEGER DEFAULT 1,
            security_id TEXT DEFAULT '',
            lid TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '已投递',
            resume_version TEXT DEFAULT '',
            applied_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT DEFAULT '',
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS platform_sessions (
            platform TEXT PRIMARY KEY,
            cookie_data TEXT NOT NULL,
            expires_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            last_run_at TEXT,
            last_status TEXT DEFAULT '',
            last_result_count INTEGER DEFAULT 0,
            next_run_at TEXT
        );
        CREATE TABLE IF NOT EXISTS search_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL,
            result_count INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS timelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (application_id) REFERENCES applications(id)
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_direction ON jobs(direction);
        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_normalized);
        CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);
        CREATE INDEX IF NOT EXISTS idx_timelines_app ON timelines(application_id);
        CREATE INDEX IF NOT EXISTS idx_search_status_search ON search_status(search_id);
    """
    conn.executescript(sql)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add security_id and lid columns (for databases created before v1)."""
    for col in ("security_id", "lid"):
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists


# Ordered list of (version, migration_function)
_MIGRATIONS = [
    (1, _migrate_v1),
    (2, _migrate_v2),
]


def migrate(conn: sqlite3.Connection) -> None:
    _ensure_schema_version_table(conn)

    # Detect starting version for legacy databases (no schema_version entries)
    current = _get_version(conn)
    if current == 0:
        current = _detect_existing_version(conn)
        if current > 0:
            _set_version(conn, current)

    for version, fn in _MIGRATIONS:
        if version > current:
            logger.info(f"Running migration v{version}...")
            fn(conn)
            _set_version(conn, version)
            current = version

    conn.commit()
    logger.info(f"Database migration complete (v{current})")
