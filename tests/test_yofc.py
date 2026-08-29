"""Tests for YOFC (长飞光纤) adapter: response parsing, field mapping."""

import asyncio
import json

from agent_core.platforms.yofc import YofcAdapter

# ── _api_item_to_job tests ──


def make_yofc_item(
    job_ad_name="海外销售代表",
    job_ad_id="390596137",
    category="社会招聘",
    loc_names=None,
    duty="1. 负责海外市场光纤光缆产品销售",
    require="1. 本科学历，通信或市场营销专业",
    degree=None,
    years_of_working=None,
    change_date="2026-06-10T16:24:18",
    item_id="abc-def-123",
):
    return {
        "Id": item_id,
        "JobAdId": job_ad_id,
        "JobAdName": job_ad_name,
        "Category": category,
        "LocNames": loc_names if loc_names is not None else [],
        "Duty": duty,
        "Require": require,
        "ChangeDate": change_date,
        "Salary": None,
        "Degree": degree,
        "YearsOfWorking": years_of_working,
        "OrgId": 1703263,
    }


def test_item_to_job_basic():
    adapter = YofcAdapter()
    item = make_yofc_item()
    job = adapter._api_item_to_job(item)

    assert job.title == "海外销售代表"
    assert job.company == "长飞光纤"
    assert "社会招聘" in job.description
    assert "岗位职责" in job.description
    assert "海外市场光纤光缆产品销售" in job.description
    assert "任职要求" in job.description
    assert "本科学历" in job.description
    assert "yofc" in job.urls
    assert job.security_id == "390596137"


def test_item_to_job_with_location():
    """When LocNames has values, use them for location."""
    adapter = YofcAdapter()
    item = make_yofc_item(loc_names=["武汉市", "东湖高新区"])
    job = adapter._api_item_to_job(item)
    assert "武汉" in job.location
    assert "东湖" in job.location


def test_item_to_job_empty_location():
    """LocNames is often empty for social recruitment."""
    adapter = YofcAdapter()
    item = make_yofc_item(loc_names=[])
    job = adapter._api_item_to_job(item)
    assert job.location == ""


def test_item_to_job_string_location():
    """Handle LocNames as a single string."""
    adapter = YofcAdapter()
    item = make_yofc_item(loc_names="武汉")
    job = adapter._api_item_to_job(item)
    assert job.location == "武汉"


def test_item_to_job_none_location():
    adapter = YofcAdapter()
    item = make_yofc_item(loc_names=None)
    job = adapter._api_item_to_job(item)
    assert job.location == ""


def test_item_to_job_no_salary():
    """YOFC list API Salary is usually None."""
    adapter = YofcAdapter()
    item = make_yofc_item()
    job = adapter._api_item_to_job(item)
    assert job.salary_min is None
    assert job.salary_max is None


def test_item_to_job_with_degree_and_years():
    """When Degree and YearsOfWorking are present, include in description."""
    adapter = YofcAdapter()
    item = make_yofc_item(degree="本科", years_of_working="1-3年")
    job = adapter._api_item_to_job(item)
    assert "学历: 本科" in job.description
    assert "经验: 1-3年" in job.description


def test_item_to_job_without_duty():
    """Handle missing Duty field."""
    adapter = YofcAdapter()
    item = make_yofc_item(duty="")
    job = adapter._api_item_to_job(item)
    # Should still have require section
    assert "任职要求" in job.description
    # But no duties section
    assert "岗位职责" not in job.description


def test_item_to_job_url_contains_item_id():
    adapter = YofcAdapter()
    item = make_yofc_item(item_id="test-id-456")
    job = adapter._api_item_to_job(item)
    assert "test-id-456" in job.urls.get("yofc", "")


def test_item_to_job_empty_url():
    adapter = YofcAdapter()
    item = make_yofc_item(item_id="")
    job = adapter._api_item_to_job(item)
    assert job.urls.get("yofc", "") == ""


# ── normalize tests ──


def test_normalize():
    adapter = YofcAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "长飞光纤",
            "location": "武汉",
            "salary_min": None,
            "salary_max": None,
            "description": "测试描述",
            "url": "https://yofccampus.zhiye.com/campus/position/123",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "yofc" in job.platforms


# ── Search tests with mock ──


def make_yofc_resp(*items):
    """Build a fake YOFC API response."""
    return json.dumps(
        {
            "Code": 200,
            "Message": "operation success",
            "Count": len(items),
            "Data": list(items),
        }
    ).encode()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_search_parses_list(monkeypatch):
    """Search should parse results from YOFC API."""

    item = make_yofc_item(
        job_ad_name="技术支持工程师",
        job_ad_id="390596138",
        loc_names=["武汉市"],
    )

    api_bytes = make_yofc_resp(item)

    def fake_urlopen(req, timeout=20, context=None):
        return _FakeResp(api_bytes)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = YofcAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["技术"],
            location="武汉",
            rate_limit_seconds=0,
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "技术支持工程师"
    assert jobs[0].company == "长飞光纤"


def test_search_api_error_returns_empty(monkeypatch):
    """HTTP error should return empty list."""
    import urllib.error

    def fake_urlopen(req, timeout=20, context=None):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = YofcAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["技术"],
            location="武汉",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_search_non_200_code(monkeypatch):
    """Non-200 Code should return empty."""
    resp = json.dumps({"Code": 500, "Message": "error", "Count": 0, "Data": []}).encode()

    def fake_urlopen(req, timeout=20, context=None):
        return _FakeResp(resp)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = YofcAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["技术"],
            location="武汉",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_rate_limit_default():
    adapter = YofcAdapter()
    assert adapter._rate_limit_seconds == 1.0


def test_rate_limit_custom():
    adapter = YofcAdapter(rate_limit_seconds=2.5)
    assert adapter._rate_limit_seconds == 2.5


def test_adapter_name():
    adapter = YofcAdapter()
    assert adapter.name == "yofc"
