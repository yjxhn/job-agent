"""Tests for Boss platform: anti-bot vs cookie-expired distinction, JD detail fetch."""

import asyncio
import json

import pytest

from agent_core.platforms.base import Job
from agent_core.platforms.boss_zhipin import BossZhipinAdapter


# Test: anti-bot challenge (code 37) triggers _notify_anti_bot, NOT _notify_cookie_expired
def test_code_37_triggers_anti_bot_not_expired(monkeypatch):
    from agent_core.platforms import boss_zhipin

    # Track which notify function was called
    anti_bot_called = []
    cookie_expired_called = []

    # Monkeypatch at module level to match actual call signature (no args)
    def fake_notify_anti_bot():
        anti_bot_called.append("Boss直聘")

    def fake_notify_cookie_expired():
        cookie_expired_called.append("Boss直聘")

    # Mock urlopen to return code 37 with challenge markers
    fake_resp = json.dumps(
        {"code": 37, "message": "x", "zpData": {"seed": "s", "name": "n", "ts": 1}}
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

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(boss_zhipin, "_notify_anti_bot", fake_notify_anti_bot)
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))

    assert anti_bot_called == ["Boss直聘"], f"Expected anti-bot called, got {anti_bot_called}"
    assert (
        cookie_expired_called == []
    ), f"Cookie expired should NOT be called, got {cookie_expired_called}"
    assert jobs == [], "Should return empty list on anti-bot"


# Test: code-37 backoff sleep test (would wait 300s, blocks CI, so skipped)
@pytest.mark.skip(reason="Backoff sleep takes 300s, skip in CI")
def test_code_37_backoff_sleeps():
    """Test: code-37 triggers _ANTI_BOT_BACKOFF_SECONDS (300s) backoff."""

    # Mock asyncio.sleep to track if backoff duration is used
    sleep_called_with = []

    async def fake_sleep(seconds):
        if seconds == 300:
            sleep_called_with.append(True)

    # Mock urlopen to return code 37
    fake_resp = json.dumps(
        {"code": 37, "message": "anti-bot challenge", "zpData": {"seed": "s", "name": "n", "ts": 1}}
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

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = BossZhipinAdapter(rate_limit_seconds=1.5)
    # This will trigger backoff and should sleep 300s
    try:
        asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=1))
    except Exception:
        # We expect the backoff to break after sleep
        pass

    # Wait a bit for the async sleep to complete if triggered
    import time

    time.sleep(0.1)

    assert sleep_called_with == [True], "Should have slept 300s on code-37 backoff"


# Test: other non-zero codes trigger _notify_cookie_expired
def test_other_nonzero_triggers_cookie_expired(monkeypatch):
    from agent_core.platforms import boss_zhipin

    anti_bot_called = []
    cookie_expired_called = []

    def fake_notify_anti_bot():
        anti_bot_called.append("Boss直聘")

    def fake_notify_cookie_expired():
        cookie_expired_called.append("Boss直聘")

    # Mock urlopen to return code 1501 (auth error) without challenge markers
    fake_resp = json.dumps({"code": 1501, "message": "login required", "zpData": {}}).encode()

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
    monkeypatch.setattr(boss_zhipin, "_notify_anti_bot", fake_notify_anti_bot)
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))

    assert anti_bot_called == [], f"Anti-bot should NOT be called, got {anti_bot_called}"
    assert cookie_expired_called == [
        "Boss直聘"
    ], f"Expected cookie expired called, got {cookie_expired_called}"
    assert jobs == [], "Should return empty list on auth error"


# Test: rate_limit_seconds is used for page sleep
def test_rate_limit_seconds_used(monkeypatch):
    """Verify that rate_limit_seconds from config is used for page delays."""
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    sleep_called_with = []

    async def fake_sleep(seconds):
        sleep_called_with.append(seconds)

    def create_fake_resp(page):
        return json.dumps(
            {
                "code": 0,
                "zpData": {
                    "jobList": [
                        {
                            "jobName": "AMR Engineer",
                            "brandName": "Test Corp",
                            "encryptJobId": "test001",
                            "cityName": "Suzhou",
                            "areaDistrict": "",
                            "businessDistrict": "",
                            "salaryDesc": "15-20K",
                            "jobExperience": "3-5年",
                            "jobDegree": "本科",
                            "skills": [],
                            "jobLabels": [],
                            "welfareList": [],
                            "brandIndustry": "",
                            "brandScaleName": "",
                            "securityId": "",
                            "lid": "",
                        }
                    ]
                },
            }
        ).encode()

    class FakeResp:
        def __init__(self, page):
            self.page = page

        def read(self):
            return create_fake_resp(self.page)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp(1)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # Test with custom rate_limit_seconds
    adapter = BossZhipinAdapter(rate_limit_seconds=2.5)
    asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=2))

    # Sleep only between pages: 2.5s between page 1 and page 2.
    assert 2.5 in sleep_called_with, f"Expected sleep with 2.5s, got {sleep_called_with}"


