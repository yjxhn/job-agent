"""Extra unit tests for pipeline orchestrator helpers and run_pipeline branches.

All network/LLM/dashboard/DB side effects are mocked or redirected to
temporary SQLite files.  No real production database is touched.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent_core.pipeline import orchestrator as orch
from agent_core.pipeline.orchestrator import (
    _ask_continue,
    _compare_jobs,
    _is_production_db,
    _is_test_environment,
    _open_dashboard,
    _save_jobs_to_db,
    _save_match_to_db,
    _save_pipeline_run,
    _save_search_statuses,
    _show_job_summary,
    run_pipeline,
)

# ---------------------------------------------------------------------------
# small doubles
# ---------------------------------------------------------------------------


class _FakeMatching:
    def __init__(self):
        self.enrich_in_pipeline = False
        self.enrich_top_n = None
        self.match_flagged_only = False


class _FakeConfig:
    def __init__(self):
        self.matching = _FakeMatching()


def _job(**kw):
    defaults = dict(
        id="j1",
        title="设备工程师",
        company="某公司",
        company_normalized="某公司",
        location="苏州",
        salary_min=10000,
        salary_max=15000,
        description="岗位描述",
        platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"},
        direction="",
        security_id="",
        lid="",
        published_at="",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class _FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.rowcount = 1
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, flag_rows=None, desc_rows=None):
        self.flag_rows = flag_rows or []
        self.desc_rows = desc_rows or []
        self.closed = False
        self.committed = False

    def execute(self, sql, params=()):
        if "user_flag = 'interested'" in sql:
            return _FakeCursor(self.flag_rows)
        if "description FROM jobs" in sql:
            return _FakeCursor(self.desc_rows)
        return _FakeCursor()

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _patch_pipeline_basics(monkeypatch, jobs=None, filtered=None, matched=None, skipped=0):
    async def fake_search_all(
        config, platform_names=None, directions=None, keywords=None, headless=False, **kw
    ):
        return list(jobs or [])

    async def fake_match_jobs(items, config, llm_provider):
        return list(matched or []), skipped

    monkeypatch.setattr(orch.search, "search_all", fake_search_all)
    monkeypatch.setattr(
        orch.filter_mod,
        "filter_jobs",
        lambda source, config: list(filtered if filtered is not None else source),
    )
    monkeypatch.setattr(orch.match, "match_jobs", fake_match_jobs)
    monkeypatch.setattr(
        "agent_core.notify.windows_toast.notify_search_complete", lambda *a, **k: None
    )


def _patch_get_db(monkeypatch, flag_rows=None, desc_rows=None):
    conn = _FakeConn(flag_rows=flag_rows, desc_rows=desc_rows)
    monkeypatch.setattr(
        "agent_core.storage.db.get_db",
        lambda *a, **k: _FakeConn(flag_rows=flag_rows, desc_rows=desc_rows),
    )
    return conn


def _open_db(tmp_path, name="test.db"):
    from agent_core.storage.db import get_db, migrate

    path = str(tmp_path / name)
    conn = get_db(path)
    migrate(conn)
    conn.close()
    return path


# ---------------------------------------------------------------------------
# environment / dashboard guards
# ---------------------------------------------------------------------------


def test_is_test_environment_agent_testing_flag(monkeypatch):
    monkeypatch.setenv("AGENT_TESTING", "1")
    assert _is_test_environment() is True


def test_is_production_db_handles_realpath_error(monkeypatch):
    def boom(_path):
        raise ValueError("bad path")

    monkeypatch.setattr(orch.os.path, "realpath", boom)
    assert _is_production_db("whatever") is False


def test_open_dashboard_already_running_does_not_open_browser(monkeypatch):
    monkeypatch.setattr("agent_core.server.serve._ensure_dashboard", lambda: True)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    _open_dashboard()
    assert opened == []


def test_open_dashboard_starts_browser(monkeypatch):
    monkeypatch.setattr("agent_core.server.serve._ensure_dashboard", lambda: False)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    _open_dashboard()
    assert opened == [orch.DASHBOARD_URL]


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------


def test_save_jobs_to_db_guard_skips_production_db(monkeypatch):
    guarded = []
    monkeypatch.setattr(orch, "_is_test_environment", lambda: True)
    monkeypatch.setattr(orch, "_is_production_db", lambda path: True)
    monkeypatch.setattr(orch, "_guard_skip", lambda what: guarded.append(what))

    assert _save_jobs_to_db([_job()]) == 0
    assert guarded and "_save_jobs_to_db" in guarded[0]


def test_save_jobs_to_db_platforms_and_urls_variants(tmp_path):
    db_path = _open_db(tmp_path, "variants.db")
    jobs = [
        _job(id="str", platforms="boss_zhipin", urls="http://str"),
        _job(id="set", platforms={"a", "b"}, urls=None),
        _job(id="other", platforms=123, urls={"x": "y"}),
    ]

    assert _save_jobs_to_db(jobs, db_path=db_path) == 3

    from agent_core.storage.db import get_db

    conn = get_db(db_path)
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM jobs").fetchall()}
    conn.close()

    assert rows["str"]["platforms"] == "boss_zhipin"
    assert rows["str"]["urls"] == "http://str"
    assert "a" in rows["set"]["platforms"]
    assert "b" in rows["set"]["platforms"]
    assert rows["set"]["urls"] == "{}"
    assert rows["other"]["platforms"] == "[]"
    assert "x" in rows["other"]["urls"]


def test_save_jobs_to_db_prefers_richer_new_description(tmp_path):
    db_path = _open_db(tmp_path, "richer.db")
    _save_jobs_to_db(
        [_job(id="upd", description="旧描述", security_id="", lid="")], db_path=db_path
    )
    _save_jobs_to_db(
        [
            _job(
                id="upd",
                description="JD: 完整岗位职责\n任职要求：本科",
                security_id="sec-1",
                lid="lid-1",
            )
        ],
        db_path=db_path,
    )

    from agent_core.storage.db import get_db

    conn = get_db(db_path)
    row = conn.execute("SELECT description, security_id, lid FROM jobs WHERE id='upd'").fetchone()
    conn.close()

    assert "JD: 完整岗位职责" in row["description"]
    assert row["security_id"] == "sec-1"
    assert row["lid"] == "lid-1"


def test_save_jobs_to_db_continues_after_per_job_error(tmp_path):
    db_path = _open_db(tmp_path, "perjob.db")

    class _BadPlatformJob:
        id = "bad"
        urls = {}

        @property
        def platforms(self):
            raise RuntimeError("bad platforms")

    assert _save_jobs_to_db([_BadPlatformJob(), _job(id="ok")], db_path=db_path) == 1

    from agent_core.storage.db import get_db

    conn = get_db(db_path)
    ids = [r["id"] for r in conn.execute("SELECT id FROM jobs").fetchall()]
    conn.close()
    assert ids == ["ok"]


def test_save_jobs_to_db_outer_error_returns_zero(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("agent_core.storage.db.get_db", boom)
    assert _save_jobs_to_db([_job()], db_path="tmp.db") == 0


def test_save_match_to_db_guard_skips_production_db(monkeypatch):
    guarded = []
    monkeypatch.setattr(orch, "_is_test_environment", lambda: True)
    monkeypatch.setattr(orch, "_is_production_db", lambda path: True)
    monkeypatch.setattr(orch, "_guard_skip", lambda what: guarded.append(what))

    _save_match_to_db([{"job_id": "x"}])
    assert guarded and "_save_match_to_db" in guarded[0]


def test_save_match_to_db_outer_error_is_swallowed(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("agent_core.storage.db.get_db", boom)
    _save_match_to_db([{"job_id": "x"}], db_path="tmp.db")  # must not raise


def test_save_pipeline_run_guard_skips_production_db(monkeypatch):
    guarded = []
    monkeypatch.setattr(orch, "_is_test_environment", lambda: True)
    monkeypatch.setattr(orch, "_is_production_db", lambda path: True)
    monkeypatch.setattr(orch, "_guard_skip", lambda what: guarded.append(what))

    _save_pipeline_run("search", 3)
    assert guarded and "_save_pipeline_run" in guarded[0]


def test_save_pipeline_run_outer_error_is_swallowed(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("agent_core.storage.db.get_db", boom)
    _save_pipeline_run("search", 3, db_path="tmp.db")  # must not raise


def test_save_search_statuses_empty_does_not_open_db(monkeypatch):
    called = []

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("should not be called")

    monkeypatch.setattr("agent_core.storage.db.get_db", boom)
    _save_search_statuses([], db_path="tmp.db")
    assert called == []


def test_save_search_statuses_outer_error_is_swallowed(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("agent_core.storage.db.get_db", boom)
    _save_search_statuses([{"platform": "boss"}], db_path="tmp.db")  # must not raise


# ---------------------------------------------------------------------------
# console / interactive helpers
# ---------------------------------------------------------------------------


def test_show_job_summary_empty(capsys):
    _show_job_summary([], "🔍 测试")
    out = capsys.readouterr().out
    assert "0 个岗位" in out
    assert "(无)" in out


def test_show_job_summary_prints_salary_branches_and_more(capsys):
    jobs = [
        _job(id="1", salary_min=10000, salary_max=15000, direction="equipment_amr"),
        _job(id="2", salary_min=None, salary_max=20000),
        _job(id="3", salary_min=12000, salary_max=None),
        _job(id="4", salary_min=None, salary_max=None),
        _job(id="5", salary_min=None, salary_max=0),
    ]
    _show_job_summary(jobs, "🔍 测试", max_show=4)
    out = capsys.readouterr().out
    assert "15K" in out
    assert "20K" in out
    assert "12K+" in out
    assert "面议" in out
    assert "[equipment_amr]" in out
    assert "还有 1 个岗位" in out


def test_ask_continue_quit(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "q")
    assert _ask_continue("搜索", 0) is False
    assert "0 个岗位" in capsys.readouterr().out


def test_ask_continue_skip(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "s")
    assert _ask_continue("搜索", 1) == "skip"


def test_ask_continue_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: " \n ")
    assert _ask_continue("搜索", 1) is True


def test_ask_continue_eof(monkeypatch):
    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert _ask_continue("搜索", 1) is False


def test_ask_continue_keyboard_interrupt(monkeypatch):
    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert _ask_continue("搜索", 1) is False


# ---------------------------------------------------------------------------
# _compare_jobs
# ---------------------------------------------------------------------------


def test_compare_jobs_builds_summaries_and_returns_stripped(monkeypatch):
    async def fake_call_llm(*_a, **_k):
        return "  summary  "

    monkeypatch.setattr("agent_core.llm.providers.call_llm_with_retry", fake_call_llm)

    matched = [
        {
            "job_id": "1",
            "raw_score": 85,
            "score": 80,
            "gaps": [{"gap": "A", "severity": "high"}, {"gap": "B"}],
            "missing_skills": ["old"],
            "strengths": ["s1"],
            "match_reason": "理由1",
            "job_title": "岗位A",
            "company": "公司A",
        },
        {
            "job_id": "2",
            "score": 70,
            "gaps": ["C"],
            "match_reason": "理由2",
            "job_title": "岗位B",
            "company": "公司B",
        },
    ]

    result = asyncio.run(_compare_jobs(matched, None, "fake-provider"))

    assert result == "summary"


def test_compare_jobs_failure_returns_empty(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("llm down")

    monkeypatch.setattr("agent_core.llm.providers.call_llm_with_retry", boom)
    result = asyncio.run(_compare_jobs([{"job_id": "1"}], None, "fake-provider"))
    assert result == ""


# ---------------------------------------------------------------------------
# run_pipeline: empty/default/partial/interactive paths
# ---------------------------------------------------------------------------


def test_run_pipeline_default_stages_empty_search(monkeypatch):
    _patch_pipeline_basics(monkeypatch, jobs=[])
    data = asyncio.run(run_pipeline(_FakeConfig(), None, interactive=False))

    assert data["jobs"] == []
    assert data["filtered"] == []
    assert data["matched"] == []


def test_run_pipeline_stages_without_search_or_filter(monkeypatch):
    async def no_search(*_a, **_k):
        raise AssertionError("search should not run")

    def no_filter(*_a, **_k):
        raise AssertionError("filter should not run")

    async def no_match(*_a, **_k):
        raise AssertionError("match should not run")

    monkeypatch.setattr(orch.search, "search_all", no_search)
    monkeypatch.setattr(orch.filter_mod, "filter_jobs", no_filter)
    monkeypatch.setattr(orch.match, "match_jobs", no_match)
    monkeypatch.setattr(
        "agent_core.notify.windows_toast.notify_search_complete", lambda *a, **k: None
    )

    data = asyncio.run(run_pipeline(_FakeConfig(), None, stages=["match"], interactive=False))

    assert data["jobs"] == []
    assert data["matched"] == []


def test_run_pipeline_interactive_quit_search(monkeypatch, capsys):
    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs)
    monkeypatch.setattr("builtins.input", lambda: "q")
    monkeypatch.setattr(orch, "_open_dashboard", lambda: None)

    data = asyncio.run(
        run_pipeline(_FakeConfig(), None, stages=["search", "filter", "match"], interactive=True)
    )

    assert data["jobs"] == jobs
    assert data["filtered"] == []
    assert "Dashboard" in capsys.readouterr().out


def test_run_pipeline_interactive_skip_search(monkeypatch):
    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs)
    monkeypatch.setattr("builtins.input", lambda: "s")
    monkeypatch.setattr(orch, "_open_dashboard", lambda: None)

    data = asyncio.run(
        run_pipeline(_FakeConfig(), None, stages=["search", "filter", "match"], interactive=True)
    )

    assert data["jobs"] == jobs
    assert data["filtered"] == []


def test_run_pipeline_interactive_quit_filter(monkeypatch):
    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=[])
    answers = iter(["", "q"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    monkeypatch.setattr(orch, "_open_dashboard", lambda: None)

    data = asyncio.run(
        run_pipeline(_FakeConfig(), None, stages=["search", "filter", "match"], interactive=True)
    )

    assert data["jobs"] == jobs
    assert data["filtered"] == []
    assert data["matched"] == []


def test_run_pipeline_interactive_skip_filter(monkeypatch):
    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=[])
    answers = iter(["", "s"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    monkeypatch.setattr(orch, "_open_dashboard", lambda: None)

    data = asyncio.run(
        run_pipeline(_FakeConfig(), None, stages=["search", "filter", "match"], interactive=True)
    )

    assert data["jobs"] == jobs
    assert data["filtered"] == []
    assert data["matched"] == []


# ---------------------------------------------------------------------------
# run_pipeline: enrichment branches
# ---------------------------------------------------------------------------


def test_run_pipeline_enrich_flagged_only_filters_to_flagged(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.match_flagged_only = True
    cfg.matching.enrich_top_n = None

    jobs = [_job(id="1"), _job(id="2")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[("1",)], desc_rows=[])

    enriched = []

    async def fake_enrich(job, config):
        enriched.append(job.id)

    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)

    data = asyncio.run(
        run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False)
    )

    assert enriched == ["1"]
    assert data["enriched"] == 1


def test_run_pipeline_enrich_flagged_only_no_candidates(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.match_flagged_only = True
    cfg.matching.enrich_top_n = None

    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[("other",)], desc_rows=[])

    enriched = []

    async def fake_enrich(job, config):
        enriched.append(job.id)

    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)

    data = asyncio.run(
        run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False)
    )

    assert enriched == []
    assert data["enriched"] == 0


def test_run_pipeline_enrich_skips_already_enriched_jobs(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.match_flagged_only = False
    cfg.matching.enrich_top_n = None

    long_desc = "JD:" + "详细岗位职责" * 60
    jobs = [_job(id="1", description=long_desc)]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[], desc_rows=[])

    enriched = []

    async def fake_enrich(job, config):
        enriched.append(job.id)

    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)

    data = asyncio.run(
        run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False)
    )

    assert enriched == []
    assert data["enriched"] == 1


def test_run_pipeline_enrich_reloads_db_description(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.match_flagged_only = True
    cfg.matching.enrich_top_n = None

    jobs = [_job(id="1", description="short")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[("1",)], desc_rows=[("1", "JD: 数据库里的完整岗位职责")])

    seen = []

    async def fake_enrich(job, config):
        seen.append(job.description)

    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)

    asyncio.run(run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False))

    assert seen == ["JD: 数据库里的完整岗位职责"]


# ---------------------------------------------------------------------------
# run_pipeline: match branches
# ---------------------------------------------------------------------------


def test_run_pipeline_match_flagged_only_filters_to_flagged(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.match_flagged_only = True

    jobs = [_job(id="1"), _job(id="2")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[("1",)], desc_rows=[])

    matched_items = []

    async def fake_match_jobs(items, config, llm_provider):
        matched_items.extend(i.job.id for i in items)
        return [], 0

    monkeypatch.setattr(orch.match, "match_jobs", fake_match_jobs)

    asyncio.run(run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False))

    assert matched_items == ["1"]


def test_run_pipeline_match_flagged_only_no_flagged_jobs(monkeypatch):
    cfg = _FakeConfig()
    cfg.matching.match_flagged_only = True

    jobs = [_job(id="1")]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=[])
    _patch_get_db(monkeypatch, flag_rows=[], desc_rows=[])

    match_called = []

    async def fake_match_jobs(items, config, llm_provider):
        match_called.append(items)
        return [], 0

    monkeypatch.setattr(orch.match, "match_jobs", fake_match_jobs)

    data = asyncio.run(
        run_pipeline(cfg, None, stages=["search", "filter", "match"], interactive=False)
    )

    # The current implementation logs "no flagged jobs" but still runs matching
    # on the unfiltered candidate list when there are no flagged ids.
    assert len(match_called) == 1
    assert match_called[0][0].job.id == "1"
    assert data["matched"] == []
    assert data["skipped"] == 0


def test_run_pipeline_cross_job_comparison_success(monkeypatch):
    cfg = _FakeConfig()
    jobs = [_job(id="1"), _job(id="2")]
    matched = [
        {"job_id": "1", "raw_score": 80, "job_title": "A", "company": "C1"},
        {"job_id": "2", "raw_score": 70, "job_title": "B", "company": "C2"},
    ]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=matched)
    monkeypatch.setattr(orch, "_compare_jobs", AsyncMock(return_value="推荐结果"))

    data = asyncio.run(
        run_pipeline(cfg, object(), stages=["search", "filter", "match"], interactive=False)
    )

    assert data["comparison"] == "推荐结果"


def test_run_pipeline_cross_job_comparison_error_is_swallowed(monkeypatch):
    cfg = _FakeConfig()
    jobs = [_job(id="1"), _job(id="2")]
    matched = [
        {"job_id": "1", "raw_score": 80, "job_title": "A", "company": "C1"},
        {"job_id": "2", "raw_score": 70, "job_title": "B", "company": "C2"},
    ]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=matched)
    monkeypatch.setattr(
        orch, "_compare_jobs", AsyncMock(side_effect=RuntimeError("compare failed"))
    )

    data = asyncio.run(
        run_pipeline(cfg, object(), stages=["search", "filter", "match"], interactive=False)
    )

    assert "comparison" not in data


def test_run_pipeline_match_interactive_prints(monkeypatch, capsys):
    cfg = _FakeConfig()
    jobs = [_job(id="1")]
    matched = [
        {"job_id": str(i), "raw_score": 90, "job_title": f"岗位{i}", "company": "C"}
        for i in range(16)
    ]
    _patch_pipeline_basics(monkeypatch, jobs=jobs, filtered=jobs, matched=matched)
    monkeypatch.setattr(orch, "_compare_jobs", AsyncMock(return_value="cmp"))
    monkeypatch.setattr(orch, "_open_dashboard", lambda: None)
    calls = []
    monkeypatch.setattr("builtins.input", lambda: calls.append(1) or "")

    data = asyncio.run(
        run_pipeline(cfg, object(), stages=["search", "filter", "match"], interactive=True)
    )

    assert data["matched"] == matched
    out = capsys.readouterr().out
    assert "LLM 匹配完成" in out
    assert "横向对比" in out
    assert "还有 1 个" in out


def test_run_pipeline_toast_error_is_swallowed(monkeypatch):
    _patch_pipeline_basics(monkeypatch, jobs=[], matched=[])

    def boom(*_a, **_k):
        raise RuntimeError("toast failed")

    monkeypatch.setattr("agent_core.notify.windows_toast.notify_search_complete", boom)

    data = asyncio.run(run_pipeline(_FakeConfig(), None, interactive=False))

    assert data["jobs"] == []
