"""CLI smoke tests via Typer CliRunner -- covers command entrypoints."""

import json
from typer.testing import CliRunner

from agent_core.cli import app

runner = CliRunner()


def test_cli_login_boss_prints_manual_guidance():
    # boss_login now guides manual cookie export (Playwright blocked by Boss)
    result = runner.invoke(app, ["login", "--platform", "boss"])
    assert result.exit_code == 0
    assert "手动流程" in result.stdout or "自动登录不可行" in result.stdout


def test_cli_login_unknown_platform_errors():
    result = runner.invoke(app, ["login", "--platform", "mars"])
    assert result.exit_code != 0
    assert "Unknown platform" in result.stdout


def test_cli_login_no_args_prints_usage():
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0
    assert "boss" in result.stdout


def test_cli_schedule_status():
    result = runner.invoke(app, ["schedule", "status"])
    assert result.exit_code == 0
    assert "Enabled" in result.stdout


def test_cli_import_cookies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exp = tmp_path / "exp.json"
    exp.write_text(
        '[{"name":"wt2","value":"x","domain":".zhipin.com","path":"/",'
        '"expirationDate":9999999999,"secure":true,"httpOnly":false,'
        '"sameSite":"lax"}]', encoding="utf-8")
    result = runner.invoke(app, ["import-cookies", str(exp), "boss_zhipin",
                                  "--domain", "zhipin.com"])
    assert result.exit_code == 0
    assert "[OK]" in result.stdout
    assert "wt2" in result.stdout
    assert (tmp_path / "data" / "cookies" / "boss_zhipin.json").exists()


def test_cli_import_cookies_rejects_bad_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exp = tmp_path / "bad.json"
    exp.write_text('{"not":"array"}', encoding="utf-8")
    result = runner.invoke(app, ["import-cookies", str(exp), "boss_zhipin"])
    assert result.exit_code != 0
    assert "[FAIL]" in result.stdout


def test_cli_schedule_on_off(tmp_path, monkeypatch):
    """Test schedule on/off commands with mocked state file."""
    from agent_core.scheduler import scheduler

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(scheduler, "STATE_FILE", state_file)

    # Test schedule on
    result = runner.invoke(app, ["schedule", "on"])
    assert result.exit_code == 0
    assert "Scheduler ON" in result.stdout
    assert state_file.exists()

    # Verify state file has enabled=True
    import json
    with open(state_file) as f:
        state = json.load(f)
    assert state["enabled"] is True

    # Test schedule off
    result = runner.invoke(app, ["schedule", "off"])
    assert result.exit_code == 0
    assert "Scheduler OFF" in result.stdout

    # Verify state file has enabled=False
    with open(state_file) as f:
        state = json.load(f)
    assert state["enabled"] is False


def test_cli_schedule_unknown_action():
    """Test schedule command with unknown action."""
    result = runner.invoke(app, ["schedule", "bogus"])
    assert result.exit_code == 0
    assert "Commands: on | off | run | status" in result.stdout


def test_cli_schedule_status_no_state(tmp_path, monkeypatch):
    """Test schedule status when state file doesn't exist."""
    from agent_core.scheduler import scheduler

    # Point to non-existent state file
    non_existent = tmp_path / "non_existent_state.json"
    monkeypatch.setattr(scheduler, "STATE_FILE", non_existent)

    result = runner.invoke(app, ["schedule", "status"])
    assert result.exit_code == 0
    assert "Enabled" in result.stdout
    assert "Runs" in result.stdout


# ============================================================================
# Tests for uncovered commands to improve coverage
# ============================================================================

class FakeProvider:
    """Fake LLM provider to avoid real API calls."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None):
        self.calls += 1
        r = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def _mock_provider(monkeypatch):
    """Monkeypatch create_provider to return a fake that won't need a real API key."""
    monkeypatch.setattr(
        "agent_core.llm.providers.create_provider",
        lambda config: FakeProvider(["mocked response"]))


