"""Additional CLI coverage for less-tested commands, helpers, and error paths."""

from types import SimpleNamespace

from typer.testing import CliRunner

from agent_core.cli import _fmt_size, _pick_critical_details, app
from agent_core.cookie_health import CookieHealthResult, CookieStatus

runner = CliRunner()


class _FakeDB:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def execute(self, sql, params=()):
        return SimpleNamespace(fetchone=lambda: self.row, fetchall=lambda: self.rows)


def _config(platforms=None):
    llm = SimpleNamespace(api_key_env="TEST_KEY", model="fake")
    schedule = SimpleNamespace(interval_hours=1, quiet_hours=[])
    return SimpleNamespace(
        platforms=platforms or {},
        directions={},
        llm=llm,
        schedule=schedule,
        api_key="x",
    )


def _job_row(job_id="job1"):
    return {
        "id": job_id,
        "title": "工程师",
        "company": "某公司",
        "company_normalized": "某公司",
        "location": "北京",
        "salary_min": 10000,
        "salary_max": 20000,
        "description": "desc",
        "platforms": '["boss_zhipin"]',
        "urls": '{"boss_zhipin":"http://x"}',
        "direction": "equipment_amr",
        "first_seen": "2026-01-01T00:00:00",
        "last_seen": "2026-01-01T00:00:00",
        "is_new": 1,
        "security_id": "",
        "lid": "",
        "published_at": "",
    }


def _fake_setup(monkeypatch, config=None, db=None, provider=None):
    config = config or _config()
    db = db or _FakeDB()
    provider = provider if provider is not None else SimpleNamespace(model="fake")
    import agent_core.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_setup", lambda *a, **k: (config, db, provider))
    monkeypatch.setattr("agent_core.cli.create_provider", lambda *a, **k: provider)
    return config, db, provider


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_cli_login_liepin_mocked(monkeypatch):
    config = _config({"liepin": SimpleNamespace(cookie_path="cookies/liepin.json")})
    _fake_setup(monkeypatch, config=config)
    called = []

    async def fake_login(path):
        called.append(path)

    monkeypatch.setattr("agent_core.platforms.liepin.liepin_login", fake_login)
    result = runner.invoke(app, ["login", "--platform", "liepin"])
    assert result.exit_code == 0
    assert called == ["cookies/liepin.json"]


def test_cli_login_zhilian_alias_and_close_browser(monkeypatch):
    config = _config({"zhilian": SimpleNamespace(cookie_path="cookies/zhilian.json")})
    _fake_setup(monkeypatch, config=config)
    called = []
    closed = []

    async def fake_login(path):
        called.append(path)

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr("agent_core.platforms.zhilian.zhilian_login", fake_login)
    monkeypatch.setattr("agent_core.platforms.zhilian_browser.close_browser", fake_close)
    result = runner.invoke(app, ["login", "--platform", "zl"])
    assert result.exit_code == 0
    assert called == ["cookies/zhilian.json"]
    assert closed == [True]


# ---------------------------------------------------------------------------
# rematch
# ---------------------------------------------------------------------------


def test_cli_rematch_single_job_raw_score_and_save(monkeypatch):
    config = _config()
    db = _FakeDB(row=_job_row())
    _fake_setup(monkeypatch, config=config, db=db)

    async def fake_enrich(job, config):
        return job

    async def fake_match(jobs, config, provider):
        return [
            {
                "raw_score": 88,
                "job_title": "AMR工程师",
                "company": "某公司",
                "match_reason": "Strong match",
                "confidence": "high",
            }
        ], []

    saved = []
    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)
    monkeypatch.setattr("agent_core.pipeline.match.match_jobs", fake_match)
    monkeypatch.setattr("agent_core.pipeline.orchestrator._save_match_to_db", saved.append)

    result = runner.invoke(app, ["rematch", "job1"])
    assert result.exit_code == 0
    assert "88%" in result.stdout
    assert len(saved) == 1 and saved[0][0]["raw_score"] == 88


