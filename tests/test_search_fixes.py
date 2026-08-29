"""Regression tests for the 2026-08-16 search-code audit fixes."""

import asyncio
from datetime import UTC, datetime

from agent_core.config import load_config
from agent_core.platforms.base import Job, parse_salary_text


def _now():
    return datetime.now(UTC)


def _job(**kw):
    defaults = dict(
        id="x",
        title="AMR工程师",
        company="A公司",
        company_normalized="A公司",
        location="苏州",
        salary_min=10000,
        salary_max=15000,
        description="岗位职责：AMR 调度",
        direction="user_query",
        platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"},
        first_seen=_now(),
        last_seen=_now(),
    )
    defaults.update(kw)
    return Job(**defaults)


# ---- B2 shared relevance guard ----


def test_filter_by_keywords_exact_and_chinese_overlap():
    from agent_core.pipeline.search import filter_by_keywords

    jobs = [
        _job(id="1", title="AMR工程师"),
        _job(id="2", title="设备维护工程师"),
        _job(id="3", title="销售经理"),
    ]
    assert [j.id for j in filter_by_keywords(jobs, ["设备工程师"])] == ["2"]
    assert [j.id for j in filter_by_keywords(jobs, ["AMR"])] == ["1"]


def test_filter_by_keywords_english_requires_full_substring():
    from agent_core.pipeline.search import filter_by_keywords

    jobs = [_job(id="1", title="AMR工程师"), _job(id="2", title="ARM工程师")]
    assert [j.id for j in filter_by_keywords(jobs, ["AMR"])] == ["1"]


def test_search_all_applies_relevance_guard(monkeypatch):
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    cfg = load_config("config.yaml")

    async def fake_boss_search(
        self, keywords, location, cookie_path=None, headless=False, rate_limit_seconds=None
    ):
        return [
            _job(id="ok", title="AMR工程师", platforms=["boss_zhipin"]),
            _job(id="bad", title="销售经理", platforms=["boss_zhipin"]),
        ]

    monkeypatch.setattr(BossZhipinAdapter, "search", fake_boss_search)
    jobs = asyncio.run(search.search_all(cfg, ["boss_zhipin"], keywords=["AMR"]))
    assert [j.id for j in jobs] == ["ok"]


def test_resolve_platform_names_aliases():
    from agent_core.pipeline.search import resolve_platform_names

    cfg = load_config("config.yaml")
    known, unknown = resolve_platform_names(cfg, ["boss", "zl", "nope", "zl"])
    assert known == ["boss_zhipin", "zhilian"]
    assert unknown == ["nope"]


# ---- B1 dedup field merge ----


def test_dedup_merges_salary_and_description():
    from agent_core.pipeline.search import _dedup

    j1 = _job(
        id="a",
        title="设备工程师",
        salary_min=None,
        salary_max=None,
        description="短描述",
        location="",
    )
    j2 = _job(
        id="b",
        title="设备工程师",
        salary_min=12000,
        salary_max=18000,
        description="JD: 完整岗位职责\n任职要求：本科",
        location="苏州",
        platforms=["liepin"],
        urls={"liepin": "http://y"},
    )
    merged = _dedup([j1, j2], {})
    assert len(merged) == 1
    m = merged[0]
    assert m.salary_min == 12000
    assert m.salary_max == 18000
    assert m.description.startswith("JD:")
    assert m.location == "苏州"
    assert set(m.platforms) == {"boss_zhipin", "liepin"}


# ---- defect 1: job upsert preserves manual state ----


def test_save_jobs_preserves_user_flag_and_jd(monkeypatch, tmp_path):
    from agent_core.pipeline import orchestrator
    from agent_core.storage.db import get_db, migrate

    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO jobs "
        "(id,title,company,company_normalized,location,description,platforms,urls,"
        "direction,first_seen,last_seen,is_new,user_flag) "
        "VALUES ('j1','设备工程师','A','A','苏州','JD: 完整岗位职责','[]','{}',"
        "'default','2026-01-01','2026-01-01',1,'interested')"
    )
    conn.commit()
    conn.close()

    job = _job(
        id="j1",
        title="设备工程师",
        description="短描述",
        is_new=False,
    )
    saved = orchestrator._save_jobs_to_db([job], db_path=db_path)
    assert saved == 1

    conn = get_db(db_path)
    row = conn.execute(
        "SELECT user_flag, description, is_new, first_seen FROM jobs WHERE id='j1'"
    ).fetchone()
    conn.close()
    assert row["user_flag"] == "interested"
    assert row["description"] == "JD: 完整岗位职责"
    assert row["is_new"] == 0  # update of an existing row
    assert row["first_seen"] == "2026-01-01"