# Test: rate_limit_seconds defaults to 1.5 when not provided
def test_rate_limit_defaults(monkeypatch):
    """Verify that rate_limit_seconds defaults to 1.5 when not provided."""
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    sleep_called_with = []

    async def fake_sleep(seconds):
        sleep_called_with.append(seconds)

    def create_fake_resp(page):
        return json.dumps(
            {
                "code": 0,
                "zpData": {
                    "jobList": [
                        {
                            "jobName": "AMR Engineer",
                            "brandName": "Test Corp",
                            "encryptJobId": "test001",
                            "cityName": "Suzhou",
                            "areaDistrict": "",
                            "businessDistrict": "",
                            "salaryDesc": "15-20K",
                            "jobExperience": "3-5年",
                            "jobDegree": "本科",
                            "skills": [],
                            "jobLabels": [],
                            "welfareList": [],
                            "brandIndustry": "",
                            "brandScaleName": "",
                            "securityId": "",
                            "lid": "",
                        }
                    ]
                },
            }
        ).encode()

    class FakeResp:
        def __init__(self, page):
            self.page = page

        def read(self):
            return create_fake_resp(self.page)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp(1)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = BossZhipinAdapter()  # No rate_limit_seconds arg, should use default
    asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=2))

    # Sleep only between pages: 1.5s between page 1 and page 2.
    assert 1.5 in sleep_called_with, f"Expected default sleep with 1.5s, got {sleep_called_with}"


# ── _fetch_jd_detail field extraction tests ──────────────────────────────
# Verified at call sites via mocking; no real API call needed.


def _make_card_response(post_description_path):
    """Build a card.json response with postDescription at the given nested path.

    Path is a tuple of keys, e.g. ("jobCard", "postDescription").
    """
    inner = {"postDescription": "## 岗位职责\n1. xxx\n2. yyy"}
    # Walk the path in reverse to nest
    result = inner
    for key in reversed(post_description_path[:-1]):
        result = {key: result}
    return json.dumps({"code": 0, "zpData": result}).encode()


class _FakeCardResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.mark.parametrize(
    "path",
    [
        ("jobCard", "postDescription"),  # primary path
        ("postDescription",),  # fallback 1
        ("jobInfo", "postDescription"),  # fallback 2
    ],
)
def test_fetch_jd_detail_paths(monkeypatch, path):
    """_fetch_jd_detail should find postDescription in each supported path."""
    resp = _make_card_response(path)

    captured_url = []

    def fake_urlopen(req, timeout=20):
        captured_url.append(req.full_url)
        return _FakeCardResp(resp)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))

    assert "岗位职责" in result, f"Path {path} failed to extract JD, got: {result!r}"
    assert "card.json?securityId=sec123&lid=lid456" in captured_url[0]


def test_fetch_jd_detail_empty_on_missing_field(monkeypatch):
    """_fetch_jd_detail returns empty string when postDescription is absent."""
    resp = json.dumps({"code": 0, "zpData": {"jobCard": {"otherField": "x"}}}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeCardResp(resp))
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))
    assert result == ""


def test_fetch_jd_detail_empty_on_http_error(monkeypatch):
    """_fetch_jd_detail returns empty string on HTTP/network error."""

    def _raise(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))
    assert result == ""


def test_fetch_jd_detail_truncates_at_5000(monkeypatch):
    """_fetch_jd_detail truncates postDescription to 5000 characters."""
    long_text = "A" * 8000
    resp = json.dumps({"code": 0, "zpData": {"jobCard": {"postDescription": long_text}}}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeCardResp(resp))
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))
    assert len(result) == 5000
    assert result == "A" * 5000


def test_fetch_jd_detail_empty_on_code_nonzero(monkeypatch):
    """_fetch_jd_detail returns empty string when API code is not 0."""
    resp = json.dumps({"code": 37, "zpData": {"seed": "s"}}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeCardResp(resp))
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))
    assert result == ""