def test_cli_rematch_all_since_empty_results(monkeypatch):
    config = _config()
    db = _FakeDB(rows=[_job_row()])
    _fake_setup(monkeypatch, config=config, db=db)
    saved = []

    async def fake_match(jobs, config, provider):
        return [], []

    monkeypatch.setattr("agent_core.pipeline.match.match_jobs", fake_match)
    monkeypatch.setattr("agent_core.pipeline.orchestrator._save_match_to_db", saved.append)

    result = runner.invoke(app, ["rematch", "--all-since", "2020-01-01"])
    assert result.exit_code == 0
    assert "Re-matching" in result.stdout
    assert saved == []


# ---------------------------------------------------------------------------
# search / pipeline error and result branches
# ---------------------------------------------------------------------------


def test_cli_search_unknown_platform_exits(monkeypatch):
    _fake_setup(monkeypatch)
    monkeypatch.setattr(
        "agent_core.pipeline.search.resolve_platform_names",
        lambda config, plats: ([], ["mars"]),
    )
    result = runner.invoke(app, ["search", "--keyword", "x", "--platforms", "mars"])
    assert result.exit_code != 0
    assert "未知平台" in result.stdout


def test_cli_search_empty_results_diagnoses_cookies(monkeypatch):
    config = _config({"boss_zhipin": SimpleNamespace()})
    _fake_setup(monkeypatch, config=config)

    async def fake_search_all(*args, **kwargs):
        return []

    async def fake_close():
        pass

    monkeypatch.setattr("agent_core.pipeline.search.search_all", fake_search_all)
    monkeypatch.setattr(
        "agent_core.cookie_health.diagnose_empty_results",
        lambda config: "diagnose-line",
    )
    monkeypatch.setattr("agent_core.platforms.zhilian_browser.close_browser", fake_close)

    result = runner.invoke(app, ["search", "--keyword", "x"])
    assert result.exit_code == 0
    assert "Found 0 jobs" in result.stdout
    assert "diagnose-line" in result.stdout


def test_cli_pipeline_unknown_platform_exits(monkeypatch):
    _fake_setup(monkeypatch)
    monkeypatch.setattr(
        "agent_core.pipeline.search.resolve_platform_names",
        lambda config, plats: ([], ["bad"]),
    )
    result = runner.invoke(app, ["pipeline", "--platforms", "bad"])
    assert result.exit_code != 0
    assert "未知平台" in result.stdout