def test_save_jobs_new_row_marks_is_new(monkeypatch, tmp_path):
    from agent_core.pipeline import orchestrator
    from agent_core.storage.db import get_db, migrate

    db_path = str(tmp_path / "agent.db")
    conn = get_db(db_path)
    migrate(conn)
    conn.close()

    orchestrator._save_jobs_to_db([_job(id="new1")], db_path=db_path)
    conn = get_db(db_path)
    row = conn.execute("SELECT is_new FROM jobs WHERE id='new1'").fetchone()
    conn.close()
    assert row["is_new"] == 1


# ---- defect 2: config passthrough ----


def test_load_config_passes_search_max_pages_and_profile():
    cfg = load_config("config.yaml")
    assert cfg.platforms["boss_zhipin"].search_max_pages == 1
    assert cfg.platforms["tencent"].search_max_pages == 2
    assert cfg.platforms["zhilian"].browser_profile_dir == "data/zhilian_browser_profile"


# ---- defect 3: zhilian cookie health no longer reports missing file ----


def test_zhilian_cookie_check_uses_browser_mode():
    from agent_core.cookie_health import PLATFORM_SPECS, CookieStatus, _check_single_platform

    r = _check_single_platform(PLATFORM_SPECS["zhilian"])
    assert r.status == CookieStatus.UNVERIFIED
    assert "浏览器持久化登录" in r.details[0]


# ---- defect 4/5/6: education, salary, id fallback ----


def test_adapter_education_and_salary_fields():
    from agent_core.platforms.naura import NauraAdapter
    from agent_core.platforms.yofc import YofcAdapter

    n = NauraAdapter()._api_item_to_job(
        {"JobAdId": "n1", "JobAdName": "设备工程师", "Degree": "本科", "Salary": "15K-25K"}
    )
    assert n.education == "本科"
    assert (n.salary_min, n.salary_max) == (15000, 25000)

    y = YofcAdapter()._api_item_to_job(
        {"JobAdId": "y1", "JobAdName": "设备工程师", "Degree": "硕士", "Salary": "1.2万-1.8万"}
    )
    assert y.education == "硕士"
    assert (y.salary_min, y.salary_max) == (12000, 18000)


def test_adapter_id_fallback_is_title_based():
    from agent_core.platforms.netease import NeteaseAdapter

    a = NeteaseAdapter()._api_item_to_job(
        {"id": "", "name": "设备工程师", "workPlaceNameList": ["苏州"], "beeUrl": ""}
    )
    b = NeteaseAdapter()._api_item_to_job(
        {"id": "", "name": "软件工程师", "workPlaceNameList": ["苏州"], "beeUrl": ""}
    )
    assert a.id and b.id
    assert a.id != b.id


# ---- B6 unified salary parser ----


def test_parse_salary_text_unified():
    assert parse_salary_text("15K-25K") == (15000, 25000)
    assert parse_salary_text("8千-1.2万") == (8000, 12000)
    assert parse_salary_text("15000-25000") == (15000, 25000)
    assert parse_salary_text("15-20万/年") == (None, None)
    assert parse_salary_text("300-500元/天") == (None, None)


def test_tencent_location_china_only_city():
    from agent_core.platforms.tencent import TencentAdapter

    job = TencentAdapter()._api_item_to_job(
        {"PostId": 1, "RecruitPostName": "工程师", "CountryName": "中国", "LocationName": "深圳"}
    )
    assert job.location == "深圳"


def test_tencent_search_honors_max_pages(monkeypatch):
    import json as _json

    from agent_core.platforms.tencent import TencentAdapter

    payload = _json.dumps(
        {
            "Code": 200,
            "Data": {
                "Count": 1,
                "Posts": [
                    {
                        "PostId": 1,
                        "RecruitPostName": "AMR工程师",
                        "CountryName": "中国",
                        "LocationName": "苏州",
                        "Responsibility": "职责",
                    }
                ],
            },
        }
    ).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())

    async def fake_sleep(_s):
        pass

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    adapter = TencentAdapter(rate_limit_seconds=0, max_pages=2)
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "全国"))
    assert len(jobs) == 2


def test_liepin_search_honors_max_pages(monkeypatch):
    import json as _json

    from agent_core.platforms.liepin import LiepinAdapter

    payload = _json.dumps(
        {
            "flag": 1,
            "data": {
                "data": {
                    "jobCardList": [
                        {
                            "comp": {"compName": "A公司"},
                            "job": {
                                "title": "AMR工程师",
                                "jobId": "job1",
                                "salary": "15-20k",
                                "dq": "苏州",
                                "link": "https://www.liepin.com/a/1.shtml",
                            },
                            "recruiter": {},
                        }
                    ]
                }
            },
        }
    ).encode()

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())

    async def fake_sleep(_s):
        pass

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    adapter = LiepinAdapter(rate_limit_seconds=0, max_pages=2)
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "XSRF-TOKEN=x", 0))
    assert len(jobs) == 2
