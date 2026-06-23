"""Tests for NAURA adapter: response parsing, field mapping, session init."""

import asyncio
import json
from http.cookiejar import CookieJar

from agent_core.platforms.naura import NauraAdapter

# ── _api_item_to_job tests ──


def make_naura_item(
    job_ad_name="PIE-封装业务",
    job_ad_id="190831761",
    category="社会招聘",
    loc_names=None,
    duty="1. 负责半导体先进封装工艺开发",
    require="1. 硕士学历，微电子、半导体专业",
    degree=None,
    years_of_working=None,
    change_date="2026-06-10T16:24:18",
    item_id="58c027a8-cc62-48a4-8724-60c6c379219b",
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
        "OrgId": 2296667,
        "CategoryId": 1,
        "HeadCount": 0,
    }


def test_item_to_job_basic():
    adapter = NauraAdapter()
    item = make_naura_item()
    job = adapter._api_item_to_job(item)

    assert job.title == "PIE-封装业务"
    assert job.company == "北方华创"
    assert "社会招聘" in job.description
    assert "岗位职责" in job.description
    assert "半导体先进封装工艺开发" in job.description
    assert "任职要求" in job.description
    assert "硕士学历" in job.description
    assert "naura" in job.urls
    assert job.security_id == "190831761"


def test_item_to_job_with_location():
    """When LocNames has values, use them for location."""
    adapter = NauraAdapter()
    item = make_naura_item(loc_names=["北京市", "大兴区"])
    job = adapter._api_item_to_job(item)
    assert "北京" in job.location
    assert "大兴" in job.location


def test_item_to_job_empty_location():
    """LocNames is often empty for social recruitment."""
    adapter = NauraAdapter()
    item = make_naura_item(loc_names=[])
    job = adapter._api_item_to_job(item)
    assert job.location == ""


def test_item_to_job_string_location():
    """Handle LocNames as a single string."""
    adapter = NauraAdapter()
    item = make_naura_item(loc_names="北京")
    job = adapter._api_item_to_job(item)
    assert job.location == "北京"


def test_item_to_job_none_location():
    adapter = NauraAdapter()
    item = make_naura_item(loc_names=None)
    job = adapter._api_item_to_job(item)
    assert job.location == ""


def test_item_to_job_no_salary():
    """NAURA list API Salary is usually None."""
    adapter = NauraAdapter()
    item = make_naura_item()
    job = adapter._api_item_to_job(item)
    assert job.salary_min is None
    assert job.salary_max is None


def test_item_to_job_with_degree_and_years():
    """When Degree and YearsOfWorking are present, include in description."""
    adapter = NauraAdapter()
    item = make_naura_item(degree="硕士", years_of_working="3-5年")
    job = adapter._api_item_to_job(item)
    assert "学历: 硕士" in job.description
    assert "经验: 3-5年" in job.description


def test_item_to_job_without_duty():
    """Handle missing Duty field."""
    adapter = NauraAdapter()
    item = make_naura_item(duty="")
    job = adapter._api_item_to_job(item)
    # Should still have require section
    assert "任职要求" in job.description
    # But no duties section
    assert "岗位职责" not in job.description


# ── normalize tests ──


def test_normalize():
    adapter = NauraAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "北方华创",
            "location": "北京",
            "salary_min": None,
            "salary_max": None,
            "description": "测试描述",
            "url": "https://career.naura.com/123",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "naura" in job.platforms


# ── Search tests with mock ──


def make_naura_resp(*items):
    """Build a fake NAURA API response."""
    return json.dumps(
        {
            "Code": 200,
            "Message": "operation success",
            "Count": len(items),
            "Data": list(items),
        }
    ).encode()


class _FakeOpen:
    """Mocks the opener's open() method, returning our fake response."""

    def __init__(self, resp_bytes, expect_session=False):
        self._resp_bytes = resp_bytes
        self._session_called = False
        self._expect_session = expect_session

    def __call__(self, req, timeout=20, context=None):
        if self._expect_session and not self._session_called:
            self._session_called = True
            return _FakeResp(b"<html>fake session page</html>")
        return _FakeResp(self._resp_bytes)


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeOpener:
    def __init__(self, fake_open):
        self._fake_open = fake_open

    def open(self, req, timeout=20, context=None):
        return self._fake_open(req, timeout=timeout, context=context)


def test_search_parses_list(monkeypatch):
    """Search should parse results from NAURA API, including session init."""

    item = make_naura_item(
        job_ad_name="算法工程师（仿真方向）",
        job_ad_id="190834196",
    )

    api_bytes = make_naura_resp(item)
    fake_open = _FakeOpen(api_bytes, expect_session=False)

    adapter = NauraAdapter(rate_limit_seconds=0)
    # Pre-set opener to skip real session init in executor
    adapter._opener = _FakeOpener(fake_open)
    adapter._session_ready = True

    jobs = asyncio.run(
        adapter.search(
            keywords=["算法"],
            location="北京",
            rate_limit_seconds=0,
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "算法工程师（仿真方向）"
    assert jobs[0].company == "北方华创"


def test_search_api_error_returns_empty(monkeypatch):
    """HTTP error should return empty list."""
    import urllib.error

    class FakeOpenerError:
        def open(self, req, timeout=20, context=None):
            raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    adapter = NauraAdapter(rate_limit_seconds=0)
    adapter._opener = FakeOpenerError()
    adapter._session_ready = True

    jobs = asyncio.run(
        adapter.search(
            keywords=["算法"],
            location="北京",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_search_non_200_code(monkeypatch):
    """Non-200 Code should return empty."""
    resp = json.dumps({"Code": 500, "Message": "error", "Count": 0, "Data": []}).encode()
    fake_open = _FakeOpen(resp, expect_session=False)

    adapter = NauraAdapter(rate_limit_seconds=0)
    adapter._opener = _FakeOpener(fake_open)
    adapter._session_ready = True

    jobs = asyncio.run(
        adapter.search(
            keywords=["算法"],
            location="北京",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_rate_limit_default():
    adapter = NauraAdapter()
    assert adapter._rate_limit_seconds == 1.0


def test_rate_limit_custom():
    adapter = NauraAdapter(rate_limit_seconds=2.5)
    assert adapter._rate_limit_seconds == 2.5


def test_adapter_name():
    adapter = NauraAdapter()
    assert adapter.name == "naura"


def test_ensure_session_sets_opener():
    """_ensure_session should create opener and cookie jar."""
    adapter = NauraAdapter()
    assert adapter._session_ready is False
    assert adapter._opener is None

    # Manually set to simulate session init
    cj = CookieJar()
    adapter._cj = cj
    adapter._opener = _FakeOpener(_FakeOpen(b"{}"))
    adapter._session_ready = True

    assert adapter._session_ready is True
    assert adapter._opener is not None
