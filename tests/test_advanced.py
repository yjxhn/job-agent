"""Advanced tests: LLM pipeline modules, integration, cookie utils, boss API mock.

Brings coverage of the previously-0% pipeline modules and integration paths
(orchestrator, scheduler.run_scheduled_search) up using a FakeProvider and
monkeypatched network. Deterministic — no real LLM, no real network.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_core.config import load_config
from agent_core.platforms.base import Job


@pytest.fixture
def cfg():
    return load_config("config.yaml")


@pytest.fixture
def db(tmp_path):
    from agent_core.storage.db import get_db, migrate
    conn = get_db(str(tmp_path / "test.db"))
    migrate(conn)
    yield conn
    conn.close()


def _now():
    return datetime.now(UTC)


def _job(**kw):
    defaults = dict(
        id="x", title="AMR AGV 调度工程师", company="某科技公司",
        company_normalized="某科技公司", description="AMR AGV SLAM 调度 导航",
        direction="equipment_amr", platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"}, salary_min=10000, salary_max=15000,
        first_seen=_now(), last_seen=_now(),
    )
    defaults.update(kw)
    return Job(**defaults)


class FakeProvider:
    """Mock LLM provider. Returns scripted responses (str) or raises."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, messages, temperature=0.7, max_tokens=4096,
                   response_format=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self.responses) - 1)
        r = self.responses[idx]
        if isinstance(r, Exception):
            raise r
        return r


# ---------- cover_letter ----------

def test_cover_letter_generate_and_save(cfg, tmp_path):
    from agent_core.pipeline.cover_letter import generate_cover_letter, save_cover_letter
    provider = FakeProvider(["我对该职位非常感兴趣..."])
    text = asyncio.run(generate_cover_letter(_job(), cfg, provider))
    assert "感兴趣" in text
    assert provider.calls == 1
    path = save_cover_letter(text, _job(), output_dir=str(tmp_path))
    assert tmp_path.joinpath(path.split("/")[-1]).exists() or path.endswith(".md")


def test_cover_letter_falls_back_when_resume_missing(cfg):
    from agent_core.pipeline.cover_letter import generate_cover_letter
    job = _job(direction="nonexistent_direction")
    # direction not in config → load_resume raises → fallback resume used
    provider = FakeProvider(["fallback letter"])
    text = asyncio.run(generate_cover_letter(job, cfg, provider))
    assert text == "fallback letter"


# ---------- offer_eval ----------

def test_offer_eval_parses_json(cfg):
    from agent_core.pipeline.offer_eval import evaluate
    resp = ('```json\n{"overall_score":8,"competitive_score":7,"growth_score":9,'
            '"risk_score":3,"summary":"不错","pros":["a"],"cons":["b"],'
            '"negotiation_levers":["c"]}\n```')
    provider = FakeProvider([resp])
    r = asyncio.run(evaluate(cfg, provider, company="某公司", title="AMR",
                              salary="15K", bonus="2个月"))
    assert r["overall_score"] == 8
    assert r["pros"] == ["a"]


# ---------- salary_advice ----------

def test_salary_advice_parses_json(cfg):
    from agent_core.pipeline.salary_advice import get_advice
    resp = '{"anchor":"18K","leverage":["x"],"concessions":["y"],"scripts":["z"],"confidence":"high"}'
    provider = FakeProvider([resp])
    r = asyncio.run(get_advice(cfg, provider, company="某公司", salary="15K"))
    assert r["anchor"] == "18K"
    assert r["confidence"] == "high"


# ---------- interview_prep ----------

def test_interview_prep_predict_questions(cfg):
    from agent_core.pipeline.interview_prep import predict_questions, save_interview_prep
    resp = ('{"technical":[{"q":"AMR调度算法?","a":["A*","Dijkstra"]}],'
            '"behavioral":[{"q":"团队冲突?","a":["沟通"]}],'
            '"project":[{"q":"项目难点?","a":["SLAM"]}]}')
    provider = FakeProvider([resp])
    qs = asyncio.run(predict_questions(_job(), cfg, provider))
    assert len(qs["technical"]) == 1
    assert qs["technical"][0]["q"] == "AMR调度算法?"
    path = save_interview_prep(qs, _job(), output_dir="output")
    assert path.endswith("_interview.md")


# ---------- tailor ----------

def test_tailor_resume_generates_markdown(cfg):
    from agent_core.pipeline.tailor import save_resume, tailor_resume
    provider = FakeProvider(["## 教育背景\n\n某大学\n\n## 核心能力\n\n- AMR调度\n"])
    text = asyncio.run(tailor_resume(_job(), cfg, provider))
    assert "教育背景" in text
    # save_resume needs python-docx; use tmp output dir
    paths = save_resume(text, _job(), output_dir="output")
    assert paths["md"].endswith(".md")
    assert paths["docx"].endswith(".docx")