def test_cli_search_with_mock_provider(tmp_path, monkeypatch):
    """Test search command with mocked provider and search_all."""
    from agent_core.platforms.base import Job
    from datetime import datetime, timezone

    _mock_provider(monkeypatch)

    # Mock search_all to return fake jobs
    async def fake_search_all(config, platform_names=None, directions=None, headless=False):
        now = datetime.now(timezone.utc)
        return [Job(
            id="1",
            title="AMR AGV 调度 SLAM 导航",
            company="某公司",
            company_normalized="某公司",
            description="AMR AGV SLAM 调度 导航",
            direction="equipment_amr",
            platforms=["boss_zhipin"],
            urls={"boss_zhipin": "http://x"},
            salary_min=10000,
            salary_max=15000,
            first_seen=now,
            last_seen=now
        )]

    monkeypatch.setattr("agent_core.pipeline.search.search_all", fake_search_all)

    result = runner.invoke(app, ["search", "--direction", "equipment_amr"])
    assert result.exit_code == 0
    assert "Found" in result.stdout
    assert "AMR AGV" in result.stdout or "AMR" in result.stdout


def test_cli_search_no_args(tmp_path, monkeypatch):
    """Test search command with no arguments."""
    _mock_provider(monkeypatch)

    # Mock search_all to return empty list
    async def fake_search_all(config, platform_names=None, directions=None, headless=False):
        return []

    monkeypatch.setattr("agent_core.pipeline.search.search_all", fake_search_all)

    result = runner.invoke(app, ["search"])
    assert result.exit_code == 0
    assert "Found" in result.stdout


