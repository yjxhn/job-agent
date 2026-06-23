"""Tests for Zhilian platform: response parsing, anti-bot detection, rate limiting."""

import asyncio
import json

from agent_core.platforms.zhilian import ZhilianAdapter, _parse_salary

# ── _parse_salary tests ──


def test_parse_salary_k_format():
    assert _parse_salary("15K-25K") == (15000, 25000)
    assert _parse_salary("8k-12k") == (8000, 12000)
    assert _parse_salary("20K") == (20000, None)


def test_parse_salary_wan_format():
    assert _parse_salary("1.5万-2.5万") == (15000, 25000)
    assert _parse_salary("8千-1.2万") == (8000, 12000)
    assert _parse_salary("3万") == (30000, None)


def test_parse_salary_empty():
    assert _parse_salary("") == (None, None)
    assert _parse_salary("薪资面议") == (None, None)
    assert _parse_salary(None) == (None, None)  # type: ignore[arg-type]


# ── _api_item_to_job tests ──


def make_zhilian_item(
    name="Python工程师",
    company_name="测试科技",
    salary60="15K-25K",
    work_city="北京",
    education="本科",
    working_exp="3-5年",
    position_url="https://jobs.zhaopin.com/123.htm",
    number="ZL001",
    industry_name=None,
    company_size=None,
    work_type="全职",
    welfare_label=None,
    job_desc=None,
):
    """Build a realistic Zhilian API data.list item (real field names)."""
    item: dict = {
        "name": name,
        "companyName": company_name,
        "salary60": salary60,
        "workCity": work_city,
        "education": education,
        "workingExp": working_exp,
        "positionURL": position_url,
        "number": number,
        "workType": work_type,
        "welfareLabel": welfare_label or ["五险一金", "年终奖"],
    }
    if industry_name:
        item["industryName"] = industry_name
    if company_size:
        item["companySize"] = company_size
    if job_desc:
        # Nest under jobDetailData.position.desc.description
        item["jobDetailData"] = {
            "position": {
                "desc": {"description": job_desc},
            }
        }
    return item


def test_item_to_job_basic():
    adapter = ZhilianAdapter()
    item = make_zhilian_item()
    job = adapter._api_item_to_job(item)

    assert job.title == "Python工程师"
    assert job.company == "测试科技"
    assert job.location == "北京"
    assert job.salary_min == 15000
    assert job.salary_max == 25000
    assert "学历: 本科" in job.description
    assert "经验: 3-5年" in job.description
    assert job.urls["zhilian"] == "https://jobs.zhaopin.com/123.htm"
    assert job.security_id == "ZL001"


def test_item_to_job_with_district():
    adapter = ZhilianAdapter()
    item = make_zhilian_item(work_city="上海")
    item["cityDistrict"] = "浦东"
    job = adapter._api_item_to_job(item)
    assert job.location == "上海 浦东"


def test_item_to_job_empty_company():
    adapter = ZhilianAdapter()
    item = make_zhilian_item(company_name="", salary60="10K-15K")
    item.pop("companyName")  # Missing companyName entirely
    job = adapter._api_item_to_job(item)
    assert job.company == ""
    assert job.title == "Python工程师"
    assert job.salary_min == 10000


def test_item_to_job_salary_from_nested():
    """salary60 empty but jobDetailData.position.base.salary has value."""
    adapter = ZhilianAdapter()
    item = make_zhilian_item(salary60="")
    item["jobDetailData"] = {
        "position": {
            "base": {"salary": "2万-3万"},
        }
    }
    job = adapter._api_item_to_job(item)
    assert job.salary_min == 20000
    assert job.salary_max == 30000


def test_item_to_job_with_full_desc():
    adapter = ZhilianAdapter()
    item = make_zhilian_item(job_desc="Responsible for system architecture design...")
    job = adapter._api_item_to_job(item)
    assert "Responsible for system architecture design" in job.description


def test_item_to_job_with_industry_and_size():
    adapter = ZhilianAdapter()
    item = make_zhilian_item(industry_name="互联网", company_size="1000-9999人")
    job = adapter._api_item_to_job(item)
    assert "行业: 互联网" in job.description
    assert "规模: 1000-9999人" in job.description


# ── normalize tests ──


def test_normalize():
    adapter = ZhilianAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "测试公司",
            "location": "上海",
            "salary_min": 10000,
            "salary_max": 20000,
            "description": "测试描述",
            "url": "https://example.com",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "zhilian" in job.platforms


# ── API response parsing tests (mock urllib) ──


def make_mock_search_resp(items=None, count=5):
    """Build a fake fe-api/c/i/sou JSON response with real data.list structure."""
    return json.dumps(
        {
            "code": 200,
            "apiCode": 200,
            "message": "成功",
            "data": {
                "count": count,
                "list": items or [],
            },
        }
    ).encode()