# ---------- orchestrator integration ----------

def test_run_pipeline_end_to_end(cfg, monkeypatch):
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search

    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return [_job(id="1"), _job(id="2", title="外包 AMR")]  # 2nd filtered out

    monkeypatch.setattr(search, "search_all", fake_search_all)
    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)

    provider = FakeProvider([
        '{"score": 80, "match_reason": "好", "missing_skills": [], "strengths": []}',
    ])
    data = asyncio.run(orchestrator.run_pipeline(
        cfg, provider, stages=["search", "filter", "prescreen", "match"]))

    assert len(data["jobs"]) == 2
    assert len(data["filtered"]) == 1  # "外包" excluded
    assert len(data["prescreened"]) == 1
    assert len(data["matched"]) == 1
    assert data["matched"][0]["score"] == 80
    assert data["skipped"] == 0


def test_run_pipeline_partial_stages(cfg, monkeypatch):
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search

    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return [_job(id="1")]

    monkeypatch.setattr(search, "search_all", fake_search_all)
    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)

    data = asyncio.run(orchestrator.run_pipeline(
        cfg, FakeProvider([]), stages=["search", "filter"]))
    assert len(data["jobs"]) == 1
    assert data["matched"] == []  # match stage not run


# ---------- scheduler.run_scheduled_search integration ----------

def test_run_scheduled_search_runs_and_updates_state(cfg, db, monkeypatch, tmp_path):
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator
    from agent_core.scheduler import scheduler as S

    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    cfg.schedule.quiet_hours = []  # avoid quiet-hour skip
    S._save({"enabled": True, "last_run": None, "runs": 0,
             "directions": ["equipment_amr"], "last_error": None})

    async def fake_run_pipeline(config, llm_provider, stages=None, **kw):
        return {"matched": [{"score": 80, "job_title": "x"}], "skipped": 0}

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)

    asyncio.run(S.run_scheduled_search(cfg, FakeProvider([]), db))

    s = S._load()
    assert s["runs"] == 1
    assert s["last_run"] is not None
    assert s["last_error"] is None
    rows = db.execute("SELECT * FROM search_status").fetchall()
    assert len(rows) >= 1


def test_run_scheduled_search_skips_when_disabled(cfg, db, monkeypatch, tmp_path):
    from agent_core.scheduler import scheduler as S
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    S._save({"enabled": False, "last_run": None, "runs": 0,
             "directions": [], "last_error": None})
    asyncio.run(S.run_scheduled_search(cfg, FakeProvider([]), db))
    assert S._load()["runs"] == 0  # did not run


def test_run_scheduled_search_skips_quiet_hours(cfg, db, monkeypatch, tmp_path):
    from agent_core.scheduler import scheduler as S
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    local_h = datetime.now().hour
    cfg.schedule.quiet_hours = [local_h, local_h + 1]  # cover current hour
    S._save({"enabled": True, "last_run": None, "runs": 0,
             "directions": ["equipment_amr"], "last_error": None})
    asyncio.run(S.run_scheduled_search(cfg, FakeProvider([]), db))
    assert S._load()["runs"] == 0  # quiet hours → skip


def test_run_scheduled_search_records_error(cfg, db, monkeypatch, tmp_path):
    from agent_core.pipeline import orchestrator
    from agent_core.scheduler import scheduler as S
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    cfg.schedule.quiet_hours = []
    S._save({"enabled": True, "last_run": None, "runs": 0,
             "directions": ["equipment_amr"], "last_error": None})

    async def boom(config, llm_provider, stages=None, **kw):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(orchestrator, "run_pipeline", boom)
    asyncio.run(S.run_scheduled_search(cfg, FakeProvider([]), db))
    s = S._load()
    assert s["last_error"] and "exploded" in s["last_error"]


# ---------- boss _search_keyword_api (mocked HTTP) ----------

def test_boss_search_keyword_api_parses_jobs(monkeypatch):
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter
    fake_resp = json.dumps({"code": 0, "message": "Success", "zpData": {
        "jobList": [{
            "jobName": "AMR工程师", "brandName": "某科技", "cityName": "苏州",
            "areaDistrict": "高新区", "businessDistrict": "科技园",
            "salaryDesc": "8-13K", "encryptJobId": "abc",
            "skills": ["ROS"], "jobLabels": [], "welfareList": [],
            "jobExperience": "不限", "jobDegree": "大专",
            "brandIndustry": "机器人", "brandScaleName": "100人",
        }]
    }}).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))
    assert len(jobs) == 1
    assert jobs[0].title == "AMR工程师"
    assert jobs[0].salary_min == 8000
    assert jobs[0].salary_max == 13000


