"""Tests for NetEase HR adapter: response parsing, field mapping."""

import asyncio
import json

from agent_core.platforms.netease import NeteaseAdapter

# ── _api_item_to_job tests ──


def make_netease_item(
    item_id=75177,
    name="资深技术美术（AI Agent开发）",
    first_dep_name="艺设一部",
    work_place_names=None,
    req_education="本科",
    req_work_years="不限",
    first_post_type="游戏艺术",
    recruit_num=1,
    description="Responsible for AI pipeline development.",
    requirement="Python, Blender, ComfyUI.",
    product_name="网易游戏（互娱）",
    bee_url="https://hr.163.com/job/75177",
):
    return {
        "id": item_id,
        "name": name,
        "workType": "0",
        "firstPostTypeName": first_post_type,
        "recruitNum": recruit_num,
        "requirement": requirement,
        "description": description,
        "reqEducationName": req_education,
        "reqWorkYearsName": req_work_years,
        "firstDepName": first_dep_name,
        "workPlaceNameList": work_place_names or ["广州市"],
        "updateTime": 1781508323000,
        "productName": product_name,
        "beeUrl": bee_url,
    }


def test_item_to_job_basic():
    adapter = NeteaseAdapter()
    item = make_netease_item()
    job = adapter._api_item_to_job(item)

    assert job.title == "资深技术美术（AI Agent开发）"
    assert job.company == "网易"
    assert "广州市" in job.location
    assert "学历: 本科" in job.description
    assert "艺设一部" in job.description
    assert "Responsible for AI pipeline development" in job.description
    assert "netease" in job.urls
    assert job.security_id == "75177"


def test_item_to_job_multiple_locations():
    adapter = NeteaseAdapter()
    item = make_netease_item(work_place_names=["北京市", "杭州市"])
    job = adapter._api_item_to_job(item)
    assert "北京" in job.location
    assert "杭州" in job.location


def test_item_to_job_no_salary():
    """NetEase list API doesn't include salary."""
    adapter = NeteaseAdapter()
    item = make_netease_item()
    job = adapter._api_item_to_job(item)
    assert job.salary_min is None
    assert job.salary_max is None


def test_item_to_job_fallback_url():
    """When beeUrl is None, construct from id."""
    adapter = NeteaseAdapter()
    item = make_netease_item(bee_url=None, item_id=99999)
    job = adapter._api_item_to_job(item)
    assert "99999" in job.urls.get("netease", "")


def test_item_to_job_with_recruit_num():
    adapter = NeteaseAdapter()
    item = make_netease_item(recruit_num=5)
    job = adapter._api_item_to_job(item)
    assert "5" in job.description


def test_item_to_job_education_not_unlimited():
    """Only show education when not '不限'."""
    adapter = NeteaseAdapter()
    item = make_netease_item(req_education="硕士")
    job = adapter._api_item_to_job(item)
    assert "学历: 硕士" in job.description


def test_item_to_job_empty_education():
    """Don't show education if '不限'."""
    adapter = NeteaseAdapter()
    item = make_netease_item(req_education="不限")
    job = adapter._api_item_to_job(item)
    assert "学历:" not in job.description


# ── normalize tests ──


def test_normalize():
    adapter = NeteaseAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "网易",
            "location": "广州",
            "salary_min": None,
            "salary_max": None,
            "description": "测试描述",
            "url": "https://hr.163.com/job/123",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "netease" in job.platforms


# ── Search tests with mock ──


def make_netease_resp(*items):
    """Build a fake NetEase API response."""
    return json.dumps(
        {
            "code": 200,
            "data": {
                "total": len(items),
                "pages": 1,
                "lastPage": False,
                "list": list(items),
            },
        }
    ).encode()


def test_search_parses_list(monkeypatch):
    """Search should parse results from NetEase API."""
    item = make_netease_item(
        name="Python工程师",
        first_dep_name="技术部",
    )

    class FakeResp:
        def read(self):
            return make_netease_resp(item)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = NeteaseAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="广州",
            rate_limit_seconds=0,
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Python工程师"
    assert jobs[0].company == "网易"


def test_search_api_error_returns_empty(monkeypatch):
    """HTTP error should return empty list."""
    import urllib.error

    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = NeteaseAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="广州",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_rate_limit_default():
    adapter = NeteaseAdapter()
    assert adapter._rate_limit_seconds == 1.0


def test_rate_limit_custom():
    adapter = NeteaseAdapter(rate_limit_seconds=2.5)
    assert adapter._rate_limit_seconds == 2.5


def test_adapter_name():
    adapter = NeteaseAdapter()
    assert adapter.name == "netease"