def test_cli_pipeline_matched_uses_raw_score(monkeypatch):
    _fake_setup(monkeypatch)

    async def fake_run_pipeline(config, provider, stages=None, **kwargs):
        return {
            "matched": [
                {
                    "raw_score": 77,
                    "job_title": "Test Job",
                    "company": "Test Co",
                    "match_reason": "Good match",
                }
            ]
        }

    monkeypatch.setattr("agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)
    result = runner.invoke(app, ["pipeline", "--stages", "search"])
    assert result.exit_code == 0
    assert "Top matches" in result.stdout
    assert "77%" in result.stdout


# ---------------------------------------------------------------------------
# tailor
# ---------------------------------------------------------------------------


def test_cli_tailor_yes_missing_facts(monkeypatch):
    config = _config()
    db = _FakeDB(row=_job_row())
    _fake_setup(monkeypatch, config=config, db=db)

    async def fake_enrich(job, config):
        return job

    async def fake_tailor(job, config, provider):
        return "## 定制简历"

    async def fake_close():
        pass

    saved = []
    monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", fake_enrich)
    monkeypatch.setattr("agent_core.pipeline.tailor.tailor_resume", fake_tailor)
    monkeypatch.setattr("agent_core.config.load_resume", lambda config, direction: "原简历")
    monkeypatch.setattr(
        "agent_core.pipeline.tailor.extract_hard_facts",
        lambda original: [("姓名", "张三")],
    )
    monkeypatch.setattr(
        "agent_core.pipeline.tailor.verify_facts",
        lambda text, facts: [("姓名", "张三")],
    )
    monkeypatch.setattr(
        "agent_core.pipeline.tailor.save_resume",
        lambda text, job: {"md": "/tmp/x.md", "docx": "/tmp/x.docx"},
    )
    monkeypatch.setattr("agent_core.pipeline.tailor.open_job_link", lambda job: None)
    monkeypatch.setattr(
        "agent_core.pipeline.file_catalog.catalog_file",
        lambda *a, **k: saved.append(a),
    )
    monkeypatch.setattr("agent_core.platforms.zhilian_browser.close_browser", fake_close)

    result = runner.invoke(app, ["tailor", "job1", "--yes"])
    assert result.exit_code == 0
    assert "事实校验" in result.stdout
    assert "张三" in result.stdout
    assert "Resume saved" in result.stdout
    assert saved


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def test_cli_serve_stop(monkeypatch):
    called = []
    monkeypatch.setattr("agent_core.server.serve._stop_dashboard", lambda: called.append(True))
    result = runner.invoke(app, ["serve", "--stop"])
    assert result.exit_code == 0
    assert called == [True]


def test_cli_serve_daemon(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        "agent_core.server.serve._ensure_dashboard",
        lambda port: calls.update(port=port),
    )
    result = runner.invoke(app, ["serve", "--daemon", "--port", "9001"])
    assert result.exit_code == 0
    assert calls["port"] == 9001
    assert "后台进程已启动" in result.stdout


# ---------------------------------------------------------------------------
# track
# ---------------------------------------------------------------------------


def test_cli_track_add_external_url(monkeypatch):
    _fake_setup(monkeypatch)
    calls = {}

    def fake_ctl(db):
        pass

    def fake_add(db, jid):
        calls["jid"] = jid
        return 7

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr("agent_core.tracking.tracker.add_application", fake_add)
    result = runner.invoke(app, ["track", "add", "https://example.com/job/123"])
    assert result.exit_code == 0
    assert "Application #7 recorded" in result.stdout
    assert len(calls["jid"]) == 16


def test_cli_track_list_filtered_empty(monkeypatch):
    _fake_setup(monkeypatch)
    seen = {}

    def fake_ctl(db):
        pass

    def fake_list(db, status_filter=None):
        seen["filter"] = status_filter
        return []

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr("agent_core.tracking.tracker.list_applications", fake_list)
    result = runner.invoke(app, ["track", "list", "--status", "Offer"])
    assert result.exit_code == 0
    assert seen["filter"] == "Offer"
    assert "filtered by 'Offer'" in result.stdout


# ---------------------------------------------------------------------------
# interview prep / mock interview
# ---------------------------------------------------------------------------


def test_cli_interview_prep_cached(monkeypatch):
    config = _config()
    db = _FakeDB(row=_job_row())
    _fake_setup(monkeypatch, config=config, db=db)

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.load_interview_prep_json",
        lambda job_id, db: {"rounds": [{"questions": [{"q": "1"}, {"q": "2"}]}]},
    )
    result = runner.invoke(app, ["interview-prep", "job1"])
    assert result.exit_code == 0
    assert "Using cached prep" in result.stdout
    assert "2 questions" in result.stdout


def test_cli_mock_interview_passes_options(monkeypatch):
    config = _config()
    db = _FakeDB(row=_job_row())
    _fake_setup(monkeypatch, config=config, db=db)
    seen = {}

    def fake_mi(job, config, provider, from_prep=False, focus=None, difficulty=None):
        seen.update(from_prep=from_prep, focus=focus, difficulty=difficulty)

    monkeypatch.setattr("agent_core.pipeline.interview_prep.mock_interview", fake_mi)
    result = runner.invoke(
        app,
        ["mock-interview", "job1", "--from-prep", "--focus", "技术", "--difficulty", "hard"],
    )
    assert result.exit_code == 0
    assert seen == {"from_prep": True, "focus": "技术", "difficulty": "hard"}