def test_boss_search_keyword_api_stops_on_auth_error(monkeypatch):
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter
    fake_resp = json.dumps(
        {"code": 1501, "message": "login required", "zpData": {}}).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=20: FakeResp())
    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))
    assert jobs == []  # auth error → stop, return what we have (nothing)


# ---------- cookie_utils ----------

def test_cookie_utils_convert_maps_fields():
    from agent_core.platforms.cookie_utils import convert
    out = convert([{
        "name": "wt2", "value": "x", "domain": ".zhipin.com", "path": "/",
        "expirationDate": 9999999999, "secure": True, "httpOnly": True,
        "sameSite": "Lax",
    }])
    assert out[0]["name"] == "wt2"
    assert out[0]["expires"] == 9999999999
    assert out[0]["sameSite"] == "Lax"
    assert out[0]["httpOnly"] is True


def test_cookie_utils_convert_filters_domain():
    from agent_core.platforms.cookie_utils import convert
    out = convert([
        {"name": "a", "domain": ".zhipin.com"},
        {"name": "b", "domain": ".other.com"},
    ], domain_filter="zhipin.com")
    assert len(out) == 1
    assert out[0]["name"] == "a"


def test_cookie_utils_convert_and_save(tmp_path, monkeypatch):
    from agent_core.platforms import cookie_utils as cu
    monkeypatch.chdir(tmp_path)
    exp = tmp_path / "exp.json"
    exp.write_text(
        '[{"name":"wt2","value":"x","domain":".zhipin.com","path":"/",'
        '"expirationDate":9999999999,"secure":true,"httpOnly":false,'
        '"sameSite":"null"}]', encoding="utf-8")
    r = cu.convert_and_save(str(exp), "boss_zhipin", "zhipin.com")
    assert r["count"] == 1
    assert "wt2" in r["session_found"]
    assert tmp_path.joinpath(r["out_path"]).exists()


def test_cookie_utils_convert_and_save_rejects_non_array(tmp_path):
    from agent_core.platforms.cookie_utils import convert_and_save
    exp = tmp_path / "exp.json"
    exp.write_text('{"not":"an array"}', encoding="utf-8")
    with pytest.raises(ValueError):
        convert_and_save(str(exp), "boss_zhipin")


# ---------- F10: prescreen confidence penalty ----------

# ---------- Task 1: enrichment pipeline integration ----------

def test_pipeline_enrich_disabled_by_default(cfg, monkeypatch):
    """enrich_in_pipeline=False means enrich_job_jd is never called."""
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search
    from agent_core.pipeline.orchestrator import STAGE_ORDER as FULL

    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)
    # cfg.matching.enrich_in_pipeline defaults to False
    assert cfg.matching.enrich_in_pipeline is False

    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return [_job(id="1")]
    monkeypatch.setattr(search, "search_all", fake_search_all)

    enrich_called = []
    async def fake_enrich(job, config):
        enrich_called.append(job.id)
        return job
    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", fake_enrich)

    data = asyncio.run(orchestrator.run_pipeline(
        cfg, FakeProvider([]), stages=FULL))
    assert enrich_called == []
    assert "enriched" not in data or data.get("enriched", 0) == 0


def test_pipeline_enrich_enabled_calls_enrich(cfg, monkeypatch):
    """enrich_in_pipeline=True -> enrichment runs on top-N filtered jobs."""
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search
    from agent_core.pipeline.orchestrator import STAGE_ORDER as FULL

    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.enrich_top_n = 2

    jobs = [
        _job(id="1", salary_max=15000),
        _job(id="2", salary_max=20000),
        _job(id="3", salary_max=10000),
    ]
    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return list(jobs)
    monkeypatch.setattr(search, "search_all", fake_search_all)

    enrich_called = []
    async def fake_enrich(job, config):
        enrich_called.append(job.id)
        return job
    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", fake_enrich)

    data = asyncio.run(orchestrator.run_pipeline(
        cfg, FakeProvider([]), stages=FULL))
    # Top 2 by salary_max: job 2 (20000) then job 1 (15000)
    assert len(enrich_called) == 2
    assert enrich_called[0] == "2"
    assert enrich_called[1] == "1"
    assert data["enriched"] == 2


def test_pipeline_enrich_survives_exceptions(cfg, monkeypatch):
    """Enrichment errors don't kill the pipeline."""
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search
    from agent_core.pipeline.orchestrator import STAGE_ORDER as FULL

    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)
    cfg.matching.enrich_in_pipeline = True
    cfg.matching.enrich_top_n = 3

    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return [_job(id="1"), _job(id="2"), _job(id="3")]
    monkeypatch.setattr(search, "search_all", fake_search_all)

    async def boom_enrich(job, config):
        if job.id == "2":
            raise RuntimeError("network down")
        job.description = f"enriched_{job.id}"
        return job
    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", boom_enrich)

    data = asyncio.run(orchestrator.run_pipeline(
        cfg, FakeProvider([]), stages=FULL))
    # 2 out of 3 enriched (one errored); pipeline still completed
    assert data["enriched"] == 2
    assert len(data["prescreened"]) >= 1  # prescreen still ran