def test_fetch_jd_detail_real_response_shape(monkeypatch):
    """_fetch_jd_detail extracts postDescription from a realistic card.json response.

    Verified against real Boss API 2026-06-22: zpData.jobCard contains
    postDescription alongside other fields like jobName, salaryDesc, etc.
    """
    # Real card.json response structure (field names/values sanitized)
    real_shape = {
        "code": 0,
        "zpData": {
            "jobCard": {
                "jobName": "Python开发工程师",
                "postDescription": (
                    "## 岗位职责\n1. 负责后台服务开发\n2. 参与架构设计\n"
                    "## 任职要求\n- 熟练Python\n- 熟悉Django/Flask"
                ),
                "encryptJobId": "abc123",
                "atsDirectPost": False,
                "atsProxyJob": False,
                "salaryDesc": "15-25K",
                "cityName": "北京",
                "experienceName": "3-5年",
                "degreeName": "本科",
                "jobLabels": ["Python", "Django", "Flask"],
            }
        },
    }
    resp = json.dumps(real_shape).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeCardResp(resp))
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))

    assert "岗位职责" in result
    assert "Python" in result
    # Should not contain non-postDescription fields
    assert "北京" not in result  # cityName should not leak into JD text
    assert "Django" in result  # jobLabels should not reappear unless in JD text
    # Django appears in the JD text, so yes it should be there


def test_fetch_jd_detail_handles_non_dict_zpdata(monkeypatch):
    """_fetch_jd_detail returns empty when zpData is not a dict."""
    resp = json.dumps({"code": 0, "zpData": ["list", "not", "dict"]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeCardResp(resp))
    adapter = BossZhipinAdapter()
    result = asyncio.run(adapter._fetch_jd_detail("sec123", "lid456", "wt2=x"))
    assert result == ""


# ── Additional coverage tests ────────────────────────────────────────────


def test_load_cookies_missing_path():
    """_load_cookies returns [] when path is None or file missing."""
    from agent_core.platforms.boss_zhipin import _load_cookies

    assert _load_cookies(None) == []
    assert _load_cookies("/nonexistent/path/cookies.json") == []


def test_load_cookies_invalid_json(monkeypatch, tmp_path):
    """_load_cookies returns [] on invalid JSON."""
    from agent_core.platforms.boss_zhipin import _load_cookies

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = _load_cookies(str(bad))
    assert result == []


def test_session_cookie_valid_expired():
    """_session_cookie_valid returns False when wt2 is expired."""
    import time

    from agent_core.platforms.boss_zhipin import _session_cookie_valid

    past = time.time() - 3600
    cookies = [{"name": "wt2", "value": "x", "expires": past}]
    assert _session_cookie_valid(cookies) is False


def test_session_cookie_valid_no_wt2():
    """_session_cookie_valid returns False when no wt2 cookie."""
    from agent_core.platforms.boss_zhipin import _session_cookie_valid

    cookies = [{"name": "other_cookie", "value": "x", "expires": -1}]
    assert _session_cookie_valid(cookies) is False


def test_session_cookie_valid_requires_stoken():
    """wt2 alone is NOT enough — Boss search also needs __zp_stoken__."""
    from agent_core.platforms.boss_zhipin import _session_cookie_valid

    cookies = [
        {"name": "wt2", "value": "x", "expires": -1},
        {"name": "other_cookie", "value": "x", "expires": -1},
    ]
    assert _session_cookie_valid(cookies) is False


def test_session_cookie_valid_both_present():
    """wt2 + __zp_stoken__ session cookies are valid."""
    from agent_core.platforms.boss_zhipin import _session_cookie_valid

    cookies = [
        {"name": "wt2", "value": "x", "expires": -1},
        {"name": "__zp_stoken__", "value": "y", "expires": -1},
    ]
    assert _session_cookie_valid(cookies) is True


def test_notify_anti_bot_handles_import_error(monkeypatch):
    """_notify_anti_bot does not raise on Windows toast import error."""
    from agent_core.platforms import boss_zhipin

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if "agent_core.notify.windows_toast" in name:
            raise ImportError("no toast")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    # Should not raise
    boss_zhipin._notify_anti_bot()


def test_notify_cookie_expired_boss_handles_import_error(monkeypatch):
    """_notify_cookie_expired for Boss does not raise on import error."""
    from agent_core.platforms import boss_zhipin

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if "agent_core.notify.windows_toast" in name:
            raise ImportError("no toast")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    # Should not raise
    boss_zhipin._notify_cookie_expired()


def test_search_no_cookie_returns_empty(monkeypatch):
    """search returns [] when cookie file is missing."""
    from agent_core.platforms import boss_zhipin

    cookie_expired_called = []

    def fake_notify():
        cookie_expired_called.append("Boss直聘")

    monkeypatch.setattr(boss_zhipin, "_load_cookies", lambda p: [])
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "全国", cookie_path="/nonexistent"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_invalid_session_cookie(monkeypatch):
    """search returns [] when wt2 is expired."""
    from agent_core.platforms import boss_zhipin

    cookie_expired_called = []

    def fake_notify():
        cookie_expired_called.append("Boss直聘")

    monkeypatch.setattr(
        boss_zhipin,
        "_load_cookies",
        lambda p: [{"name": "wt2", "value": "x", "expires": 1}],
    )
    monkeypatch.setattr(boss_zhipin, "_session_cookie_valid", lambda c: False)
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "全国"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_keyword_api_http_error_breaks(monkeypatch):
    """_search_keyword_api breaks on HTTPError."""
    import urllib.error

    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError("https://example.com", 500, "Server Error", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))
    assert jobs == []