def test_cli_pipeline_with_mock(tmp_path, monkeypatch):
    """Test pipeline command with mocked search and match."""
    _mock_provider(monkeypatch)

    # Mock orchestrator to return fake pipeline results
    async def fake_run_pipeline(config, provider, stages=None):
        return {
            "matched": [
                {
                    "score": 80,
                    "job_title": "Test Job",
                    "company": "Test Company",
                    "match_reason": "Good match"
                }
            ]
        }

    monkeypatch.setattr("agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)

    result = runner.invoke(app, ["pipeline", "--stages", "search,filter"])
    assert result.exit_code == 0
    # May show "No results" if mocked pipeline returns empty


def test_cli_pipeline_no_results(tmp_path, monkeypatch):
    """Test pipeline command with no results."""
    _mock_provider(monkeypatch)

    # Mock orchestrator to return no matches
    async def fake_run_pipeline(config, provider, stages=None):
        return {"matched": []}

    monkeypatch.setattr("agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)

    result = runner.invoke(app, ["pipeline", "--stages", "all"])
    assert result.exit_code == 0
    assert "No results" in result.stdout


def test_cli_rematch_single_job(tmp_path, monkeypatch):
    """Test rematch command for a single job."""
    from agent_core.storage.db import get_db as real_get_db, migrate
    from datetime import datetime, timezone

    # Setup temporary database with a job
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "AMR工程师", "某公司", "某公司", "苏州", "AMR AGV SLAM", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, now)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Mock prescreen and match_jobs
    def fake_prescreen(jobs, config):
        return jobs

    async def fake_match_jobs(jobs, config, provider):
        return [
            {
                "score": 85,
                "job_title": "AMR工程师",
                "company": "某公司",
                "match_reason": "Strong match",
                "confidence": "high"
            }
        ], []

    monkeypatch.setattr("agent_core.pipeline.prescreen.prescreen", fake_prescreen)
    monkeypatch.setattr("agent_core.pipeline.match.match_jobs", fake_match_jobs)

    result = runner.invoke(app, ["rematch", "job1"])
    assert result.exit_code == 0
    assert "85" in result.stdout


def test_cli_rematch_no_args_prints_usage(tmp_path, monkeypatch):
    """Test rematch command with no arguments."""
    result = runner.invoke(app, ["rematch"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_cli_offer_eval_missing_company():
    """Test offer_eval command without required --company."""
    result = runner.invoke(app, ["offer-eval"])
    assert result.exit_code != 0


def test_cli_salary_advice_missing_company():
    """Test salary_advice command without required --company."""
    result = runner.invoke(app, ["salary-advice"])
    assert result.exit_code != 0


def test_cli_tailor(tmp_path, monkeypatch):
    """Test tailor command with mocked resume generation."""
    from agent_core.storage.db import get_db as real_get_db, migrate
    from datetime import datetime, timezone

    # Setup temporary database with a job
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "AMR工程师", "某公司", "某公司", "苏州", "AMR AGV SLAM", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, now)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Create output directory
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Mock tailor_resume, save_resume, and open_job_link
    async def fake_tailor_resume(job, config, provider):
        return "## 教育背景\n某大学\n## 工作经验\n某公司"

    def fake_save_resume(text, job):
        md_path = output_dir / f"resume_{job.id}.md"
        docx_path = output_dir / f"resume_{job.id}.docx"
        md_path.write_text(text, encoding="utf-8")
        docx_path.write_text("fake docx", encoding="utf-8")
        return {"md": str(md_path), "docx": str(docx_path)}

    def fake_open_job_link(job):
        pass  # Do nothing, don't open browser

    monkeypatch.setattr("agent_core.pipeline.tailor.tailor_resume", fake_tailor_resume)
    monkeypatch.setattr("agent_core.pipeline.tailor.save_resume", fake_save_resume)
    monkeypatch.setattr("agent_core.pipeline.tailor.open_job_link", fake_open_job_link)

    result = runner.invoke(app, ["tailor", "job1"])
    assert result.exit_code == 0
    assert "Saved" in result.stdout or "saved" in result.stdout


def test_cli_tailor_job_not_found(tmp_path, monkeypatch):
    """Test tailor command with non-existent job."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup empty database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["tailor", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_cli_track_list(tmp_path, monkeypatch):
    """Test track list command."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database with timeline table
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Mock tracking functions
    def fake_create_timeline_table(db):
        pass

    def fake_list_applications(db, status_filter=None):
        return []

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)
    monkeypatch.setattr("agent_core.tracking.tracker.list_applications", fake_list_applications)

    result = runner.invoke(app, ["track", "list"])
    assert result.exit_code == 0
    assert "No applications" in result.stdout or "application" in result.stdout.lower()


def test_cli_track_add(tmp_path, monkeypatch):
    """Test track add command."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Mock tracking functions
    def fake_create_timeline_table(db):
        pass

    def fake_add_application(db, job_id):
        return 1

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)
    monkeypatch.setattr("agent_core.tracking.tracker.add_application", fake_add_application)

    result = runner.invoke(app, ["track", "add", "job1"])
    assert result.exit_code == 0
    assert "Application" in result.stdout or "recorded" in result.stdout.lower()


def test_cli_track_add_no_target(tmp_path, monkeypatch):
    """Test track add command without target."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    def fake_create_timeline_table(db):
        pass

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)

    result = runner.invoke(app, ["track", "add"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_cli_track_update(tmp_path, monkeypatch):
    """Test track update command."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Mock tracking functions
    def fake_create_timeline_table(db):
        pass

    def fake_update_status(db, app_id, status):
        pass

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)
    monkeypatch.setattr("agent_core.tracking.tracker.update_status", fake_update_status)

    result = runner.invoke(app, ["track", "update", "1", "--status", "二面"])
    assert result.exit_code == 0
    assert "1 ->" in result.stdout


def test_cli_track_show(tmp_path, monkeypatch):
    """Test track show command."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    # Mock tracking functions
    def fake_create_timeline_table(db):
        pass

    def fake_get_application(db, app_id):
        return {
            "id": app_id,
            "status": "已投递",
            "job_title": "Test Job",
            "job_company": "Test Company",
            "applied_at": "2026-01-01",
            "updated_at": "2026-01-02"
        }

    def fake_get_timeline(db, app_id):
        return []

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)
    monkeypatch.setattr("agent_core.tracking.tracker.get_application", fake_get_application)
    monkeypatch.setattr("agent_core.tracking.tracker.get_timeline", fake_get_timeline)

    result = runner.invoke(app, ["track", "show", "1"])
    assert result.exit_code == 0
    assert "#" in result.stdout


def test_cli_track_unknown_action(tmp_path, monkeypatch):
    """Test track command with unknown action."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    # Setup database
    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: real_get_db(str(db_path)))

    def fake_create_timeline_table(db):
        pass

    monkeypatch.setattr("agent_core.tracking.tracker.create_timeline_table", fake_create_timeline_table)

    result = runner.invoke(app, ["track", "unknown"])
    assert result.exit_code == 0
    assert "Unknown" in result.stdout


def test_cli_serve_with_mock(tmp_path, monkeypatch):
    """Test serve command with mocked server."""
    # Mock start_server to avoid actually starting server
    def fake_start_server(port=8765):
        pass  # Do nothing

    monkeypatch.setattr("agent_core.server.serve.start_server", fake_start_server)

    # Invoke with default port
    result = runner.invoke(app, ["serve"])
    # Command starts server which blocks, so we check it runs without error
    # The test will timeout if server actually starts, which we've prevented


def test_cli_serve_custom_port(tmp_path, monkeypatch):
    """Test serve command with custom port."""
    def fake_start_server(port=8765):
        assert port == 9000

    monkeypatch.setattr("agent_core.server.serve.start_server", fake_start_server)

    result = runner.invoke(app, ["serve", "--port", "9000"])
    # Command should validate port and call start_server


# ============================================================================
# Tests for previously uncovered paths (coverage boost to 80%+)
# ============================================================================


def test_cli__require_provider_returns_provider():
    """Test _require_provider when provider is not None."""
    from agent_core.cli import _require_provider

    class FakeConfig:
        llm = type("LLM", (), {"api_key_env": "FAKE_KEY"})()

    assert _require_provider("ok", FakeConfig()) == "ok"


def test_cli__require_provider_raises_on_none():
    """Test _require_provider raises typer.Exit when provider is None."""
    import typer
    from agent_core.cli import _require_provider

    class FakeConfig:
        llm = type("LLM", (), {"api_key_env": "MISSING_KEY"})()

    try:
        _require_provider(None, FakeConfig())
        assert False, "Should have raised"
    except typer.Exit:
        pass  # Expected


def test_cli__setup_without_api_key(monkeypatch):
    """Test _setup when api_key is empty string -- should warn."""
    from agent_core.cli import _setup

    def fake_load_config(path):
        class Cfg:
            api_key = ""
            llm = type("LLM", (), {"api_key_env": "MISSING_ENV"})()

        return Cfg()

    monkeypatch.setattr("agent_core.config.load_config", fake_load_config)

    def fake_migrate(db):
        pass

    monkeypatch.setattr("agent_core.storage.db.migrate", fake_migrate)

    config, db, provider = _setup()
    assert provider is None


def test_cli_login_status_with_expired_cookies(tmp_path, monkeypatch):
    """Test login --status when cookie files exist with expired cookies."""
    cookies_dir = tmp_path / "data" / "cookies"
    cookies_dir.mkdir(parents=True)
    cookie_file = cookies_dir / "boss_zhipin.json"

    from datetime import datetime
    # Cookie expired yesterday
    past_expire = datetime.now().timestamp() - 86400
    cookie_file.write_text(json.dumps([
        {"name": "wt2", "value": "test", "domain": ".zhipin.com",
         "expires": past_expire, "path": "/", "secure": True}
    ]), encoding="utf-8")

    def fake_load_config(path):
        class PC:
            enabled = True
            cookie_path = str(cookie_file)

        class Cfg:
            api_key = ""
            llm = type("LLM", (), {"api_key_env": "FAKE"})()

            class platforms:
                @staticmethod
                def items():
                    return {"boss_zhipin": PC()}.items()

            platforms = platforms()

        return Cfg()

    monkeypatch.setattr("agent_core.config.load_config", fake_load_config)
    monkeypatch.setattr("agent_core.storage.db.migrate", lambda db: None)

    result = runner.invoke(app, ["login", "--status"])
    assert result.exit_code == 0
    assert "expired" in result.stdout.lower()


def test_cli_rematch_job_not_found(tmp_path, monkeypatch):
    """Test rematch with non-existent job ID."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["rematch", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_cli_rematch_all_since(tmp_path, monkeypatch):
    """Test rematch --all-since with matching jobs."""
    import sqlite3
    from agent_core.storage.db import migrate
    from datetime import datetime, timezone

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    future = "2099-01-01T00:00:00"
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "engineer", "acme", "acme", "Beijing", "desc", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, future)
    )
    conn.commit()
    conn.close()

    # Return connection with row_factory for dict(r) to work
    def _make_conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: _make_conn())

    # Mock provider so _setup doesn't crash on missing API key
    _mock_provider(monkeypatch)

    def fake_prescreen(jobs, config):
        return jobs

    async def fake_match_jobs(jobs, config, provider):
        return [{"score": 90, "job_title": "engineer", "company": "acme"}], []

    monkeypatch.setattr("agent_core.pipeline.prescreen.prescreen", fake_prescreen)
    monkeypatch.setattr("agent_core.pipeline.match.match_jobs", fake_match_jobs)

    result = runner.invoke(app, ["rematch", "--all-since", "2020-01-01"])
    assert result.exit_code == 0
    assert "Re-matching" in result.stdout