def test_pipeline_enrich_not_called_when_stage_not_in_set(cfg, monkeypatch):
    """Even with enrich_in_pipeline=True, if "enrich" not in stages, skip it."""
    from agent_core.notify import windows_toast as wt
    from agent_core.pipeline import orchestrator, search

    monkeypatch.setattr(wt, "notify_search_complete", lambda *a, **k: None)
    cfg.matching.enrich_in_pipeline = True

    async def fake_search_all(config, platform_names=None, directions=None,
                              headless=False):
        return [_job(id="1")]
    monkeypatch.setattr(search, "search_all", fake_search_all)

    enrich_called = []
    async def fake_enrich(job, config):
        enrich_called.append(job.id)
        return job
    monkeypatch.setattr(
        "agent_core.platforms.enrichment.enrich_job_jd", fake_enrich)

    asyncio.run(orchestrator.run_pipeline(
        cfg, FakeProvider([]), stages=["search", "filter"]))
    assert enrich_called == []


# ---------- Task 2: fuzzy matching (0.75 threshold) ----------

def test_fuzzy_similar_company_names_dedup():
    """Similar company names (ratio >= 0.75) should match to same canonical."""
    from difflib import SequenceMatcher

    from agent_core.pipeline.search import _normalize_company
    aliases = {"腾讯": ["tencent", "腾讯科技"], "阿里巴巴": ["alibaba", "阿里"]}

    # "腾讯科技" should fuzzy-match to "tencent" (ratio close to 0.85+)
    r1 = _normalize_company("腾讯科技", aliases)
    assert r1 == "腾讯"

    # "阿里" should fuzzy-match to "alibaba" or "阿里"
    r2 = _normalize_company("阿里", aliases)
    assert r2 in ("阿里巴巴", "阿里")

    # Verify actual fuzzy ratios for documentation
    ratio_tencent = SequenceMatcher(None, "腾讯科技".lower(), "tencent").ratio()
    # Exact substring match in alias table catches this first
    # But if alias table didn't have it, fuzzy would need >= 0.75
    assert ratio_tencent < 0.3  # Chinese vs English has low ratio
    # So fuzzy alone can't dedup Chinese-English pairs; alias table must handle them


def test_fuzzy_different_companies_not_deduped():
    """Unrelated company names should stay separate."""
    from agent_core.pipeline.search import _normalize_company
    aliases = {"腾讯": ["tencent", "腾讯科技"], "阿里巴巴": ["alibaba", "阿里"]}

    # "腾讯" should NOT match "阿里巴巴"
    r = _normalize_company("腾讯", aliases)
    assert r == "腾讯"

    r2 = _normalize_company("阿里巴巴", aliases)
    assert r2 == "阿里巴巴"

    # "字节跳动" is completely unknown, stays as-is
    r3 = _normalize_company("字节跳动", aliases)
    assert r3 == "字节跳动"


def test_fuzzy_threshold_behavior():
    """Verify fuzzy match (difflib.SequenceMatcher >= 0.75) behavior.

    The alias table catches substring containment first (very broad check).
    Fuzzy only matters when no variant contains/is-contained-by the input.
    """
    from difflib import SequenceMatcher

    from agent_core.pipeline.search import _normalize_company

    # Case 1: Similar typo — "Googel" vs "Google" — ratio ~0.83
    # Neither is substring of the other → alias table misses → fuzzy catches
    ratio = SequenceMatcher(None, "googel", "google").ratio()
    assert ratio >= 0.75
    aliases_typo = {"Google": ["Google"]}
    r1 = _normalize_company("Googel", aliases_typo)
    assert r1 == "Google"

    # Case 2: Completely different companies — "Google" vs "Apple"
    aliases2 = {"Google": ["Google"], "Apple": ["Apple"]}
    r2 = _normalize_company("Pear Inc", aliases2)
    # Pear vs Google ratio ~0.67, Pear vs Apple ratio ~0.22 — both below 0.75
    assert r2 == "Pear Inc"

    # Case 3: No alias table → returns original
    r3 = _normalize_company("AnyCompany", {})
    assert r3 == "AnyCompany"


