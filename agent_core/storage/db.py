"""SQLite database connection and migration with schema versioning."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Current schema version — bump this when adding new migrations below
SCHEMA_VERSION = 12


def get_db(db_path: str = "data/agent.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Avoid immediate "database is locked" under concurrent dashboard/CLI/scheduler
    # writers; 5s is a sane local-machine default (busy handler retries internally).
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def db_connection(db_path: str = "data/agent.db"):
    """Open a connection and ALWAYS close it, even on error.

    Preferred over raw ``get_db()`` for one-shot helpers (the caller of
    ``get_db()`` owns the close and a missed close leaks a connection/file
    handle; WAL also keeps -wal/-shm files around until close).
    """
    conn = get_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """
    )


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
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()}
    for col in ("security_id", "lid"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT ''")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Create match_results and pipeline_runs tables."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS match_results (
            job_id TEXT PRIMARY KEY,
            match_score INTEGER NOT NULL DEFAULT 0,
            match_reason TEXT DEFAULT '',
            missing_skills TEXT DEFAULT '[]',
            strengths TEXT DEFAULT '[]',
            job_title TEXT DEFAULT '',
            company TEXT DEFAULT '',
            direction TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage TEXT NOT NULL,
            job_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_match_results_score ON match_results(match_score);
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage ON pipeline_runs(stage);
    """
    )


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Add user_flag column to jobs for manual filtering (accept/reject)."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()}
    for col, col_type in (("user_flag", "TEXT DEFAULT ''"),):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Create generated_files table.

    Catalogs every artifact a pipeline tool writes to output/ (tailored resume,
    cover letter, interview prep, mock interview). Lets the dashboard show
    "which job is this file for?" and "when was it generated?" without relying
    on filesystem mtime + filename-substring guessing (which was fragile:
    _mock_interview collided with _interview, and a stray .md in output/ got
    mislabeled as a tailored resume).

    job_id is nullable because mock_interview files generated via CLI may not
    have a job row (and historical files predating this migration don't either
    — they get backfilled with job_id=NULL on first scan).
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS generated_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            file_type TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            size INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            direction TEXT DEFAULT '',
            company TEXT DEFAULT '',
            job_title TEXT DEFAULT '',
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_generated_files_job ON generated_files(job_id);
        CREATE INDEX IF NOT EXISTS idx_generated_files_type ON generated_files(file_type);
    """
    )


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Add reasoning column to match_results.

    Stores the LLM's chain-of-thought (reasoning_content from thinking mode)
    so each match score is auditable — you can see exactly how the model
    arrived at a score, not just the final number. Without this, thinking
    mode produces reasoning that gets discarded after the call, making it
    impossible to debug why a score was high/low.

    Also adds prompt_version to allow A/B comparison when the match prompt
    changes (default 'v1' for legacy rows).
    """
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info('match_results')").fetchall()
    }
    for col, col_type, default in (
        ("reasoning", "TEXT", "''"),
        ("prompt_version", "TEXT", "'v1'"),
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE match_results ADD COLUMN {col} {col_type} DEFAULT {default}")


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Create match_feedback table for human calibration of LLM scores."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS match_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            direction TEXT DEFAULT '',
            feedback_type TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_match_feedback_job ON match_feedback(job_id);
    """
    )


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """Add published_at column to jobs for platform-reported publish time."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()}
    if "published_at" not in existing_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN published_at TEXT DEFAULT ''")


def _migrate_v9(conn: sqlite3.Connection) -> None:
    """Create material_drafts table for resume + HR-message draft review.

    Stores per-job draft pairs (tailored resume markdown + HR outreach message)
    generated from the match tab. Status flows draft -> confirmed; regenerating
    overwrites the row (version counts regenerations, no history kept). On
    confirm, the content is saved to output/ and cataloged into generated_files.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS material_drafts (
            job_id TEXT PRIMARY KEY,
            resume_md TEXT DEFAULT '',
            hr_message TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            feedback TEXT DEFAULT '',
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_material_drafts_status ON material_drafts(status);
    """
    )


def _migrate_v10(conn: sqlite3.Connection) -> None:
    """Enforce one application per job_id (v10).

    applications.job_id had no UNIQUE constraint, so re-confirming materials
    (serve.py ``INSERT OR IGNORE`` -- the IGNORE never fired without a unique
    constraint) or re-adding a job after its status had advanced created
    duplicate rows. Operating by job_id then updated every duplicate at once,
    which is how a batch edit on 2 selected rows ended up changing 3.

    Deduplicate first (keep the newest row per job_id -- greatest updated_at,
    tie-break greatest id), then replace the plain idx_applications_job index
    with a UNIQUE one so duplicates cannot come back.
    """
    # Guard: a legacy database detected as v1 may not actually have every v1
    # table (test_legacy_db_upgrades_from_existing_tables creates only jobs).
    # Skip if applications is missing -- nothing to dedup, no index to build.
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='applications'"
    ).fetchone()
    if not has_table:
        return
    conn.execute(
        """
        DELETE FROM applications
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id
                           ORDER BY updated_at DESC, id DESC
                       ) AS rn
                FROM applications
            ) WHERE rn > 1
        )
        """
    )
    conn.execute("DROP INDEX IF EXISTS idx_applications_job")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id)")


def _migrate_v11(conn: sqlite3.Connection) -> None:
    """Create offer_evaluations table for caching per-offer eval results.

    The Offer tab is file-driven: each uploaded offer .txt in offers/
    can be evaluated, and the result (scores + pros/cons + parsed fields) is
    cached here so "预览评估结果" can re-render the radar chart without a
    fresh LLM call. Keyed by offer_file_name (UNIQUE) -- one cached eval per
    offer file; re-evaluating overwrites. parsed_fields holds the 17-field
    parse for re-display; eval_input holds the 8 mapped fields fed to
    evaluate(); result holds the LLM's scoring JSON.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS offer_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_file_name TEXT NOT NULL UNIQUE,
            offer_file_path TEXT NOT NULL,
            company TEXT DEFAULT '',
            title TEXT DEFAULT '',
            parsed_fields TEXT DEFAULT '{}',
            eval_input TEXT DEFAULT '{}',
            result TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_offer_eval_file ON offer_evaluations(offer_file_name);
    """
    )


def _migrate_v12(conn: sqlite3.Connection) -> None:
    """v12: interview_prep 草稿状态支持 (材料审核台确认后才归档).

    material_drafts previously had no record of the interview-prep file —
    it was generated and immediately cataloged into generated_files, so it
    skipped the review flow entirely. Now the generated .md content is stored
    here (interview_prep_md) for the 材料审核台 preview, and interview_confirmed
    marks whether the user confirmed it (which is what triggers cataloging
    the on-disk .md/.json into generated_files).
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(material_drafts)").fetchall()]
    if "interview_prep_md" not in cols:
        conn.execute("ALTER TABLE material_drafts ADD COLUMN interview_prep_md TEXT")
    if "interview_confirmed" not in cols:
        conn.execute("ALTER TABLE material_drafts ADD COLUMN interview_confirmed INTEGER DEFAULT 0")