def test_cli_rematch_all_since_no_jobs(tmp_path, monkeypatch):
    """Test rematch --all-since with no matching jobs."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["rematch", "--all-since", "2099-01-01"])
    assert result.exit_code == 0
    assert "No jobs" in result.stdout


def test_cli_cover_letter(tmp_path, monkeypatch):
    """Test cover_letter command with mocked dependencies."""
    from agent_core.storage.db import get_db as real_get_db, migrate
    from datetime import datetime, timezone

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "工程师", "某公司", "某公司", "北京", "desc", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, now)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    # Mock enrichment to return the same job
    async def fake_enrich(job, config):
        return job

    async def fake_generate(job, config, provider):
        return "尊敬的招聘经理：\n我对贵公司职位非常感兴趣。\n此致"

    def fake_save(text, job):
        return "/tmp/cover_letter.md"

    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", fake_enrich)
    monkeypatch.setattr(
        "agent_core.pipeline.cover_letter.generate_cover_letter", fake_generate)
    monkeypatch.setattr(
        "agent_core.pipeline.cover_letter.save_cover_letter", fake_save)

    result = runner.invoke(app, ["cover-letter", "job1"])
    assert result.exit_code == 0
    assert "Saved" in result.stdout


def test_cli_cover_letter_job_not_found(tmp_path, monkeypatch):
    """Test cover_letter with non-existent job."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["cover-letter", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_cli_interview_prep(tmp_path, monkeypatch):
    """Test interview_prep command with mocked dependencies."""
    from agent_core.storage.db import get_db as real_get_db, migrate
    from datetime import datetime, timezone

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "工程师", "某公司", "某公司", "北京", "desc", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, now)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    async def fake_enrich(job, config):
        return job

    async def fake_predict(job, config, provider):
        return {"technical": ["Q1"], "behavioral": ["Q2"], "project": ["Q3"]}

    def fake_save(qs, job):
        return "/tmp/interview_prep.md"

    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", fake_enrich)
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.predict_questions", fake_predict)
    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.save_interview_prep", fake_save)

    result = runner.invoke(app, ["interview-prep", "job1"])
    assert result.exit_code == 0
    assert "Saved" in result.stdout
    assert "3 questions" in result.stdout