# ---------------------------------------------------------------------------
# offer eval / salary advice edge branches
# ---------------------------------------------------------------------------


def test_cli_offer_eval_without_negotiation_levers(monkeypatch):
    _fake_setup(monkeypatch)

    async def fake_evaluate(
        config, provider, company, title, location, salary, bonus, benefits, level, notes
    ):
        return {
            "overall_score": 6,
            "competitive_score": 5,
            "growth_score": 6,
            "risk_score": 4,
            "summary": "ok",
            "pros": ["pro"],
            "cons": ["con"],
        }

    monkeypatch.setattr("agent_core.pipeline.offer_eval.evaluate", fake_evaluate)
    result = runner.invoke(app, ["offer-eval", "--company", "X"])
    assert result.exit_code == 0
    assert "综合评价: 6/10" in result.stdout
    assert "谈判杠杆" not in result.stdout


# ---------------------------------------------------------------------------
# import-cookies error
# ---------------------------------------------------------------------------


def test_cli_import_cookies_file_not_found(monkeypatch):
    def raise_not_found(*a, **k):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr("agent_core.platforms.cookie_utils.convert_and_save", raise_not_found)
    result = runner.invoke(app, ["import-cookies", "missing.json", "boss_zhipin"])
    assert result.exit_code != 0
    assert "[FAIL]" in result.stdout


# ---------------------------------------------------------------------------
# check-cookies
# ---------------------------------------------------------------------------


def test_cli_check_cookies_probe_boss(monkeypatch):
    config = _config({"boss_zhipin": SimpleNamespace()})
    _fake_setup(monkeypatch, config=config)
    results = [
        CookieHealthResult(
            platform_key="boss_zhipin",
            display_name="boss 直聘",
            status=CookieStatus.EXPIRED,
            file_exists=True,
            needs_cookie=True,
            details=["文件存在", "共 5 条", "文件修改时间 xx"],
            regrab_guide="重新抓取指引",
        ),
        CookieHealthResult(
            platform_key="tencent",
            display_name="腾讯招聘",
            status=CookieStatus.NO_COOKIE_NEEDED,
            file_exists=False,
            needs_cookie=False,
            details=["公开 API"],
        ),
    ]
    seen = {}

    async def fake_check(config, probe=False, platform_filter=None):
        seen["probe"] = probe
        return results

    async def fake_close():
        pass

    monkeypatch.setattr("agent_core.cookie_health.check_cookies", fake_check)
    monkeypatch.setattr("agent_core.platforms.zhilian_browser.close_browser", fake_close)
    monkeypatch.setattr("agent_core.platforms.playwright_jd.close_browser", fake_close)

    result = runner.invoke(app, ["check-cookies", "--probe"])
    assert result.exit_code == 0
    assert seen["probe"] is True
    assert "需要登录态" in result.stdout
    assert "公开 API" in result.stdout
    assert "重新抓取指引" in result.stdout
    assert "探活完成。Boss token" in result.stdout
    assert "共 5 条" not in result.stdout


def test_cli_check_cookies_no_probe_valid(monkeypatch):
    config = _config({"boss_zhipin": SimpleNamespace()})
    _fake_setup(monkeypatch, config=config)
    results = [
        CookieHealthResult(
            platform_key="boss_zhipin",
            display_name="boss 直聘",
            status=CookieStatus.VALID,
            file_exists=True,
            needs_cookie=True,
            details=["有效"],
            regrab_guide="",
        )
    ]

    async def fake_check(config, probe=False, platform_filter=None):
        return results

    async def fake_close():
        pass

    monkeypatch.setattr("agent_core.cookie_health.check_cookies", fake_check)
    monkeypatch.setattr("agent_core.platforms.zhilian_browser.close_browser", fake_close)
    monkeypatch.setattr("agent_core.platforms.playwright_jd.close_browser", fake_close)

    result = runner.invoke(app, ["check-cookies"])
    assert result.exit_code == 0
    assert "需要重抓 cookie" not in result.stdout
    assert "仅检查文件+过期时间" in result.stdout


