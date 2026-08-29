"""Additional focused unit tests for agent_core.platforms.zhilian.

These tests cover cookie loading, adapter configuration, search error paths,
extra API item mapping branches, and JD-fetch fallback paths without using a
real browser, network, or LLM.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent_core.platforms.zhilian import ZhilianAdapter, _load_cookies, zhilian_login

# ── _load_cookies ─────────────────────────────────────────────────────────


def test_load_cookies_missing_or_none_returns_empty(tmp_path):
    assert _load_cookies(None) == []
    assert _load_cookies(str(tmp_path / "missing.json")) == []


def test_load_cookies_valid_list_returns_cookies(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps([{"name": "at", "value": "1"}, {"name": "rt", "value": "2"}]),
        encoding="utf-8",
    )
    cookies = _load_cookies(str(cookie_file))
    assert len(cookies) == 2
    assert cookies[0] == {"name": "at", "value": "1"}


def test_load_cookies_invalid_json_returns_empty(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    assert _load_cookies(str(bad_file)) == []


def test_load_cookies_non_list_returns_empty(tmp_path):
    obj_file = tmp_path / "obj.json"
    obj_file.write_text(json.dumps({"name": "at", "value": "1"}), encoding="utf-8")
    assert _load_cookies(str(obj_file)) == []


# ── Adapter configuration ────────────────────────────────────────────────


def test_adapter_rate_limit_default_and_custom():
    assert ZhilianAdapter()._rate_limit_seconds == 2.0
    assert ZhilianAdapter(rate_limit_seconds=0.5)._rate_limit_seconds == 0.5


def test_adapter_max_pages_non_positive_defaults_to_one():
    assert ZhilianAdapter(max_pages=0).max_pages == 1
    assert ZhilianAdapter(max_pages=-5).max_pages == 1
    assert ZhilianAdapter(max_pages=3).max_pages == 3


# ── search() additional branches ─────────────────────────────────────────


def test_search_rate_limit_override_is_stored(monkeypatch):
    async def _mock_get_browser(*args, **kwargs):
        return SimpleNamespace(search=AsyncMock(return_value=[]))

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )
    adapter = ZhilianAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "北京", rate_limit_seconds=7))
    assert jobs == []
    assert adapter._rate_limit_seconds == 7


def test_search_multiple_keywords_sleeps_and_skips_bad_items(monkeypatch):
    class MockBrowser:
        def __init__(self):
            self.searches = []

        async def search(self, keyword, city_code="0", headless=False):
            self.searches.append(keyword)
            if keyword == "AMR":
                return [
                    {
                        "name": "AMR工程师",
                        "companyName": "测试公司",
                        "salary60": "15K-25K",
                        "workCity": "北京",
                        "positionURL": "https://jobs.zhaopin.com/1.htm",
                        "number": "ZL001",
                    }
                ]
            return [None]  # bad item must be skipped by _api_item_to_job

    mock_browser = MockBrowser()

    async def _mock_get_browser(*args, **kwargs):
        return mock_browser

    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    adapter = ZhilianAdapter()
    jobs = asyncio.run(adapter.search(["AMR", "AGV"], "北京"))
    assert [j.title for j in jobs] == ["AMR工程师"]
    assert mock_browser.searches == ["AMR", "AGV"]
    assert sleep_calls == [2, 2]


def test_search_browser_launch_error_returns_empty(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    adapter = ZhilianAdapter()
    assert asyncio.run(adapter.search(["AMR"], "北京")) == []


# ── _api_item_to_job extra branches ──────────────────────────────────────


def test_api_item_to_job_nested_company_fallback():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "company": {"name": "嵌套公司"},
        "salary60": "10K",
        "workCity": "上海",
    }
    job = adapter._api_item_to_job(item)
    assert job.company == "嵌套公司"


def test_api_item_to_job_non_dict_company_fallback_is_empty():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "company": "not-a-dict",
        "salary60": "10K",
        "workCity": "上海",
    }
    job = adapter._api_item_to_job(item)
    assert job.company == ""


def test_api_item_to_job_district_equal_city_not_appended():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "companyName": "公司",
        "salary60": "10K",
        "workCity": "北京",
        "cityDistrict": "北京",
    }
    job = adapter._api_item_to_job(item)
    assert job.location == "北京"


def test_api_item_to_job_missing_number_generates_id():
    adapter = ZhilianAdapter()
    item = {
        "name": "无编号职位",
        "companyName": "某公司",
        "salary60": "10K",
        "workCity": "北京",
    }
    job = adapter._api_item_to_job(item)
    assert job.security_id == ""
    assert job.id  # fallback MD5 id is non-empty
    assert job.id == job.id[:16]


def test_api_item_to_job_welfare_filters_empty_entries():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "companyName": "公司",
        "salary60": "10K",
        "workCity": "北京",
        "welfareLabel": ["", "五险一金", None, "年终奖"],
    }
    job = adapter._api_item_to_job(item)
    assert "福利: 五险一金/年终奖" in job.description


def test_api_item_to_job_non_dict_desc_is_ignored():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "companyName": "公司",
        "salary60": "10K",
        "workCity": "北京",
        "jobDetailData": {"position": {"desc": "not-a-dict"}},
    }
    job = adapter._api_item_to_job(item)
    assert job.description == ""


def test_api_item_to_job_preserves_publish_time_and_education():
    adapter = ZhilianAdapter()
    item = {
        "name": "测试",
        "companyName": "公司",
        "salary60": "10K",
        "workCity": "北京",
        "education": "硕士",
        "publishTime": "2026-01-02 10:00:00",
    }
    job = adapter._api_item_to_job(item)
    assert job.published_at == "2026-01-02 10:00:00"
    assert job.education == "硕士"


# ── fetch_full_jd extra branches ─────────────────────────────────────────


class _FakeElement:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _FakePage:
    def __init__(self, selector_text=None, body_text=""):
        self.selector_text = selector_text
        self.body_text = body_text
        self.closed = False

    async def goto(self, *args, **kwargs):
        pass

    async def wait_for_load_state(self, *args, **kwargs):
        pass

    async def query_selector(self, selector):
        if self.selector_text is not None:
            return _FakeElement(self.selector_text)
        return None

    async def inner_text(self, selector="body"):
        if selector == "body":
            return self.body_text
        return ""

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class _FakeZLBrowser:
    def __init__(self, context):
        self._context = context


def test_fetch_full_jd_persistent_browser_success(monkeypatch):
    page = _FakePage(selector_text="岗位职责" + "A" * 80)
    browser = _FakeZLBrowser(_FakeContext(page))

    async def _mock_get_browser(*args, **kwargs):
        return browser

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    result = asyncio.run(adapter.fetch_full_jd(job, ""))
    assert result.startswith("岗位职责")
    assert len(result) == 4 + 80
    assert page.closed is True


def test_fetch_full_jd_persistent_browser_short_falls_to_playwright_jd(monkeypatch):
    page = _FakePage(selector_text="短文本")
    browser = _FakeZLBrowser(_FakeContext(page))

    async def _mock_get_browser(*args, **kwargs):
        return browser

    async def _mock_fetch_jd_playwright(**kwargs):
        return "B" * 100

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _mock_fetch_jd_playwright,
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    result = asyncio.run(adapter.fetch_full_jd(job, ""))
    assert result == "B" * 100


def test_fetch_full_jd_playwright_jd_fallback(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("persistent browser failed")

    async def _mock_fetch_jd_playwright(**kwargs):
        return "C" * 90

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _mock_fetch_jd_playwright,
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    result = asyncio.run(adapter.fetch_full_jd(job, ""))
    assert result == "C" * 90


def test_fetch_full_jd_http_no_cookies_returns_empty(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("no browser")

    async def _raise_fetch(*args, **kwargs):
        raise RuntimeError("no playwright")

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _raise_fetch,
    )
    monkeypatch.setattr(
        "agent_core.platforms.zhilian._load_cookies",
        lambda cookie_path: [],
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    assert asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json")) == ""


def test_fetch_full_jd_http_extracts_describtion_html(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("no browser")

    async def _raise_fetch(*args, **kwargs):
        raise RuntimeError("no playwright")

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                '<html><body><div class="describtion__detail-content">'
                "<p>岗位职责内容足够长：负责设备维护</p></div></body></html>"
            ).encode()

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _raise_fetch,
    )
    monkeypatch.setattr(
        "agent_core.platforms.zhilian._load_cookies",
        lambda cookie_path: [{"name": "at", "value": "abc"}],
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=20: _FakeResp(),
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert "岗位职责内容足够长" in result
    assert "负责设备维护" in result


def test_fetch_full_jd_http_falls_back_to_body_marker(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("no browser")

    async def _raise_fetch(*args, **kwargs):
        raise RuntimeError("no playwright")

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                "<html><body><div>导航</div><div>岗位职责 负责机器人调试与维护</div></body></html>"
            ).encode()

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _raise_fetch,
    )
    monkeypatch.setattr(
        "agent_core.platforms.zhilian._load_cookies",
        lambda cookie_path: [{"name": "at", "value": "abc"}],
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=20: _FakeResp(),
    )
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert "负责机器人调试与维护" in result


def test_fetch_full_jd_http_error_returns_empty(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("no browser")

    async def _raise_fetch(*args, **kwargs):
        raise RuntimeError("no playwright")

    def _raise_urlopen(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _raise,
    )
    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _raise_fetch,
    )
    monkeypatch.setattr(
        "agent_core.platforms.zhilian._load_cookies",
        lambda cookie_path: [{"name": "at", "value": "abc"}],
    )
    monkeypatch.setattr("urllib.request.urlopen", _raise_urlopen)
    adapter = ZhilianAdapter()
    job = SimpleNamespace(description="简单描述", lid="https://jobs.zhaopin.com/1.htm")
    assert asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json")) == ""


# ── zhilian_login ────────────────────────────────────────────────────────


def test_zhilian_login_forwards_to_browser_login(monkeypatch):
    captured = {}

    async def _fake_login(profile_dir, timeout_s):
        captured["profile_dir"] = profile_dir
        captured["timeout_s"] = timeout_s
        return True

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.zhilian_browser_login",
        _fake_login,
    )
    assert asyncio.run(zhilian_login(timeout_s=42)) is True
    assert captured["profile_dir"] == "data/zhilian_browser_profile"
    assert captured["timeout_s"] == 42
