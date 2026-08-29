"""Catalog generated files into the generated_files table.

Three pipeline tools (tailor_resume, generate_cover_letter, interview_prep)
write artifacts to output/. Until v5 the dashboard discovered them by scanning
the directory and guessing the type from the filename — which was fragile
(_mock_interview collided with _interview; a stray .md was mislabeled as a
tailored resume) and lost the job_id association entirely.

This module is the single write-side chokepoint: every tool that drops a file
in output/ calls `catalog_file(...)` so the row exists in generated_files with
the correct job_id, file_type, and created_at before the tool returns.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical file_type values stored in generated_files.file_type.
# Keep these in sync with the frontend labels in serve.py.
TYPE_TAILORED_RESUME = "tailor_resume"
TYPE_COVER_LETTER = "cover_letter"
TYPE_INTERVIEW_PREP = "interview_prep"
TYPE_MOCK_INTERVIEW = "mock_interview"
TYPE_OFFER_EVAL = "offer_eval"
TYPE_SALARY_ADVICE = "salary_advice"
# Comparison report between 2+ offers (saved to output/ + catalog).
TYPE_OFFER_COMPARE = "offer_compare"
# Uploaded offer input .txt files live in offers/ (NOT cataloged into
# generated_files -- they are inputs, like resumes). This constant exists only
# for frontend label/color consistency, not for catalog_file() calls.
TYPE_OFFER_IMPORTED = "offer_imported"


def catalog_file(
    db: sqlite3.Connection,
    job_id: str | None,
    file_type: str,
    file_path: str,
    *,
    direction: str = "",
    company: str = "",
    job_title: str = "",
) -> None:
    """Insert (or replace on path) a generated_files row.

    Re-run safe: if the same path is regenerated for the same job, the row's
    created_at is refreshed and size updated. UNIQUE(file_path) means we
    INSERT OR REPLACE so the catalog never holds stale duplicates.

    Failures are logged but never raised — a cataloging error must not break
    the user's "generate my resume" flow. The file on disk is the source of
    truth; the catalog is a convenience index.
    """
    try:
        p = Path(file_path)
        size = p.stat().st_size if p.exists() else 0
        now = datetime.now(UTC).isoformat()
        db.execute(
            """
            INSERT OR REPLACE INTO generated_files
                (job_id, file_type, file_name, file_path, size, created_at,
                 direction, company, job_title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                file_type,
                p.name,
                str(p).replace("\\", "/"),
                size,
                now,
                direction,
                company,
                job_title,
            ),
        )
        db.commit()
    except Exception as e:  # noqa: BLE001 — catalog is best-effort
        logger.warning(f"catalog_file({file_type}, {file_path}) failed: {e}")


def backfill_from_disk(db: sqlite3.Connection, output_dir: str = "output") -> int:
    """Scan output/ and insert rows for files not yet cataloged.

    Called once at server startup (after migrate) so pre-v5 files already on
    disk show up in the dashboard with the correct type. job_id is left NULL
    for these legacy files — there's no reliable way to recover it from a
    `{company}_{title}.md` filename alone.

    Returns the number of newly-cataloged files.
    """
    import re

    base = Path(output_dir)
    if not base.exists():
        return 0

    # Filename → file_type rules. Order matters: check mock_interview BEFORE
    # interview_prep because "_mock_interview.md" contains "_interview".
    rules = [
        (r"_mock_interview\.", TYPE_MOCK_INTERVIEW),
        (r"_realtime_mock\.", TYPE_MOCK_INTERVIEW),
        (r"_interview\.", TYPE_INTERVIEW_PREP),
        (r"_hrmsg\.", TYPE_COVER_LETTER),
        (r"_cover\.", TYPE_COVER_LETTER),
        (r"_salary_advice\.", TYPE_SALARY_ADVICE),
        # A .docx in output/ is always a tailored resume (only tailor emits docx).
        (r"\.docx$", TYPE_TAILORED_RESUME),
        # A bare .md (no _cover/_interview/_mock suffix) is a tailored resume.
        (r"\.md$", TYPE_TAILORED_RESUME),
    ]

    n = 0
    for p in sorted(base.iterdir(), reverse=True):
        if not p.is_file():
            continue
        name = p.name
        if not name.endswith((".md", ".docx")):
            continue
        # Skip if already cataloged (path is UNIQUE).
        existing = db.execute(
            "SELECT 1 FROM generated_files WHERE file_path = ?", (str(p).replace("\\", "/"),)
        ).fetchone()
        if existing:
            continue
        ftype = None
        for pat, t in rules:
            if re.search(pat, name):
                ftype = t
                break
        if ftype is None:
            continue
        try:
            size = p.stat().st_size
            now = datetime.now(UTC).isoformat()
            db.execute(
                """
                INSERT OR IGNORE INTO generated_files
                    (job_id, file_type, file_name, file_path, size, created_at)
                VALUES (NULL, ?, ?, ?, ?, ?)
                """,
                (ftype, name, str(p).replace("\\", "/"), size, now),
            )
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"backfill({name}) failed: {e}")
    if n:
        db.commit()
        logger.info(f"Backfilled {n} legacy generated files into generated_files")
    return n