# ---------------------------------------------------------------------------
# schedule / chat
# ---------------------------------------------------------------------------


def test_cli_schedule_status_with_last_error(monkeypatch):
    _fake_setup(monkeypatch)
    monkeypatch.setattr(
        "agent_core.scheduler.scheduler.schedule_status",
        lambda: {"enabled": True, "runs": 2, "last_run": "2026-01-01", "last_error": "boom"},
    )
    result = runner.invoke(app, ["schedule", "status"])
    assert result.exit_code == 0
    assert "Last error: boom" in result.stdout


def test_cli_chat_mocked(monkeypatch):
    provider = SimpleNamespace(model="fake")
    _fake_setup(monkeypatch, provider=provider)
    seen = {}

    async def fake_repl(config, db, provider):
        seen["provider"] = provider

    monkeypatch.setattr("agent_core.agent.repl.run_chat_repl", fake_repl)
    result = runner.invoke(app, ["chat"])
    assert result.exit_code == 0
    assert seen["provider"] is provider


def test_cli_chat_missing_provider(monkeypatch):
    config = _config()
    db = _FakeDB()
    import agent_core.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_setup", lambda *a, **k: (config, db, None))
    result = runner.invoke(app, ["chat"])
    assert result.exit_code != 0
    assert "LLM unavailable" in result.stdout


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def _make_cleanup_data(tmp_path):
    data = tmp_path / "data"
    profile = data / "zhilian_browser_profile" / "Default" / "Cache"
    profile.mkdir(parents=True)
    (profile / "c").write_text("x", encoding="utf-8")
    (data / "agent.log").write_text("log", encoding="utf-8")
    (data / "agent.db").write_text("db", encoding="utf-8")
    return data


def test_cli_cleanup_all_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_cleanup_data(tmp_path)
    result = runner.invoke(app, ["cleanup", "--all", "--dry-run"])
    assert result.exit_code == 0
    assert "浏览器 profile" in result.stdout
    assert "日志" in result.stdout
    assert "数据库" in result.stdout
    assert "--dry-run" in result.stdout
    assert (tmp_path / "data" / "agent.db").exists()


def test_cli_cleanup_cancel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _make_cleanup_data(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: "n")
    result = runner.invoke(app, ["cleanup", "--cache", "--logs"])
    assert result.exit_code == 0
    assert "已取消" in result.stdout
    assert (data / "agent.log").exists()


def test_cli_cleanup_confirm_delete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = _make_cleanup_data(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: "y")
    result = runner.invoke(app, ["cleanup", "--cache", "--logs"])
    assert result.exit_code == 0
    assert "清理完成" in result.stdout
    assert not (data / "agent.log").exists()
    assert not (data / "zhilian_browser_profile" / "Default" / "Cache").exists()


def test_cli_cleanup_delete_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_cleanup_data(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: "y")
    import shutil

    def fail_rmtree(path):
        raise OSError("denied")

    monkeypatch.setattr(shutil, "rmtree", fail_rmtree)
    result = runner.invoke(app, ["cleanup", "--cache", "--logs"])
    assert result.exit_code == 0
    assert "❌" in result.stdout
    assert "denied" in result.stdout
    assert "清理完成" in result.stdout


def test_cli_cleanup_no_items(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0
    assert "没有可清理的数据" in result.stdout
    assert "当前 data/ 大小" in result.stdout


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def test_cli_pick_critical_details():
    assert _pick_critical_details(["共 5 条", "文件修改时间 xx", "有效"]) == "有效"
    assert _pick_critical_details([]) == "N/A"


def test_cli_fmt_size():
    assert _fmt_size(0) == "0 B"
    assert _fmt_size(2048) == "2 KB"
    assert _fmt_size(2 * 1024 * 1024) == "2.0 MB"
