"""Pytest tests for core pipeline + scheduler logic.

Deterministic — no network, no real LLM. Covers the modules touched by the
F2/F3/F4/F5/F7/F8/F9 fixes: match (parse/retry/concurrency/min-score),
filter, search dedup, scheduler (corrupt recovery + PID lock).
"""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from agent_core.config import load_config
from agent_core.pipeline import filter as filter_mod
from agent_core.pipeline import match
from agent_core.pipeline.search import _dedup, _normalize_company
from agent_core.platforms.base import Job
from agent_core.scheduler import scheduler as S

# ---------- fixtures ----------


@pytest.fixture
def cfg():
    return load_config("config.yaml")


def _now():
    return datetime.now(UTC)


def _job(**kw):
    defaults = dict(
        id="x",
        title="t",
        company="c",
        company_normalized="c",
        description="",
        platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"},
        first_seen=_now(),
        last_seen=_now(),
    )
    defaults.update(kw)
    return Job(**defaults)


class FakeProvider:
    """Mock LLM provider returning scripted responses (str) or raising Exceptions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self.responses) - 1)
        r = self.responses[idx]
        if isinstance(r, Exception):
            raise r
        return r

    async def chat_with_reasoning(
        self, messages, temperature=0.7, max_tokens=4096, response_format=None
    ):
        """Mock variant of chat_with_reasoning. Returns (content, "") —
        reasoning_content is empty in tests because thinking mode isn't
        exercised against a real API here."""
        content = await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return content, ""


# ---------- F2: match._parse ----------


def test_parse_plain_json():
    assert match._parse('{"score": 88}') == {"score": 88}


def test_parse_markdown_fenced_json():
    assert match._parse('```json\n{"score": 70}\n```') == {"score": 70}


def test_parse_markcode_fenced_bare():
    assert match._parse('```\n{"score": 70}\n```') == {"score": 70}


def test_parse_strips_trailing_comma():
    parsed = match._parse('{"score": 70, "missing": ["a",]}')
    assert parsed["score"] == 70
    assert parsed["missing"] == ["a"]


def test_parse_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        match._parse("not json at all")


def test_parse_empty_raises():
    with pytest.raises(json.JSONDecodeError):
        match._parse("")


# ---------- F2/F4/F7: match.match_jobs ----------


class _PipelineItem:
    """Lightweight stand-in for the pipeline item match_jobs consumes.

    match_jobs reads item.job / item.resume_file / item.direction. The real
    pipeline wraps Job in a PipelineItem; tests use this stub to avoid the
    extra import. Job is a frozen-ish pydantic model so we cannot attach
    resume_file to it directly — keep it on the wrapper instead.
    """

    def __init__(self, job, direction="equipment_amr", resume_file="resumes/equipment_amr.txt"):
        self.job = job
        self.direction = direction
        self.resume_file = resume_file


def _match_job(job, direction="equipment_amr"):
    """Backward-compat helper: returns a _PipelineItem wrapping the job."""
    job.direction = direction
    return _PipelineItem(job, direction=direction)


# Some legacy tests call _ps_item directly — alias to _PipelineItem for compat.
_ps_item = _PipelineItem


def test_match_jobs_returns_tuple_and_filters_min_score(cfg):
    # Arrange: two jobs, one below min_score (50), one above
    provider = FakeProvider(
        [
            '{"raw_score": 30, "match_reason": "low", "missing_skills": [], "strengths": []}',
            '{"raw_score": 80, "match_reason": "good", "missing_skills": [], "strengths": []}',
        ]
    )
    ps = [
        _match_job(_job(id="1", title="AMR 低分", description="AMR AGV 调度")),
        _match_job(_job(id="2", title="AMR 高分", description="AMR AGV 调度")),
    ]

    # Act
    results, skipped = asyncio.run(match.match_jobs(ps, cfg, provider))

    # Assert: 30 filtered by min_score, 80 kept; 0 skipped (no errors)
    assert skipped == 0
    assert len(results) == 1
    assert results[0]["raw_score"] == 80
    # Reasoning field should be present (empty string from FakeProvider)
    assert "reasoning" in results[0]
    assert "prompt_version" in results[0]


def test_match_jobs_retries_on_bad_json(cfg):
    # Arrange: first response bad JSON, second good → retry succeeds
    provider = FakeProvider(
        [
            "not valid json",
            '{"raw_score": 75, "match_reason": "ok", "missing_skills": [], "strengths": []}',
        ]
    )
    ps = [_match_job(_job(id="1", title="AMR", description="AMR AGV 调度"))]

    # Act
    results, skipped = asyncio.run(match.match_jobs(ps, cfg, provider))

    # Assert: retried once, succeeded, not skipped
    assert provider.calls == 2
    assert skipped == 0
    assert len(results) == 1
    assert results[0]["raw_score"] == 75


def test_match_jobs_skipped_when_all_attempts_fail(cfg):
    # Arrange: both attempts return unparseable
    provider = FakeProvider(["bad", "still bad"])
    ps = [_ps_item(_job(id="1", title="AMR", description="AMR AGV 调度"))]

    # Act
    results, skipped = asyncio.run(match.match_jobs(ps, cfg, provider))

    # Assert: job skipped (not silently dropped), surfaced in return value
    assert provider.calls == match.MAX_ATTEMPTS
    assert skipped == 1
    assert results == []


def test_match_jobs_empty_input_returns_empty(cfg):
    provider = FakeProvider([])
    results, skipped = asyncio.run(match.match_jobs([], cfg, provider))
    assert results == []
    assert skipped == 0
    assert provider.calls == 0


def test_match_jobs_sorted_desc_by_score(cfg):
    # Arrange: responses out of order; concurrency may reorder, but result must be sorted
    provider = FakeProvider(
        [
            '{"raw_score": 60, "match_reason": "x", "missing_skills": [], "strengths": []}',
            '{"raw_score": 95, "match_reason": "x", "missing_skills": [], "strengths": []}',
            '{"raw_score": 75, "match_reason": "x", "missing_skills": [], "strengths": []}',
        ]
    )
    ps = [_ps_item(_job(id=str(i), title=f"AMR {i}", description="AMR AGV 调度")) for i in range(3)]

    results, skipped = asyncio.run(match.match_jobs(ps, cfg, provider))

    scores = [r["raw_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert skipped == 0


# ---------- filter ----------


def test_filter_excludes_keywords(cfg):
    jobs = [
        _job(id="1", title="AMR 外包岗位", description="x"),
        _job(id="2", title="AMR 正式岗位", description="y"),
    ]
    out = filter_mod.filter_jobs(jobs, cfg)
    assert len(out) == 1
    assert "外包" not in out[0].title


def test_filter_min_salary(cfg):
    jobs = [_job(id="1", title="AMR", description="x", salary_min=3000, salary_max=4000)]
    assert filter_mod.filter_jobs(jobs, cfg) == []


def test_filter_passes_above_min_salary(cfg):
    jobs = [_job(id="1", title="AMR", description="x", salary_min=10000, salary_max=15000)]
    assert len(filter_mod.filter_jobs(jobs, cfg)) == 1


# ---------- search dedup ----------


def test_normalize_company_alias(cfg):
    assert _normalize_company("宁德时代", cfg.company_aliases) == "catl"
    assert _normalize_company("CATL", cfg.company_aliases) == "catl"


def test_normalize_company_unknown_passes_through(cfg):
    assert _normalize_company("未知小厂", cfg.company_aliases) == "未知小厂"


def test_dedup_merges_same_company_across_platforms(cfg):
    now = _now()
    j1 = _job(
        id="a",
        title="工程师",
        company="宁德时代",
        company_normalized="catl",
        platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"},
        first_seen=now,
        last_seen=now,
    )
    j2 = _job(
        id="b",
        title="工程师",
        company="CATL",
        company_normalized="catl",
        platforms=["liepin"],
        urls={"liepin": "http://y"},
        first_seen=now,
        last_seen=now,
    )
    merged = _dedup([j1, j2], cfg.company_aliases)
    assert len(merged) == 1
    assert set(merged[0].platforms) == {"boss_zhipin", "liepin"}


# ---------- F5/F9: scheduler ----------


def test_scheduler_load_corrupt_resets_and_backs_up(tmp_path, monkeypatch):
    # Arrange: corrupt state file
    state = tmp_path / "state.json"
    monkeypatch.setattr(S, "STATE_FILE", state)
    state.write_text("{not valid json,,,}")

    # Act
    s = S._load()

    # Assert: defaults returned, corrupt file backed up
    assert s["enabled"] is False
    assert (tmp_path / "state.json.corrupt").exists()


def test_scheduler_load_missing_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "nonexistent.json")
    s = S._load()
    assert s["enabled"] is False
    assert s["runs"] == 0


def test_scheduler_lock_acquire_refuse_double_release(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOCK_FILE", tmp_path / "lock")

    # Act/Assert: first acquire OK
    assert S.acquire_lock() is True
    # Second acquire by same live pid must be refused
    assert S.acquire_lock() is False
    # After release, can re-acquire
    S.release_lock()
    assert S.acquire_lock() is True
    S.release_lock()


def test_scheduler_pid_alive_invalid_pid():
    assert S._pid_alive(0) is False
    assert S._pid_alive(-1) is False
    # 999999 is almost certainly not a real process
    assert S._pid_alive(999999) is False


def test_scheduler_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    s = {
        "enabled": True,
        "last_run": "2026-06-19T00:00:00+00:00",
        "runs": 5,
        "directions": ["equipment_amr"],
        "last_error": None,
    }
    S._save(s)
    loaded = S._load()
    assert loaded["enabled"] is True
    assert loaded["runs"] == 5
    assert loaded["directions"] == ["equipment_amr"]


# ---------- tracking (7-stage lifecycle) ----------

from agent_core.storage.db import get_db, migrate  # noqa: E402
from agent_core.tracking.tracker import (  # noqa: E402
    add_application,
    get_application,
    get_timeline,
    list_applications,
    update_status,
)


@pytest.fixture
def db(tmp_path):
    conn = get_db(str(tmp_path / "test.db"))
    migrate(conn)
    yield conn
    conn.close()


def test_add_application_creates_placeholder_for_external(db):
    app_id = add_application(db, job_id="external123", resume_version="v1")
    assert app_id > 0
    app = get_application(db, app_id)
    assert app["status"] == "已投递"
    assert app["job_company"] == "未知公司"  # auto-created placeholder


def test_add_application_dedups_same_job(db):
    first = add_application(db, job_id="dup1")
    second = add_application(db, job_id="dup1")
    assert first == second  # returns existing id, no duplicate
    assert len(list_applications(db)) == 1


def test_update_status_valid_transition_records_timeline(db):
    app_id = add_application(db, job_id="j1")
    updated = update_status(db, app_id, "HR已读")
    assert updated["status"] == "HR已读"
    timeline = get_timeline(db, app_id)
    assert len(timeline) == 1
    assert timeline[0]["from_status"] == "已投递"
    assert timeline[0]["to_status"] == "HR已读"


def test_update_status_invalid_transition_raises(db):
    app_id = add_application(db, job_id="j1")
    # 已投递 -> Offer is not a valid next step
    with pytest.raises(ValueError):
        update_status(db, app_id, "Offer")


def test_update_status_unknown_app_raises(db):
    with pytest.raises(ValueError):
        update_status(db, 99999, "HR已读")


def test_list_applications_filter_by_status(db):
    add_application(db, job_id="j1")
    a2 = add_application(db, job_id="j2")
    update_status(db, a2, "HR已读")
    still_applied = list_applications(db, status_filter="已投递")
    assert len(still_applied) == 1
    assert still_applied[0]["job_id"] == "j1"


# ---------- boss_zhipin HTTP API mapping (F6 rewrite) ----------


def test_boss_parse_salary_ranges():
    from agent_core.platforms.boss_zhipin import _parse_salary

    assert _parse_salary("8-13K") == (8000, 13000)
    assert _parse_salary("15K") == (15000, None)
    assert _parse_salary("") == (None, None)
    assert _parse_salary("面议") == (None, None)


def test_boss_api_item_to_job_maps_all_fields():
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    adapter = BossZhipinAdapter()
    item = {
        "jobName": "AMR工程师",
        "brandName": "某科技",
        "cityName": "苏州",
        "areaDistrict": "高新区",
        "businessDistrict": "科技园",
        "salaryDesc": "8-13K",
        "encryptJobId": "abc123",
        "jobExperience": "经验不限",
        "jobDegree": "大专",
        "skills": ["ROS", "SLAM"],
        "jobLabels": ["经验不限"],
        "welfareList": ["五险一金"],
        "brandIndustry": "机器人",
        "brandScaleName": "100-499人",
    }
    job = asyncio.run(adapter._api_item_to_job(item))

    assert job.title == "AMR工程师"
    assert job.company == "某科技"
    assert job.location == "苏州-高新区-科技园"
    assert job.salary_min == 8000
    assert job.salary_max == 13000
    assert "job_detail/abc123.html" in job.urls["boss_zhipin"]
    # Description should aggregate skills/welfare/industry
    assert "ROS" in job.description and "SLAM" in job.description
    assert "五险一金" in job.description
    assert "机器人" in job.description


def test_boss_api_item_to_job_handles_missing_fields():
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    adapter = BossZhipinAdapter()
    # Minimal item — no salary, no encryptJobId, no optional fields
    job = asyncio.run(adapter._api_item_to_job({"jobName": "X", "brandName": "Y"}))
    assert job.title == "X"
    assert job.company == "Y"
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.urls["boss_zhipin"] == ""  # no encryptJobId → no link


def test_boss_load_cookies_missing_returns_empty(tmp_path):
    from agent_core.platforms.boss_zhipin import _load_cookies

    assert _load_cookies(str(tmp_path / "nope.json")) == []


def test_boss_load_cookies_parses_list(tmp_path):
    from agent_core.platforms.boss_zhipin import _load_cookies

    p = tmp_path / "c.json"
    p.write_text('[{"name":"wt2","value":"abc","domain":".zhipin.com"}]', encoding="utf-8")
    cookies = _load_cookies(str(p))
    assert len(cookies) == 1
    assert cookies[0]["name"] == "wt2"


def test_boss_session_cookie_valid():
    from agent_core.platforms.boss_zhipin import _session_cookie_valid

    valid_pair = [
        {"name": "wt2", "expires": -1},
        {"name": "__zp_stoken__", "expires": 9999999999},
    ]
    # No wt2 → invalid
    assert _session_cookie_valid([{"name": "bst"}]) is False
    # wt2 alone is no longer enough → invalid
    assert _session_cookie_valid([{"name": "wt2", "expires": -1}]) is False
    # wt2 + __zp_stoken__ session cookies → valid
    assert _session_cookie_valid(valid_pair) is True
    # wt2 expired → invalid even with stoken
    assert (
        _session_cookie_valid(
            [{"name": "wt2", "expires": 1}, {"name": "__zp_stoken__", "expires": 9999999999}]
        )
        is False
    )


def test_save_pipeline_run_writes_row(tmp_path):
    from agent_core.pipeline import orchestrator
    from agent_core.storage.db import get_db, migrate

    db_path = str(tmp_path / "pipe.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    orchestrator._save_pipeline_run("search", 3, db_path=db_path)

    conn = get_db(db_path)
    row = conn.execute("SELECT stage, job_count FROM pipeline_runs").fetchone()
    conn.close()
    assert row[0] == "search"
    assert row[1] == 3