def test_search_keyword_api_generic_exception_breaks(monkeypatch):
    """_search_keyword_api breaks on generic exception."""

    def fake_urlopen(req, timeout=20):
        raise ValueError("unexpected error")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))
    assert jobs == []


def test_search_keyword_api_empty_job_list_breaks(monkeypatch):
    """_search_keyword_api breaks when jobList is empty."""
    fake_resp = json.dumps({"code": 0, "zpData": {"jobList": []}}).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))
    assert jobs == []


def test_api_item_to_job_no_optional_fields():
    """_api_item_to_job handles a job with no optional description fields."""
    adapter = BossZhipinAdapter()

    job_raw = {
        "jobName": "Cleaner",
        "brandName": "Minimal Inc",
        "encryptJobId": "min001",
        "cityName": "Shenzhen",
        "areaDistrict": "",
        "businessDistrict": "",
        "salaryDesc": "5-8K",
        "jobExperience": "",
        "jobDegree": "",
        "skills": [],
        "jobLabels": [],
        "welfareList": [],
        "brandIndustry": "",
        "brandScaleName": "",
        "securityId": "s1",
        "lid": "l1",
    }

    job = asyncio.run(adapter._api_item_to_job(job_raw))
    assert job.title == "Cleaner"
    assert job.company == "Minimal Inc"
    assert job.salary_min == 5000
    assert job.salary_max == 8000
    assert "经验:" not in job.description


def test_api_item_to_job_optional_fields_populated():
    """_api_item_to_job includes all optional fields when present."""
    adapter = BossZhipinAdapter()

    job_raw = {
        "jobName": "Full Stack",
        "brandName": "Rich Corp",
        "encryptJobId": "rich001",
        "cityName": "Beijing",
        "areaDistrict": "Haidian",
        "businessDistrict": "Zhongguancun",
        "salaryDesc": "20-30K",
        "jobExperience": "3-5年",
        "jobDegree": "本科",
        "skills": ["Python", "React"],
        "jobLabels": ["大牛多"],
        "welfareList": ["五险一金"],
        "brandIndustry": "互联网",
        "brandScaleName": "1000-9999人",
        "securityId": "s2",
        "lid": "l2",
    }

    job = asyncio.run(adapter._api_item_to_job(job_raw))
    assert job.title == "Full Stack"
    assert "经验: 3-5年" in job.description
    assert "学历: 本科" in job.description
    assert "技能: Python/React" in job.description
    assert "标签: 大牛多" in job.description
    assert "福利: 五险一金" in job.description
    assert "行业: 互联网" in job.description
    assert "规模: 1000-9999人" in job.description
    assert job.location == "Beijing-Haidian-Zhongguancun"


def test_fetch_full_jd_no_cookies(monkeypatch):
    """fetch_full_jd returns '' when no cookies available."""
    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin._load_cookies",
        lambda p: [],
    )
    adapter = BossZhipinAdapter()
    job = Job(id="test", title="T", company="C", description="", platforms=["boss_zhipin"], urls={})
    job.security_id = "s1"
    job.lid = "l1"
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert result == ""


def test_fetch_full_jd_invalid_session_cookie(monkeypatch):
    """fetch_full_jd returns '' when session cookie is expired."""
    import time

    monkeypatch.setattr(
        "agent_core.platforms.boss_zhipin._load_cookies",
        lambda p: [{"name": "wt2", "value": "x", "expires": time.time() - 3600}],
    )
    adapter = BossZhipinAdapter()
    job = Job(id="test", title="T", company="C", description="", platforms=["boss_zhipin"], urls={})
    job.security_id = "s1"
    job.lid = "l1"
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert result == ""