def test_search_parses_list(monkeypatch):
    """Search should parse results from data.list (real API field)."""
    from agent_core.platforms import zhilian

    item = make_zhilian_item(name="AMR工程师", company_name="宁德时代", salary60="20K-30K")

    class FakeResp:
        def read(self):
            return make_mock_search_resp([item], count=1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(zhilian, "_session_cookie_valid", lambda c: True)
    monkeypatch.setattr(
        zhilian,
        "_load_cookies",
        lambda path: [{"name": "FSSBBIl1UgzbN7NS", "value": "test", "expires": 2000000000}],
    )

    adapter = ZhilianAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AMR"],
            location="北京",
            cookie_path="data/cookies/zhilian.json",
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "AMR工程师"
    assert jobs[0].company == "宁德时代"
    assert jobs[0].salary_min == 20000
    assert jobs[0].salary_max == 30000


def test_search_no_cookie_returns_empty(monkeypatch):
    """Search with no/missing cookie path returns empty list."""
    adapter = ZhilianAdapter()
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="北京",
            cookie_path=None,
        )
    )
    assert jobs == []


def test_search_cookie_expired_returns_empty(monkeypatch):
    """Search with expired cookie returns empty list."""
    from agent_core.platforms import zhilian

    monkeypatch.setattr(zhilian, "_session_cookie_valid", lambda c: False)
    adapter = ZhilianAdapter()
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="北京",
            cookie_path="data/cookies/zhilian.json",
        )
    )
    assert jobs == []


def test_anti_bot_count_zero_triggers_backoff(monkeypatch):
    """When API returns code=200 but data.count=0, anti-bot is triggered."""
    from agent_core.platforms import zhilian

    anti_bot_called = []
    cookie_expired_called = []

    def fake_anti_bot():
        anti_bot_called.append(True)

    def fake_cookie_expired():
        cookie_expired_called.append(True)

    fake_resp = make_mock_search_resp([], count=0)

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
    monkeypatch.setattr(zhilian, "_session_cookie_valid", lambda c: True)
    monkeypatch.setattr(zhilian, "_notify_anti_bot", fake_anti_bot)
    monkeypatch.setattr(zhilian, "_notify_cookie_expired", fake_cookie_expired)
    monkeypatch.setattr(
        zhilian,
        "_load_cookies",
        lambda path: [{"name": "FSSBBIl1UgzbN7NS", "value": "test", "expires": 2000000000}],
    )

    async def fake_sleep(seconds: float) -> None:
        pass

    adapter = ZhilianAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="北京",
            cookie_path="data/cookies/zhilian.json",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []
    assert len(anti_bot_called) == 1
    assert len(cookie_expired_called) == 0


def test_anti_bot_count_positive_list_empty(monkeypatch):
    """count>0 but data.list empty = true anti-bot soft block."""
    from agent_core.platforms import zhilian

    anti_bot_called = []

    def fake_anti_bot():
        anti_bot_called.append(True)

    fake_resp = make_mock_search_resp([], count=100)

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
    monkeypatch.setattr(zhilian, "_session_cookie_valid", lambda c: True)
    monkeypatch.setattr(zhilian, "_notify_anti_bot", fake_anti_bot)
    monkeypatch.setattr(zhilian, "_notify_cookie_expired", lambda: None)
    monkeypatch.setattr(
        zhilian,
        "_load_cookies",
        lambda path: [{"name": "FSSBBIl1UgzbN7NS", "value": "test", "expires": 2000000000}],
    )

    async def fake_sleep(seconds: float) -> None:
        pass

    adapter = ZhilianAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="北京",
            cookie_path="data/cookies/zhilian.json",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []
    assert len(anti_bot_called) == 1


def test_non_200_code_triggers_cookie_expired(monkeypatch):
    """When API returns non-200 code, cookie-expired is triggered."""
    from agent_core.platforms import zhilian

    anti_bot_called = []
    cookie_expired_called = []

    def fake_anti_bot():
        anti_bot_called.append(True)

    def fake_cookie_expired():
        cookie_expired_called.append(True)

    fake_resp = json.dumps(
        {"code": 401, "apiCode": 401, "message": "unauthorized", "data": {}}
    ).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    async def fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(zhilian, "_session_cookie_valid", lambda c: True)
    monkeypatch.setattr(zhilian, "_notify_anti_bot", fake_anti_bot)
    monkeypatch.setattr(zhilian, "_notify_cookie_expired", fake_cookie_expired)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = ZhilianAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["Python"],
            location="北京",
            cookie_path="data/cookies/zhilian.json",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []
    assert len(anti_bot_called) == 0
    assert len(cookie_expired_called) == 1


def test_rate_limit_default():
    """Default rate_limit_seconds is 2.0."""
    adapter = ZhilianAdapter()
    assert adapter._rate_limit_seconds == 2.0


def test_rate_limit_custom():
    """Custom rate_limit_seconds is respected."""
    adapter = ZhilianAdapter(rate_limit_seconds=3.5)
    assert adapter._rate_limit_seconds == 3.5


def test_cookie_path_defaults_to_json():
    """Adapter accepts cookie_path to the standard location."""
    adapter = ZhilianAdapter()
    assert "zhilian" in adapter.name