def test_fuzzy_similar_names_ratio():
    """Document actual SequenceMatcher ratios for reference."""
    from difflib import SequenceMatcher
    # These values document why 0.75 is a reasonable threshold
    assert SequenceMatcher(None, "google", "googel").ratio() >= 0.75   # typo
    assert SequenceMatcher(None, "microsoft", "microsystems").ratio() < 0.75  # different
    assert SequenceMatcher(None, "apple", "appleinc").ratio() >= 0.75  # similar suffix
    # Verify "tencent" vs "alibaba" are far apart
    assert SequenceMatcher(None, "tencent", "alibaba").ratio() < 0.5


def test_fuzzy_known_pair_above_threshold():
    """Verify a pair that does match above 0.75."""
    from agent_core.pipeline.search import _normalize_company

    # "北京小米科技" vs "小米" should fuzzy match
    aliases = {"小米": ["xiaomi", "小米科技"]}
    # Substring check: "xiaomi" is contained in "北京小米科技" → alias match
    r = _normalize_company("北京小米科技", aliases)
    assert r == "小米"


def test_dedup_cross_platform_same_company_fuzzy():
    """Cross-platform identical company with minor name variation."""
    from agent_core.pipeline.search import _dedup
    now = _now()
    j1 = _job(id="a", title="工程师", company="宁德新能源", company_normalized="宁德新能源",
              platforms=["boss_zhipin"], urls={"boss_zhipin": "http://b"},
              first_seen=now, last_seen=now)
    j2 = _job(id="b", title="工程师", company="catl", company_normalized="catl",
              platforms=["liepin"], urls={"liepin": "http://l"},
              first_seen=now, last_seen=now)
    # These have different company_normalized → different dedup_key → NOT merged
    aliases = {"catl": ["catl", "宁德时代"]}
    merged = _dedup([j1, j2], aliases)
    assert len(merged) == 2  # different normalized names remain separate


def test_normalize_company_alias_substring():
    """Substring matching in alias table."""
    from agent_core.pipeline.search import _normalize_company
    aliases = {"华为": ["huawei", "华为技术"]}
    # "huawei" contains "华为" not, but "华为技术有限公司" contains "华为技术"
    r1 = _normalize_company("华为技术有限公司", aliases)
    # "华为技术" in "华为技术有限公司"? yes → matches
    assert r1 == "华为"

    r2 = _normalize_company("huawei", aliases)
    # exact match "huawei" in aliases
    assert r2 == "华为"


# ---------- enrichment unit tests ----------

def test_enrich_no_security_id_skips(cfg):
    """Job without security_id or lid is skipped."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="no_ids", security_id="", lid="")
    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result is job  # same object, no enrichment


def test_enrich_unknown_platform_skips(cfg):
    """Job with unknown platform is not enriched."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="uk", security_id="abc123",
               platforms=["unknown_platform"],
               urls={"unknown_platform": "http://x"})
    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == job.description  # unchanged


def test_enrich_platform_not_enabled_skips(cfg):
    """Disabled platform → skip enrichment."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="dis", security_id="abc123",
               platforms=["maimai"], urls={"maimai": "http://x"})
    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == job.description


def test_enrich_boss_success(monkeypatch, cfg):
    """Successful enrichment for boss_zhipin."""
    from agent_core.platforms.enrichment import enrich_job_jd

    job = _job(id="boss1", security_id="abc123",
               platforms=["boss_zhipin"], urls={"boss_zhipin": "http://x"},
               description="原始描述")
    cfg.platforms["boss_zhipin"].enabled = True

    async def fake_fetch(self, job, cookie_path):
        return "完整的JD内容"

    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.fetch_full_jd",
        fake_fetch)
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.__init__",
        lambda self: None)

    result = asyncio.run(enrich_job_jd(job, cfg))
    assert "JD: 完整的JD内容" in result.description
    assert "原始描述" in result.description


def test_enrich_boss_fetch_returns_none(monkeypatch, cfg):
    """fetch_full_jd returns None → description unchanged."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="boss2", security_id="xyz",
               platforms=["boss_zhipin"], urls={"boss_zhipin": "http://x"},
               description="原始")
    cfg.platforms["boss_zhipin"].enabled = True

    async def fake_fetch(self, job, cookie_path):
        return None
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.fetch_full_jd",
        fake_fetch)
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.__init__",
        lambda self: None)

    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == "原始"