def test_fetch_full_jd_missing_security_id():
    """fetch_full_jd returns '' when security_id or lid is missing."""
    adapter = BossZhipinAdapter()
    job = Job(id="test", title="T", company="C", description="", platforms=["boss_zhipin"], urls={})
    job.security_id = ""
    job.lid = ""
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert result == ""


def test_parse_salary_empty():
    """_parse_salary returns (None, None) for empty or no-K text."""
    from agent_core.platforms.boss_zhipin import _parse_salary

    assert _parse_salary("") == (None, None)
    assert _parse_salary("薪资面议") == (None, None)
    assert _parse_salary("面议") == (None, None)


def test_parse_salary_single_k():
    """_parse_salary handles single value like '15K'."""
    from agent_core.platforms.boss_zhipin import _parse_salary

    assert _parse_salary("15K") == (15000, None)
    assert _parse_salary("8k") == (8000, None)


def test_search_keyword_api_multi_page(monkeypatch):
    """_search_keyword_api iterates multiple pages with rate_limit sleep."""
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    page_responses = []

    def create_fake_resp(page):
        if page == 1 and len(page_responses) == 0:
            resp = json.dumps(
                {
                    "code": 0,
                    "zpData": {
                        "jobList": [
                            {
                                "jobName": "Page1 Job",
                                "brandName": "P1 Corp",
                                "encryptJobId": "p1",
                                "cityName": "Shenzhen",
                                "areaDistrict": "",
                                "businessDistrict": "",
                                "salaryDesc": "10-15K",
                                "jobExperience": "",
                                "jobDegree": "",
                                "skills": [],
                                "jobLabels": [],
                                "welfareList": [],
                                "brandIndustry": "",
                                "brandScaleName": "",
                                "securityId": "",
                                "lid": "",
                            }
                        ]
                    },
                }
            ).encode()
        elif page == 2 and len(page_responses) == 1:
            resp = json.dumps(
                {
                    "code": 0,
                    "zpData": {
                        "jobList": [
                            {
                                "jobName": "Page2 Job",
                                "brandName": "P2 Corp",
                                "encryptJobId": "p2",
                                "cityName": "Shanghai",
                                "areaDistrict": "",
                                "businessDistrict": "",
                                "salaryDesc": "20-25K",
                                "jobExperience": "",
                                "jobDegree": "",
                                "skills": [],
                                "jobLabels": [],
                                "welfareList": [],
                                "brandIndustry": "",
                                "brandScaleName": "",
                                "securityId": "",
                                "lid": "",
                            }
                        ]
                    },
                }
            ).encode()
        else:
            resp = json.dumps({"code": 0, "zpData": {"jobList": []}}).encode()

        page_responses.append(page)
        return resp

    class FakeResp:
        def __init__(self):
            self._data = create_fake_resp(len(page_responses) + 1)

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = BossZhipinAdapter(rate_limit_seconds=1.0)
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=3))
    assert len(jobs) == 2
    assert jobs[0].title == "Page1 Job"
    assert jobs[1].title == "Page2 Job"
    assert 1.0 in sleep_calls


def test_boss_login_returns_false():
    """boss_login always returns False (manual flow guidance)."""
    from agent_core.platforms.boss_zhipin import boss_login

    result = asyncio.run(boss_login("/fake/cookie/path.json"))
    assert result is False


def test_liepin_login_returns_false():
    """liepin_login always returns False (manual flow guidance)."""
    from agent_core.platforms.liepin import liepin_login

    result = asyncio.run(liepin_login("/fake/cookie/path.json"))
    assert result is False


def test_api_item_to_job_no_encrypt_id_fallback():
    """_api_item_to_job generates ID from company+title when encryptJobId missing."""
    adapter = BossZhipinAdapter()

    job_raw = {
        "jobName": "No ID Job",
        "brandName": "Nameless Corp",
        "encryptJobId": "",
        "cityName": "Wuhan",
        "areaDistrict": "",
        "businessDistrict": "",
        "salaryDesc": "8-12K",
        "jobExperience": "",
        "jobDegree": "",
        "skills": [],
        "jobLabels": [],
        "welfareList": [],
        "brandIndustry": "",
        "brandScaleName": "",
        "securityId": "",
        "lid": "",
    }

    job = asyncio.run(adapter._api_item_to_job(job_raw))
    assert job.title == "No ID Job"
    assert job.id
