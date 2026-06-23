"""Tests for BYD adapter: response parsing, field mapping."""

import asyncio
import json

from agent_core.platforms.byd import BydAdapter

# ── _api_item_to_job tests ──


def make_byd_item(
    position_name="高级算法工程师",
    position_code="20368286",
    province="广东省",
    city="深圳市",
    father_org="电子事业群",
    org="研究院",
    people_num=2,
    detail="<p>负责AI算法研发</p>",
):
    return {
        "positionName": position_name,
        "positionCode": position_code,
        "province": province,
        "city": city,
        "fatherOrgAliasName": father_org,
        "orgAliasName": org,
        "peopleNumLimit": people_num,
        "detail": detail,
        "positionTypeId": "01",
        "createTime": "2026-06-22 18:14:02",
        "divisionCode": "DIV001",
    }


def test_item_to_job_basic():
    adapter = BydAdapter()
    item = make_byd_item()
    job = adapter._api_item_to_job(item)

    assert job.title == "高级算法工程师"
    assert job.company == "比亚迪"
    assert "深圳" in job.location
    assert "广东" in job.location
    assert "电子事业群" in job.description
    assert "研究院" in job.description
    assert "AI算法研发" in job.description
    assert "byd" in job.urls
    assert job.security_id == "20368286"


def test_item_to_job_city_only():
    """When province is empty, show city only."""
    adapter = BydAdapter()
    item = make_byd_item(province="", city="北京市")
    job = adapter._api_item_to_job(item)
    assert job.location == "北京市"


def test_item_to_job_province_only():
    """When city is empty, show province only."""
    adapter = BydAdapter()
    item = make_byd_item(province="广东省", city="")
    job = adapter._api_item_to_job(item)
    assert job.location == "广东省"


def test_item_to_job_no_location():
    adapter = BydAdapter()
    item = make_byd_item(province="", city="")
    job = adapter._api_item_to_job(item)
    assert job.location == ""


def test_item_to_job_no_salary():
    """BYD list API doesn't include salary — verify None."""
    adapter = BydAdapter()
    item = make_byd_item()
    job = adapter._api_item_to_job(item)
    assert job.salary_min is None
    assert job.salary_max is None


def test_item_to_job_url_contains_position_code():
    adapter = BydAdapter()
    item = make_byd_item(position_code="99999")
    job = adapter._api_item_to_job(item)
    assert "99999" in job.urls.get("byd", "")


def test_item_to_job_people_count():
    adapter = BydAdapter()
    item = make_byd_item(people_num=5)
    job = adapter._api_item_to_job(item)
    assert "5" in job.description


def test_item_to_job_empty_detail():
    """When detail is empty, don't add blank lines."""
    adapter = BydAdapter()
    item = make_byd_item(detail="")
    job = adapter._api_item_to_job(item)
    # Should still have org info but no blank detail section
    assert "事业群" in job.description


# ── normalize tests ──


def test_normalize():
    adapter = BydAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "比亚迪",
            "location": "深圳",
            "salary_min": None,
            "salary_max": None,
            "description": "测试描述",
            "url": "https://job.byd.com/123",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "byd" in job.platforms


# ── Search tests with mock ──


def make_byd_items(*items):
    """Build a fake BYD API response. Note: BYD uses code=0 for success."""
    return json.dumps(
        {
            "code": 0,
            "msg": "查询成功",
            "data": {
                "total": len(items),
                "data": list(items),
            },
        }
    ).encode()


def test_search_parses_list(monkeypatch):
    """Search should parse results from BYD API."""

    item = make_byd_item(
        position_name="AI工程师",
        city="深圳市",
    )

    class FakeResp:
        def read(self):
            return make_byd_items(item)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20, context=None):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BydAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "AI工程师"
    assert jobs[0].company == "比亚迪"


def test_search_api_error_returns_empty(monkeypatch):
    """HTTP error should return empty list."""
    import urllib.error

    def fake_urlopen(req, timeout=20, context=None):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BydAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_search_non_zero_code(monkeypatch):
    """Non-zero code (BYD uses 0 for success) should return empty."""
    resp = json.dumps({"code": -1, "msg": "error", "data": {"total": 0, "data": []}}).encode()

    class FakeResp:
        def read(self):
            return resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20, context=None):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BydAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_rate_limit_default():
    adapter = BydAdapter()
    assert adapter._rate_limit_seconds == 1.0


def test_rate_limit_custom():
    adapter = BydAdapter(rate_limit_seconds=2.5)
    assert adapter._rate_limit_seconds == 2.5


def test_adapter_name():
    adapter = BydAdapter()
    assert adapter.name == "byd"