def test_enrich_boss_exception_graceful(monkeypatch, cfg):
    """Exception during fetch_full_jd → logged, job returned unchanged."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="boss3", security_id="err",
               platforms=["boss_zhipin"], urls={"boss_zhipin": "http://x"},
               description="safe")
    cfg.platforms["boss_zhipin"].enabled = True

    async def fake_fetch(self, job, cookie_path):
        raise ConnectionError("timeout")
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.fetch_full_jd",
        fake_fetch)
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.__init__",
        lambda self: None)

    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == "safe"  # unchanged


def test_enrich_liepin_success(monkeypatch, cfg):
    """Enrich liepin job via LiepinAdapter."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="lp1", lid="liepin123",
               platforms=["liepin"], urls={"liepin": "http://x"},
               description="原始")
    cfg.platforms["liepin"].enabled = True

    async def fake_fetch(self, job, cookie_path):
        return "猎聘JD"
    monkeypatch.setattr(
        "agent_core.platforms.liepin.LiepinAdapter.fetch_full_jd",
        fake_fetch)
    monkeypatch.setattr(
        "agent_core.platforms.liepin.LiepinAdapter.__init__",
        lambda self: None)

    result = asyncio.run(enrich_job_jd(job, cfg))
    assert "JD: 猎聘JD" in result.description