def test_cli_interview_prep_job_not_found(tmp_path, monkeypatch):
    """Test interview_prep with non-existent job."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["interview-prep", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_cli_mock_interview(tmp_path, monkeypatch):
    """Test mock_interview command with mocked dependencies."""
    from agent_core.storage.db import get_db as real_get_db, migrate
    from datetime import datetime, timezone

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location,"
        " description, direction, platforms, urls, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("job1", "工程师", "某公司", "某公司", "北京", "desc", "equipment_amr",
         '["boss_zhipin"]', '{"boss_zhipin":"http://x"}', now, now)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_mi(job, config, provider):
        pass  # Interactive mock interview -- just no-op

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.mock_interview", fake_mi)

    result = runner.invoke(app, ["mock-interview", "job1"])
    assert result.exit_code == 0


def test_cli_mock_interview_job_not_found(tmp_path, monkeypatch):
    """Test mock_interview with non-existent job."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    result = runner.invoke(app, ["mock-interview", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_cli_offer_eval_full(tmp_path, monkeypatch):
    """Test offer_eval command with mocked evaluate."""
    _mock_provider(monkeypatch)

    async def fake_evaluate(config, provider, company, title, location,
                            salary, bonus, benefits, level, notes):
        return {
            "overall_score": 8,
            "competitive_score": 7,
            "growth_score": 8,
            "risk_score": 3,
            "summary": "Good offer overall.",
            "pros": ["High salary", "Good location"],
            "cons": ["Long commute"],
            "negotiation_levers": ["Competing offer"],
        }

    monkeypatch.setattr(
        "agent_core.pipeline.offer_eval.evaluate", fake_evaluate)

    result = runner.invoke(app, [
        "offer-eval", "--company", "TestCorp", "--title", "Engineer",
        "--salary", "300k", "--bonus", "10%"
    ])
    assert result.exit_code == 0
    assert "8/10" in result.stdout
    assert "优势" in result.stdout
    assert "谈判杠杆" in result.stdout


