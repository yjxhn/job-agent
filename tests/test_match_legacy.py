"""Comprehensive tests for the precision-match (精排) pipeline.

Covers:
- _parse: JSON extraction, fenced code blocks, trailing commas, malformed input.
- match_jobs: empty input, resume-cache load failure, JSON parse retry,
  min_score filtering, JD truncation note, reasoning capture, prompt_version
  tagging, concurrency, score sorting, skipped accounting.
- Backward-compat: legacy "score" field still honored by min_score / sort.

These tests mock the LLM provider so no network calls are made.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_core.pipeline import match as match_mod
from agent_core.pipeline.match import _parse, match_jobs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(
    *,
    job_id="j1",
    title="Python 后端",
    company="ACME",
    location="北京",
    salary_min=20000,
    salary_max=40000,
    description="需要 3 年 Python 经验，熟悉 FastAPI。",
    direction="default",
    resume_file="resumes/default.md",
    urls="{}",
):
    """Build the lightweight _Item object match_jobs consumes."""
    job = SimpleNamespace(
        id=job_id,
        title=title,
        company=company,
        location=location,
        salary_min=salary_min,
        salary_max=salary_max,
        description=description,
        direction=direction,
        urls=urls,
        platforms="[]",
    )
    return SimpleNamespace(job=job, resume_file=resume_file, direction=direction)


def _make_config(match_min_score=50, max_tokens=4096):
    cfg = SimpleNamespace(
        matching=SimpleNamespace(match_min_score=match_min_score),
        llm=SimpleNamespace(max_tokens=max_tokens),
    )
    return cfg


def _make_provider(*responses):
    """Provider whose chat_with_reasoning returns canned (content, reasoning).

    `responses` is a list of (content, reasoning) tuples consumed in order;
    a single tuple is accepted for "always return this".
    """
    if len(responses) == 1 and isinstance(responses[0], tuple):
        responses = [responses[0]]
    else:
        responses = list(responses)
    queue = list(responses)

    async def _chat(*, messages, temperature, max_tokens, response_format):
        if not queue:
            raise AssertionError("provider exhausted: more calls than stubbed responses")
        content, reasoning = queue.pop(0)
        return content, reasoning

    provider = SimpleNamespace(chat_with_reasoning=_chat)
    return provider


# ---------------------------------------------------------------------------
# _parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_plain_json(self):
        data = _parse('{"raw_score": 88, "gaps": ["go"]}')
        assert data["raw_score"] == 88
        assert data["gaps"] == ["go"]

    def test_fenced_json_block(self):
        text = '```json\n{"raw_score": 70}\n```'
        assert _parse(text)["raw_score"] == 70

    def test_fenced_plain_block(self):
        text = '```\n{"raw_score": 70}\n```'
        assert _parse(text)["raw_score"] == 70

    def test_trailing_comma_in_array(self):
        text = '{"gaps": ["a", "b",]}'
        assert _parse(text)["gaps"] == ["a", "b"]

    def test_trailing_comma_in_object(self):
        text = '{"raw_score": 70,}'
        assert _parse(text)["raw_score"] == 70

    def test_empty_string_raises(self):
        with pytest.raises(Exception):
            _parse("")

    def test_none_raises(self):
        with pytest.raises(Exception):
            _parse(None)

    def test_malformed_raises(self):
        with pytest.raises(Exception):
            _parse("not json at all")


# ---------------------------------------------------------------------------
# match_jobs
# ---------------------------------------------------------------------------


class TestMatchJobs:
    @pytest.mark.asyncio
    async def test_empty_jobs_returns_empty(self):
        cfg = _make_config()
        provider = _make_provider(("{}", ""))
        results, skipped = await match_jobs([], cfg, provider)
        assert results == []
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_basic_match_and_reasoning_capture(self):
        cfg = _make_config(match_min_score=0)
        payload = {
            "must_have": ["Python 3年"],
            "matched": [{"requirement": "Python 3年", "evidence": "5年Python"}],
            "gaps": [],
            "strengths": ["FastAPI"],
            "raw_score": 88,
            "confidence": "high",
            "match_reason": "硬性要求全中",
        }
        provider = _make_provider((json.dumps(payload), "thinking-trace"))
        with patch("agent_core.pipeline.match.load_resume", return_value="简历正文"):
            results, skipped = await match_jobs([_make_item()], cfg, provider)

        assert skipped == 0
        assert len(results) == 1
        r = results[0]
        assert r["raw_score"] == 88
        assert r["reasoning"] == "thinking-trace"
        assert r["prompt_version"] == match_mod.PROMPT_VERSION
        assert r["job_id"] == "j1"
        assert r["job_title"] == "Python 后端"
        assert r["company"] == "ACME"

    @pytest.mark.asyncio
    async def test_resume_load_failure_skipped(self):
        """If load_resume raises, the job is dropped (None) and counted as skipped."""
        cfg = _make_config()
        provider = _make_provider(("{}", ""))
        with patch(
            "agent_core.pipeline.match.load_resume",
            side_effect=FileNotFoundError("no resume"),
        ):
            results, skipped = await match_jobs([_make_item()], cfg, provider)
        assert results == []
        assert skipped == 1

    @pytest.mark.asyncio
    async def test_parse_failure_retries_then_succeeds(self):
        """First call returns malformed JSON, retry returns valid JSON."""
        cfg = _make_config(match_min_score=0)
        provider = _make_provider(
            ("not json", ""),  # attempt 0 fails _parse
            ('{"raw_score": 60}', ""),  # attempt 1 succeeds
        )
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, skipped = await match_jobs([_make_item()], cfg, provider)
        assert skipped == 0
        assert len(results) == 1
        assert results[0]["raw_score"] == 60

    @pytest.mark.asyncio
    async def test_parse_failure_after_all_retries_skipped(self):
        cfg = _make_config()
        provider = _make_provider(
            ("not json", ""),
            ("still not json", ""),
        )
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, skipped = await match_jobs([_make_item()], cfg, provider)
        assert results == []
        assert skipped == 1

    @pytest.mark.asyncio
    async def test_min_score_filter(self):
        cfg = _make_config(match_min_score=70)
        items = [
            _make_item(job_id="low", description="j low"),
            _make_item(job_id="high", description="j high"),
        ]

        async def _routed_chat(*, messages, temperature, max_tokens, response_format):
            # Route responses by job content instead of call order: the two
            # matching tasks run concurrently (Semaphore(5)) and whichever
            # reaches the provider first is event-loop dependent — the old
            # order-based queue made this test flaky / order-sensitive.
            content = messages[-1]["content"] if messages else ""
            if "j low" in content:
                return '{"raw_score": 40}', ""
            if "j high" in content:
                return '{"raw_score": 90}', ""
            raise AssertionError(f"unexpected prompt: {content[:80]}")

        provider = SimpleNamespace(chat_with_reasoning=_routed_chat)
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, skipped = await match_jobs(items, cfg, provider)
        assert skipped == 0  # filter is not "skipped" (skipped = errors only)
        assert len(results) == 1
        assert results[0]["job_id"] == "high"

    @pytest.mark.asyncio
    async def test_resume_cache_keyed_by_direction(self):
        """Resumes must load once per (resume_file, direction) pair.

        Regression: the cache used to be keyed on resume_file alone, and the
        orchestrator passes an empty resume_file, so every direction in a
        multi-direction pipeline shared the first direction's resume.
        """
        cfg = _make_config(match_min_score=0)
        # Same resume_file on purpose: only the direction differs.
        items = [
            _make_item(job_id="a", direction="dirA"),
            _make_item(job_id="b", direction="dirB"),
        ]
        loaded: list[str] = []

        def fake_load(cfg, direction):
            loaded.append(direction)
            return f"简历-{direction}"

        async def _chat(*, messages, temperature, max_tokens, response_format):
            return '{"raw_score": 60}', ""

        provider = SimpleNamespace(chat_with_reasoning=_chat)
        with patch("agent_core.pipeline.match.load_resume", side_effect=fake_load):
            results, skipped = await match_jobs(items, cfg, provider)
        assert loaded == ["dirA", "dirB"], f"expected one load per direction, got {loaded}"
        assert len(results) == 2
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_results_sorted_desc_by_score(self):
        cfg = _make_config(match_min_score=0)
        items = [_make_item(job_id=f"j{i}") for i in range(3)]
        provider = _make_provider(
            ('{"raw_score": 55}', ""),
            ('{"raw_score": 95}', ""),
            ('{"raw_score": 75}', ""),
        )
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, _ = await match_jobs(items, cfg, provider)
        scores = [r["raw_score"] for r in results]
        assert scores == [95, 75, 55]

    @pytest.mark.asyncio
    async def test_legacy_score_field_honored(self):
        """Older prompts returning 'score' instead of 'raw_score' still work."""
        cfg = _make_config(match_min_score=60)
        provider = _make_provider(('{"score": 80}', ""))
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, skipped = await match_jobs([_make_item()], cfg, provider)
        assert skipped == 0
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_jd_truncation_note_injected(self):
        """JD over JD_MAX_CHARS triggers truncation_note in the prompt."""
        cfg = _make_config(match_min_score=0)
        long_jd = "X" * (match_mod.JD_MAX_CHARS + 500)
        captured = {}

        async def _chat(*, messages, temperature, max_tokens, response_format):
            captured["prompt"] = messages[0]["content"]
            return '{"raw_score": 50}', ""

        provider = SimpleNamespace(chat_with_reasoning=_chat)
        item = _make_item(description=long_jd)
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            await match_jobs([item], cfg, provider)

        assert "本 JD 已截断" in captured["prompt"]
        # The description actually sent must be truncated, not the full one
        assert captured["prompt"].count("X") < len(long_jd)

    @pytest.mark.asyncio
    async def test_no_truncation_note_for_short_jd(self):
        cfg = _make_config(match_min_score=0)
        captured = {}

        async def _chat(*, messages, temperature, max_tokens, response_format):
            captured["prompt"] = messages[0]["content"]
            return '{"raw_score": 50}', ""

        provider = SimpleNamespace(chat_with_reasoning=_chat)
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            await match_jobs([_make_item(description="短JD")], cfg, provider)
        assert (
            match_mod.MATCH_PROMPT.split("{truncation_note}")[1].strip() not in captured["prompt"]
            or "本 JD 已截断" not in captured["prompt"]
        )
        # The injected note ("本 JD 已截断至前 3000 字符") must NOT appear
        # for a short JD (the template's literal "JD 截断" wording in step 1
        # is always present, so we check the runtime-injected marker instead).
        assert "本 JD 已截断" not in captured["prompt"]

    @pytest.mark.asyncio
    async def test_resume_cached_per_file(self):
        """load_resume is called once per unique resume_file, not once per job."""
        cfg = _make_config(match_min_score=0)
        items = [
            _make_item(job_id="a", resume_file="r1.md"),
            _make_item(job_id="b", resume_file="r1.md"),
            _make_item(job_id="c", resume_file="r2.md"),
        ]
        provider = _make_provider(
            ('{"raw_score": 50}', ""),
            ('{"raw_score": 50}', ""),
            ('{"raw_score": 50}', ""),
        )
        with patch("agent_core.pipeline.match.load_resume", return_value="简历") as mock_load:
            await match_jobs(items, cfg, provider)
        # Two unique resume_files → two loads.
        assert mock_load.call_count == 2

    @pytest.mark.asyncio
    async def test_response_format_json_on_first_attempt(self):
        """Attempt 0 should request json_object; attempt 1 should pass None."""
        cfg = _make_config(match_min_score=0)
        seen_formats = []

        async def _chat(*, messages, temperature, max_tokens, response_format):
            seen_formats.append(response_format)
            return "not json", ""  # force retry

        provider = SimpleNamespace(chat_with_reasoning=_chat)
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            await match_jobs([_make_item()], cfg, provider)
        assert seen_formats[0] == {"type": "json_object"}
        assert seen_formats[1] is None

    @pytest.mark.asyncio
    async def test_concurrency_does_not_lose_results(self):
        """Many jobs run under the semaphore; all results come back."""
        cfg = _make_config(match_min_score=0)
        n = 12  # > CONCURRENCY (5) to exercise queueing
        items = [_make_item(job_id=f"j{i}") for i in range(n)]
        provider = _make_provider(*[('{"raw_score": 50}', "") for _ in range(n)])
        with patch("agent_core.pipeline.match.load_resume", return_value="简历"):
            results, skipped = await match_jobs(items, cfg, provider)
        assert len(results) == n
        assert skipped == 0


# ---------------------------------------------------------------------------
# Persistence: _save_match_to_db
# ---------------------------------------------------------------------------


class TestSaveMatchToDb:
    """Regression: the v2 prompt emits `gaps`, but the DB column is
    `missing_skills`. _save_match_to_db must map one to the other or the
    dashboard's "未命中技能" column renders empty for every v2 result."""

    def test_gaps_persisted_as_missing_skills(self, tmp_path):
        import sqlite3

        from agent_core.pipeline.orchestrator import _save_match_to_db

        db = tmp_path / "m.db"
        # Minimal schema mirroring the v2 migration (db.py _migrate_v5).
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE match_results (
              job_id TEXT PRIMARY KEY,
              match_score INTEGER NOT NULL DEFAULT 0,
              match_reason TEXT DEFAULT '',
              missing_skills TEXT DEFAULT '[]',
              strengths TEXT DEFAULT '[]',
              job_title TEXT DEFAULT '',
              company TEXT DEFAULT '',
              direction TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              reasoning TEXT,
              prompt_version TEXT
            );
            CREATE TABLE IF NOT EXISTS pipeline_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              stage TEXT NOT NULL,
              job_count INTEGER DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        matched = [
            {
                "job_id": "j1",
                "job_title": "P",
                "company": "C",
                "direction": "d",
                "raw_score": 88,
                "match_reason": "ok",
                "gaps": ["Go", "K8s"],  # v2 field
                "strengths": ["Python"],
                "reasoning": "cot-trace",
                "prompt_version": "v2",
            }
        ]
        _save_match_to_db(matched, db_path=str(db))

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT match_score, missing_skills, reasoning, prompt_version "
            "FROM match_results WHERE job_id = ?",
            ("j1",),
        ).fetchone()
        conn.close()

        assert row["match_score"] == 88
        assert json.loads(row["missing_skills"]) == ["Go", "K8s"]
        assert row["reasoning"] == "cot-trace"
        assert row["prompt_version"] == "v2"

    def test_legacy_missing_skills_still_persisted(self, tmp_path):
        """Older prompts emitting `missing_skills` (no `gaps`) still work."""
        import sqlite3

        from agent_core.pipeline.orchestrator import _save_match_to_db

        db = tmp_path / "m.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE match_results (
              job_id TEXT PRIMARY KEY, match_score INTEGER DEFAULT 0,
              match_reason TEXT DEFAULT '', missing_skills TEXT DEFAULT '[]',
              strengths TEXT DEFAULT '[]', job_title TEXT DEFAULT '',
              company TEXT DEFAULT '', direction TEXT DEFAULT '',
              created_at TEXT NOT NULL, reasoning TEXT, prompt_version TEXT
            );
            CREATE TABLE IF NOT EXISTS pipeline_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT NOT NULL,
              job_count INTEGER DEFAULT 0, created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        matched = [
            {
                "job_id": "j2",
                "job_title": "P",
                "company": "C",
                "direction": "d",
                "score": 70,
                "missing_skills": ["Java"],
                "strengths": [],
                "reasoning": "",
                "prompt_version": "v1",
            }
        ]
        _save_match_to_db(matched, db_path=str(db))

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT match_score, missing_skills FROM match_results WHERE job_id=?",
            ("j2",),
        ).fetchone()
        conn.close()
        assert row["match_score"] == 70
        assert json.loads(row["missing_skills"]) == ["Java"]