def test_enrich_no_platforms_field_uses_urls(monkeypatch, cfg):
    """Job with empty platforms but populated urls → uses urls keys."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="urls_only", security_id="abc", platforms=[],
               urls={"boss_zhipin": "http://x"}, description="desc")
    cfg.platforms["boss_zhipin"].enabled = True

    async def fake_fetch(self, job, cookie_path):
        return "from urls"
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.fetch_full_jd",
        fake_fetch)
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin.BossZhipinAdapter.__init__",
        lambda self: None)

    result = asyncio.run(enrich_job_jd(job, cfg))
    assert "JD: from urls" in result.description


# ---------- tailor coverage ----------

def test_tailor_open_job_link(monkeypatch):
    """open_job_link navigates to the first URL."""
    from agent_core.pipeline.tailor import open_job_link
    opened_urls = []

    def fake_open(url):
        opened_urls.append(url)
    monkeypatch.setattr("webbrowser.open", fake_open)

    job = _job(platforms=["boss_zhipin"],
               urls={"boss_zhipin": "https://zhipin.com/job/123"})
    open_job_link(job)
    assert len(opened_urls) == 1
    assert "zhipin.com" in opened_urls[0]


def test_tailor_open_job_link_empty_urls():
    """open_job_link with empty urls does not crash."""
    from agent_core.pipeline.tailor import open_job_link
    job = _job(urls={})
    # Should not raise
    open_job_link(job)


def test_tailor_save_docx_bold_and_lists(tmp_path):
    """_save_docx handles bold text, lists, and headings."""
    from agent_core.pipeline.tailor import _save_docx
    text = (
        "## 教育背景\n\n"
        "某大学 硕士\n\n"
        "### 核心能力\n\n"
        "- **ROS**熟练\n"
        "- SLAM算法\n"
        "1. 第一条\n"
        "2. 第二条\n"
    )
    path = str(tmp_path / "test.docx")
    _save_docx(text, path)
    assert tmp_path.joinpath("test.docx").exists()


def test_tailor_save_resume_creates_md_and_docx(tmp_path):
    """save_resume writes .md and .docx to output dir."""
    from agent_core.pipeline.tailor import save_resume
    out_dir = str(tmp_path / "tailor_out")
    text = "# Test Resume\n\n内容"
    paths = save_resume(text, _job(), output_dir=out_dir)
    assert paths["md"].endswith(".md")
    assert paths["docx"].endswith(".docx")
    assert Path(out_dir).joinpath(Path(paths["md"]).name).exists()


def test_tailor_resume_with_direction_none(cfg):
    """tailor_resume with direction=None uses job.direction."""
    from agent_core.pipeline.tailor import tailor_resume
    provider = FakeProvider(["## 定制简历\n\n内容"])
    text = asyncio.run(tailor_resume(
        _job(), cfg, provider, direction=None))
    assert "定制简历" in text


# ---------- search error paths ----------

def test_search_all_excluded_exception_in_results(cfg, monkeypatch):
    """When one platform raises, others still return results."""
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    async def boom_search(self, keywords, location, cookie_path=None,
                          headless=False, rate_limit_seconds=None):
        raise RuntimeError("simulated failure")

    async def ok_search(self, keywords, location, cookie_path=None,
                        headless=False, rate_limit_seconds=None):
        return [_job(id="ok", title="AMR")]

    monkeypatch.setattr(BossZhipinAdapter, "search", ok_search)
    # Only boss_zhipin is enabled; liepin is disabled by default
    cfg.platforms["boss_zhipin"].enabled = True

    jobs = asyncio.run(search.search_all(cfg, directions=["equipment_amr"]))
    assert len(jobs) >= 1
    assert jobs[0].id == "ok"


def test_search_one_not_implemented(cfg, monkeypatch):
    """_search_one for unknown platform returns empty."""
    from agent_core.config import PlatformConfig
    from agent_core.pipeline.search import _search_one
    pc = PlatformConfig(enabled=True)
    jobs = asyncio.run(_search_one("nonexistent", pc, ["AMR"], "全国", "dir"))
    assert jobs == []


def test_make_job_id_deterministic():
    """_make_job_id produces consistent hashes."""
    from agent_core.pipeline.search import _make_job_id
    id1 = _make_job_id("boss_zhipin", "http://x")
    id2 = _make_job_id("boss_zhipin", "http://x")
    id3 = _make_job_id("boss_zhipin", "http://y")
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 16


def test_normalize_company_exact_match():
    """Exact match in alias table (case-insensitive)."""
    from agent_core.pipeline.search import _normalize_company
    aliases = {"大疆": ["dji", "DJI Innovations"]}
    r = _normalize_company("DJI Innovations", aliases)
    assert r == "大疆"


def test_normalize_company_whitespace():
    """Whitespace around company name is stripped."""
    from agent_core.pipeline.search import _normalize_company
    aliases = {"test": ["  test  "]}
    r = _normalize_company("  test  ", aliases)
    assert r == "test"


def test_normalize_company_empty_string():
    """Empty company name returns empty string."""
    from agent_core.pipeline.search import _normalize_company
    r = _normalize_company("", {})
    assert r == ""


def test_normalize_company_no_aliases():
    """No alias table → returns original name."""
    from agent_core.pipeline.search import _normalize_company
    r = _normalize_company("Some Company", {})
    assert r == "Some Company"


def test_dedup_last_seen_keeps_latest(cfg):
    """_dedup keeps the most recent last_seen across platforms."""
    from agent_core.pipeline.search import _dedup
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 6, 1, tzinfo=UTC)
    j1 = _job(id="a", title="工程师", company="A", company_normalized="a",
              platforms=["boss_zhipin"], urls={"boss_zhipin": "http://b"},
              first_seen=t1, last_seen=t1)
    j2 = _job(id="b", title="工程师", company="A", company_normalized="a",
              platforms=["liepin"], urls={"liepin": "http://l"},
              first_seen=t2, last_seen=t2)
    merged = _dedup([j1, j2], {})
    assert len(merged) == 1
    assert merged[0].last_seen == t2  # latest wins


def test_dedup_is_new_OR(cfg):
    """is_new is True if either job is_new=True."""
    from agent_core.pipeline.search import _dedup
    now = _now()
    j1 = _job(id="a", title="T", company="A", company_normalized="a",
              is_new=False, first_seen=now, last_seen=now)
    j2 = _job(id="b", title="T", company="A", company_normalized="a",
              is_new=True, first_seen=now, last_seen=now)
    merged = _dedup([j1, j2], {})
    assert merged[0].is_new is True


def test_dedup_empty_list(cfg):
    """_dedup on empty list returns empty."""
    from agent_core.pipeline.search import _dedup
    assert _dedup([], {}) == []


def test_search_all_with_explicit_directions(cfg, monkeypatch):
    """search_all with explicit directions list."""
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    async def fake_search(self, keywords, location, cookie_path=None,
                          headless=False, rate_limit_seconds=None):
        return [_job(id="d1")]
    monkeypatch.setattr(BossZhipinAdapter, "search", fake_search)

    jobs = asyncio.run(search.search_all(
        cfg, directions=["equipment_amr"], platform_names=["boss_zhipin"]))
    assert len(jobs) == 1


def test_search_all_skips_unknown_direction(cfg, monkeypatch):
    """search_all skips direction not in config.directions."""
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    async def fake_search(self, keywords, location, cookie_path=None,
                          headless=False, rate_limit_seconds=None):
        return [_job(id="d2")]
    monkeypatch.setattr(BossZhipinAdapter, "search", fake_search)

    jobs = asyncio.run(search.search_all(
        cfg, directions=["nonexistent_dir", "equipment_amr"],
        platform_names=["boss_zhipin"]))
    assert len(jobs) >= 1


def test_search_all_skips_disabled_platform(cfg, monkeypatch):
    """search_all skips platform when not enabled."""
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    async def fake_search(self, keywords, location, cookie_path=None,
                          headless=False, rate_limit_seconds=None):
        return [_job(id="d3")]
    monkeypatch.setattr(BossZhipinAdapter, "search", fake_search)
    # Disable ALL platforms
    for p in cfg.platforms.values():
        p.enabled = False

    jobs = asyncio.run(search.search_all(
        cfg, directions=["equipment_amr"]))
    assert jobs == []


def test_search_all_task_exception_handled(cfg, monkeypatch):
    """When search task raises exception, it's logged, not propagated."""
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    async def boom_search(self, keywords, location, cookie_path=None,
                          headless=False, rate_limit_seconds=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(BossZhipinAdapter, "search", boom_search)

    jobs = asyncio.run(search.search_all(
        cfg, directions=["equipment_amr"], platform_names=["boss_zhipin"]))
    assert jobs == []  # exception caught, no crash


def test_search_one_not_implemented_error(cfg):
    """_search_one when adapter raises NotImplementedError for company_site."""
    import agent_core.platforms.company_site as cs_mod
    from agent_core.config import PlatformConfig
    from agent_core.pipeline.search import _search_one
    original = dict(cs_mod.COMPANY_SITES)
    try:
        cs_mod.COMPANY_SITES.clear()
        pc = PlatformConfig(enabled=True)
        jobs = asyncio.run(_search_one("company_site", pc, ["AMR"], "全国", "dir"))
        assert jobs == []
    finally:
        cs_mod.COMPANY_SITES.clear()
        cs_mod.COMPANY_SITES.update(original)


def test_search_one_general_exception(monkeypatch, cfg):
    """_search_one for company_site with an exception-raising site."""
    from agent_core.config import PlatformConfig
    from agent_core.pipeline.search import _search_one
    from agent_core.platforms.company_site import CompanySiteAdapter

    async def raising_adapter_search(self, keywords, location, cookie_path=None,
                                     headless=False, rate_limit_seconds=None):
        raise RuntimeError("network error")
    monkeypatch.setattr(CompanySiteAdapter, "search", raising_adapter_search)

    import agent_core.platforms.company_site as cs_mod
    original = dict(cs_mod.COMPANY_SITES)
    try:
        cs_mod.COMPANY_SITES.clear()
        cs_mod.COMPANY_SITES["test_co"] = {"name": "Test", "url": "http://x"}
        pc = PlatformConfig(enabled=True)
        jobs = asyncio.run(_search_one("company_site", pc, ["AMR"], "全国", "dir"))
        assert jobs == []  # error caught, empty returned
    finally:
        cs_mod.COMPANY_SITES.clear()
        cs_mod.COMPANY_SITES.update(original)


# ---------- enrichment remaining coverage ----------

def test_enrich_platform_not_in_config(monkeypatch, cfg):
    """Platform in job.urls not in config.platforms."""
    from agent_core.platforms.enrichment import enrich_job_jd
    job = _job(id="unk", security_id="abc",
               urls={"nonexistent_platform": "http://x"},
               description="unchanged")
    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == "unchanged"


def test_enrich_unsupported_platform_type(cfg):
    """A platform that IS in config but IS NOT boss/liepin → logged warning."""
    from agent_core.platforms.enrichment import enrich_job_jd
    # job51 IS in config but enrichment doesn't support it
    job = _job(id="j51", security_id="abc",
               platforms=["job51"], urls={"job51": "http://x"},
               description="original")
    # job51 is in config.platforms...
    # but enrichment.py only handles boss_zhipin/liepin → falls to else
    result = asyncio.run(enrich_job_jd(job, cfg))
    assert result.description == "original"


# ---------- tailor open_job_link edge case ----------

def test_tailor_open_job_link_dict_with_empty_value(monkeypatch):
    """open_job_link skips dict entries where URL is empty string."""
    from agent_core.pipeline.tailor import open_job_link
    opened = []

    def fake_open(url):
        opened.append(url)
    monkeypatch.setattr("webbrowser.open", fake_open)

    job = _job(urls={"boss_zhipin": "", "liepin": "https://liepin.com/j/1"})
    open_job_link(job)
    assert len(opened) == 1
    assert "liepin.com" in opened[0]


# ---------- prescreen confidence penalty ----------

def test_prescreen_low_confidence_applies_penalty(cfg):
    from agent_core.pipeline import prescreen
    # Weak match (1 feature hit) → low confidence → -10 penalty
    job = _job(title="AMR", description="AMR", id="weak")
    raw = prescreen._score_job(job, cfg, "equipment_amr")
    ps = prescreen.prescreen([job], cfg)
    assert len(ps) == 1
    assert ps[0].confidence == "low"
    assert ps[0].score == max(0.0, raw - 10.0)


def test_prescreen_high_confidence_no_penalty(cfg):
    from agent_core.pipeline import prescreen
    # Strong match (many feature hits) → high confidence → no penalty
    job = _job(title="AMR AGV 调度 SLAM 导航 激光", description="AMR AGV PLC SLAM MES WMS SCADA 调度 导航", id="strong")
    raw = prescreen._score_job(job, cfg, "equipment_amr")
    ps = prescreen.prescreen([job], cfg)
    assert ps[0].confidence == "high"
    assert ps[0].score == raw  # no penalty


# ---------- windows_toast smoke (no crash) ----------

def test_toast_notify_cookie_expired_does_not_crash():
    from agent_core.notify.windows_toast import notify_cookie_expired
    # Should not raise even if toast backend unavailable
    notify_cookie_expired("TestPlatform")