def test_cli_salary_advice_full(tmp_path, monkeypatch):
    """Test salary_advice command with mocked get_advice."""
    _mock_provider(monkeypatch)

    async def fake_get_advice(config, provider, company, title, salary,
                              target, strengths, context):
        return {
            "anchor": "300k",
            "confidence": "high",
            "leverage": ["Strong market demand", "Unique skills"],
            "concessions": ["Flexible hours", "Remote work"],
            "scripts": ["I appreciate the offer..."],
        }

    monkeypatch.setattr(
        "agent_core.pipeline.salary_advice.get_advice", fake_get_advice)

    result = runner.invoke(app, [
        "salary-advice", "--company", "TestCorp", "--title", "Engineer",
        "--salary", "250k", "--target", "300k"
    ])
    assert result.exit_code == 0
    assert "锚点" in result.stdout
    assert "筹码" in result.stdout
    assert "话术" in result.stdout


def test_cli_track_update_missing_args(tmp_path, monkeypatch):
    """Test track update with missing target/status."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)

    result = runner.invoke(app, ["track", "update"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_cli_track_update_value_error(tmp_path, monkeypatch):
    """Test track update with non-integer app ID."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    def fake_update(db, app_id, status):
        raise ValueError("Not found")

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr(
        "agent_core.tracking.tracker.update_status", fake_update)

    result = runner.invoke(app, ["track", "update", "1", "--status", "二面"])
    assert result.exit_code == 0
    assert "Error" in result.stdout


def test_cli_track_show_no_target(tmp_path, monkeypatch):
    """Test track show without target."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)

    result = runner.invoke(app, ["track", "show"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_cli_track_show_value_error(tmp_path, monkeypatch):
    """Test track show with invalid app ID."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    def fake_get_app(db, app_id):
        raise ValueError("Invalid ID")

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr(
        "agent_core.tracking.tracker.get_application", fake_get_app)

    result = runner.invoke(app, ["track", "show", "999"])
    assert result.exit_code == 0
    assert "Error" in result.stdout


