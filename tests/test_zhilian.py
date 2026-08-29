"""Tests for Zhilian browser-mode search, item parsing and salary parsing."""

import asyncio

from agent_core.platforms.zhilian import ZhilianAdapter, _parse_salary
from agent_core.platforms.zhilian_browser import (
    _build_search_url,
)
from agent_core.platforms.zhilian_browser import (
    _parse_salary as _browser_parse_salary,
)

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


def test_parse_salary_daily_returns_none():
    assert _parse_salary("300-500元/天") == (None, None)
    assert _parse_salary("40元/时") == (None, None)


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
    assert job.education == "本科"
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


# ── Browser search tests (mock ZhilianBrowser) ──


def make_mock_browser_item(
    name="AMR工程师",
    company_name="宁德时代",
    salary60="20K-30K",
    work_city="北京",
    education="本科",
    working_exp="3-5年",
    position_url="https://jobs.zhaopin.com/123.htm",
    number="ZL001",
):
    """Build a mock browser-intercepted API item (same format as HTTP API)."""
    return {
        "name": name,
        "companyName": company_name,
        "salary60": salary60,
        "workCity": work_city,
        "education": education,
        "workingExp": working_exp,
        "positionURL": position_url,
        "number": number,
        "workType": "全职",
    }


class MockZhilianBrowser:
    """Mock browser that returns predefined items."""

    def __init__(self, profile_dir="data/zhilian_browser_profile"):
        self.profile_dir = profile_dir
        self._items: list[dict] = []

    def set_items(self, items: list[dict]):
        self._items = items

    async def search(self, keyword="", city_code="0", headless=False, timeout_ms=30000):
        return list(self._items)

    async def close(self):
        pass


def test_search_browser_returns_results(monkeypatch):
    """search() via browser mode returns Job objects from intercepted items."""
    mock_browser = MockZhilianBrowser()
    mock_browser.set_items(
        [
            make_mock_browser_item(name="AMR工程师", company_name="宁德时代"),
            make_mock_browser_item(name="AGV算法工程师", company_name="比亚迪"),
        ]
    )

    async def _mock_get_browser(profile_dir="data/zhilian_browser_profile", headless=False):
        return mock_browser

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )

    adapter = ZhilianAdapter()
    jobs = asyncio.run(adapter.search(keywords=["AMR"], location="北京", headless=False))

    assert len(jobs) == 2
    assert jobs[0].title == "AMR工程师"
    assert jobs[0].company == "宁德时代"
    assert jobs[1].title == "AGV算法工程师"


def test_search_browser_empty_returns_empty(monkeypatch):
    """When browser returns 0 items, search() returns [] (browser-only mode)."""
    mock_browser = MockZhilianBrowser()
    mock_browser.set_items([])

    async def _mock_get_browser(profile_dir="data/zhilian_browser_profile", headless=False):
        return mock_browser

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )

    adapter = ZhilianAdapter()
    jobs = asyncio.run(adapter.search(keywords=["AMR"], location="北京", headless=False))

    assert jobs == []


def test_search_browser_import_error_returns_empty(monkeypatch):
    """When browser module cannot be imported, search() returns [] (no HTTP fallback)."""
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if "zhilian_browser" in name:
            raise ImportError("No module named 'playwright'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    adapter = ZhilianAdapter()
    jobs = asyncio.run(adapter.search(keywords=["AMR"], location="北京", headless=False))

    assert jobs == []


def test_browser_parse_salary_k_format():
    """Browser module's _parse_salary handles K format."""
    assert _browser_parse_salary("15K-25K") == (15000, 25000)
    assert _browser_parse_salary("8k-12k") == (8000, 12000)


def test_browser_parse_salary_wan_format():
    """Browser module's _parse_salary handles wan/qian format."""
    assert _browser_parse_salary("1.5万-2.5万") == (15000, 25000)


def test_browser_parse_salary_empty():
    """Browser module's _parse_salary handles empty/None."""
    assert _browser_parse_salary("") == (None, None)


def test_build_search_url_encodes_keyword():
    """Keyword and city are URL-encoded before navigation."""
    assert _build_search_url("AMR AGV+SLAM", "489") == (
        "https://sou.zhaopin.com/?keyword=AMR%20AGV%2BSLAM&city=489"
    )


def test_adapter_has_browser_profile_dir():
    """ZhilianAdapter stores browser_profile_dir."""
    adapter = ZhilianAdapter(browser_profile_dir="data/custom_profile")
    assert adapter._browser_profile_dir == "data/custom_profile"


def test_adapter_default_browser_profile_dir():
    """ZhilianAdapter has default browser_profile_dir."""
    adapter = ZhilianAdapter()
    assert "zhilian_browser_profile" in adapter._browser_profile_dir


def test_adapter_default_max_pages_one():
    """Browser mode only consumes the first XHR batch, so max pages defaults to 1."""
    adapter = ZhilianAdapter()
    assert adapter.max_pages == 1


def test_fetch_full_jd_short_circuit_when_jd_present():
    from types import SimpleNamespace

    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="岗位职责：负责设备维护", lid="http://x")
    assert asyncio.run(adapter.fetch_full_jd(job, "")) == ""


def test_fetch_full_jd_missing_lid_returns_empty():
    from types import SimpleNamespace

    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="")
    assert asyncio.run(adapter.fetch_full_jd(job, "")) == ""