# Ordered list of (version, migration_function)
_MIGRATIONS = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
    (8, _migrate_v8),
    (9, _migrate_v9),
    (10, _migrate_v10),
    (11, _migrate_v11),
    (12, _migrate_v12),
]


def migrate(conn: sqlite3.Connection) -> None:
    _ensure_schema_version_table(conn)

    # Detect starting version for legacy databases (no schema_version entries)
    current = _get_version(conn)
    if current == 0:
        current = _detect_existing_version(conn)
        if current > 0:
            _set_version(conn, current)

    migrated = False
    for version, fn in _MIGRATIONS:
        if version > current:
            logger.info(f"Running migration v{version}...")
            # Commit any pending write (the schema_version table creation or
            # the previous migration's version record) BEFORE cloning the
            # database: sqlite3's backup API deadlocks while the source
            # connection holds an uncommitted INSERT transaction.
            conn.commit()
            # Rehearse the migration on an in-memory clone before applying it
            # to the real database. An outer transaction/SAVEPOINT cannot
            # guard the loop: executescript inside a migration implicitly
            # commits and destroys any open savepoint. Rehearse-and-apply
            # guarantees a failed migration leaves the production schema
            # untouched at v{current}.
            mem = sqlite3.connect(":memory:")
            conn.backup(mem)
            try:
                fn(mem)
            except Exception:
                mem.close()
                logger.error(
                    f"Migration v{version} rehearsal failed — schema unchanged (still v{current})"
                )
                raise
            mem.close()
            fn(conn)
            _set_version(conn, version)
            current = version
            migrated = True

    conn.commit()
    if migrated:
        logger.info(f"Database migration complete (v{current})")
    else:
        logger.debug(f"Database schema is up to date (v{current})")