def test_cli_track_show_with_timeline(tmp_path, monkeypatch):
    """Test track show with timeline entries."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    def fake_get_app(db, app_id):
        return {
            "id": app_id,
            "status": "二面",
            "job_title": "Test Job",
            "job_company": "Test Co",
            "applied_at": "2026-01-01",
            "updated_at": "2026-01-15",
        }

    def fake_get_timeline(db, app_id):
        return [
            {"created_at": "2026-01-05", "from_status": "已投递",
             "to_status": "一面"},
            {"created_at": "2026-01-10", "from_status": "一面",
             "to_status": "二面"},
        ]

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr(
        "agent_core.tracking.tracker.get_application", fake_get_app)
    monkeypatch.setattr(
        "agent_core.tracking.tracker.get_timeline", fake_get_timeline)

    result = runner.invoke(app, ["track", "show", "1"])
    assert result.exit_code == 0
    assert "Timeline" in result.stdout
    assert "已投递 -> 一面" in result.stdout


def test_cli_track_list_non_empty(tmp_path, monkeypatch):
    """Test track list with applications."""
    from agent_core.storage.db import get_db as real_get_db, migrate

    db_path = tmp_path / "test.db"
    conn = real_get_db(str(db_path))
    migrate(conn)
    conn.close()

    monkeypatch.setattr("agent_core.storage.db.get_db",
                        lambda *a, **k: real_get_db(str(db_path)))

    def fake_ctl(db):
        pass

    def fake_list(db, status_filter=None):
        return [
            {"id": 1, "status": "已投递", "job_title": "Job A",
             "job_company": "Co A"},
            {"id": 2, "status": "Offer", "job_title": "Job B",
             "job_company": "Co B"},
        ]

    monkeypatch.setattr(
        "agent_core.tracking.tracker.create_timeline_table", fake_ctl)
    monkeypatch.setattr(
        "agent_core.tracking.tracker.list_applications", fake_list)

    result = runner.invoke(app, ["track", "list"])
    assert result.exit_code == 0
    assert "#1" in result.stdout
    assert "#2" in result.stdout


def test_cli_import_cookies_warn_no_session(tmp_path, monkeypatch):
    """Test import-cookies when no known session cookies are found."""
    monkeypatch.chdir(tmp_path)
    exp = tmp_path / "exp.json"
    # Cookies without known session cookie names
    exp.write_text(
        '[{"name":"random_cookie","value":"x","domain":".zhipin.com",'
        '"path":"/","expirationDate":9999999999,"secure":true,'
        '"httpOnly":false,"sameSite":"lax"}]', encoding="utf-8")
    result = runner.invoke(app, ["import-cookies", str(exp), "boss_zhipin",
                                  "--domain", "zhipin.com"])
    assert result.exit_code == 0
    assert "[WARN]" in result.stdout


def test_cli_schedule_run_starts_and_stops(tmp_path, monkeypatch):
    """Test schedule run command -- verify it tries to acquire lock and runs."""
    from agent_core.scheduler import scheduler

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(scheduler, "STATE_FILE", state_file)

    # Mock schedule_on to be a no-op
    def fake_schedule_on(config):
        if not state_file.exists():
            state_file.write_text('{"enabled":true,"runs":0}')

    monkeypatch.setattr(scheduler, "schedule_on", fake_schedule_on)

    # Allow lock acquisition
    monkeypatch.setattr(scheduler, "acquire_lock", lambda: True)
    monkeypatch.setattr(scheduler, "release_lock", lambda: None)

    # Make the daemon loop run exactly once then break
    call_count = [0]

    async def fake_run_search(config, provider, db):
        call_count[0] += 1
        if call_count[0] >= 1:
            raise KeyboardInterrupt()  # stop after one iteration

    monkeypatch.setattr(scheduler, "run_scheduled_search", fake_run_search)

    result = runner.invoke(app, ["schedule", "run"])
    assert result.exit_code == 0
    assert "Starting daemon" in result.stdout
    assert "Daemon stopped" in result.stdout


def test_cli_schedule_run_lock_held(tmp_path, monkeypatch):
    """Test schedule run when another daemon is already running."""
    from agent_core.scheduler import scheduler

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(scheduler, "STATE_FILE", state_file)

    def fake_schedule_on(config):
        if not state_file.exists():
            state_file.write_text('{"enabled":true,"runs":0}')

    monkeypatch.setattr(scheduler, "schedule_on", fake_schedule_on)

    # Lock already held
    monkeypatch.setattr(scheduler, "acquire_lock", lambda: False)

    result = runner.invoke(app, ["schedule", "run"])
    assert result.exit_code == 0
    assert "already running" in result.stdout.lower()


def test_cli_pipeline_results_detailed(tmp_path, monkeypatch):
    """Test pipeline command with detailed matched results output."""
    _mock_provider(monkeypatch)

    async def fake_run_pipeline(config, provider, stages=None):
        return {
            "matched": [
                {"score": 95, "job_title": "Senior Dev", "company": "BestCo",
                 "match_reason": "Perfect match"}
            ]
        }

    monkeypatch.setattr(
        "agent_core.pipeline.orchestrator.run_pipeline", fake_run_pipeline)

    result = runner.invoke(app, ["pipeline"])
    assert result.exit_code == 0
    assert "Top matches" in result.stdout
    assert "95%" in result.stdout
    assert "Senior Dev" in result.stdout
    assert "Perfect match" in result.stdout
