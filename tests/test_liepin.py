"""Tests for Liepin platform: HTTP API adapter."""

import asyncio
import json

from agent_core.platforms.base import Job
from agent_core.platforms.liepin import LiepinAdapter


def test_liepin_search_parses_jobcards(monkeypatch):
    """Test that search correctly parses jobCardList from API response."""
    from agent_core.platforms import liepin

    # Monkeypatch cookie helpers to return valid cookie
    def fake_load_cookies(p):
        return [
            {"name": "lt_auth", "value": "x", "expires": -1},
            {"name": "XSRF-TOKEN", "value": "tok"},
        ]

    def fake_session_valid(c):
        return True

    # Track _notify_cookie_expired calls
    cookie_expired_called = []

    def fake_notify_cookie_expired():
        cookie_expired_called.append("猎聘")

    # Mock API response with one job card
    fake_resp = json.dumps(
        {
            "flag": 1,
            "data": {
                "data": {
                    "jobCardList": [
                        {
                            "comp": {
                                "compName": "某公司",
                                "compScale": "100-499人",
                                "compIndustry": "机械/设备",
                                "compStage": "B轮",
                            },
                            "job": {
                                "title": "AMR工程师",
                                "jobId": "123",
                                "salary": "15-20k·13薪",
                                "dq": "苏州-常熟",
                                "link": "https://www.liepin.com/a/123.shtml",
                                "requireWorkYears": "3-5年",
                                "requireEduLevel": "本科",
                                "labels": ["ROS"],
                            },
                            "recruiter": {"recruiterName": "张三", "recruiterTitle": "HR"},
                        }
                    ]
                }
            },
        }
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
    monkeypatch.setattr(liepin, "_load_cookies", fake_load_cookies)
    monkeypatch.setattr(liepin, "_session_cookie_valid", fake_session_valid)
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "全国"))

    assert len(jobs) == 1, f"Expected 1 job, got {len(jobs)}"
    assert jobs[0].title == "AMR工程师", f"Expected 'AMR工程师', got '{jobs[0].title}'"
    assert jobs[0].company == "某公司", f"Expected '某公司', got '{jobs[0].company}'"
    assert jobs[0].salary_min == 15000, f"Expected 15000, got {jobs[0].salary_min}"
    assert jobs[0].salary_max == 20000, f"Expected 20000, got {jobs[0].salary_max}"
    assert "liepin.com" in jobs[0].urls["liepin"], f"Expected liepin.com in URL, got {jobs[0].urls}"
    assert (
        cookie_expired_called == []
    ), f"Cookie expired should NOT be called, got {cookie_expired_called}"


def test_liepin_parse_salary(monkeypatch):
    """Test salary parsing for various formats."""
    from agent_core.platforms.liepin import _parse_salary

    # "15-20k·13薪" -> (15000, 20000)
    assert _parse_salary("15-20k·13薪") == (15000, 20000)

    # "薪资面议" -> (None, None)
    assert _parse_salary("薪资面议") == (None, None)

    # "20-40k" -> (20000, 40000)
    assert _parse_salary("20-40k") == (20000, 40000)


def test_liepin_api_item_to_job_maps_fields(monkeypatch):
    """Test that _api_item_to_job correctly maps all fields."""
    adapter = LiepinAdapter()

    card = {
        "comp": {
            "compName": "测试公司",
            "compScale": "500-999人",
            "compIndustry": "互联网",
            "compStage": "C轮",
        },
        "job": {
            "title": "算法工程师",
            "jobId": "job456",
            "salary": "25-35k",
            "dq": "北京-海淀",
            "link": "https://www.liepin.com/a/456.shtml",
            "requireWorkYears": "5-10年",
            "requireEduLevel": "硕士",
            "labels": ["Python", "机器学习"],
        },
        "recruiter": {"recruiterName": "李四", "recruiterTitle": "技术HR"},
    }

    job = adapter._api_item_to_job(card)

    assert job.title == "算法工程师"
    assert job.company == "测试公司"
    assert job.location == "北京-海淀"
    assert job.salary_min == 25000
    assert job.salary_max == 35000
    assert job.urls["liepin"] == "https://www.liepin.com/a/456.shtml"
    assert "经验: 5-10年" in job.description
    assert "学历: 硕士" in job.description
    assert "标签: Python/机器学习" in job.description
    assert "行业: 互联网" in job.description
    assert "规模: 500-999人" in job.description
    assert "阶段: C轮" in job.description
    assert "HR: 李四" in job.description
    assert "HR职位: 技术HR" in job.description


def test_liepin_flag_not_one_notifies(monkeypatch):
    """Test that flag != 1 triggers _notify_cookie_expired."""
    from agent_core.platforms import liepin

    # Track _notify_cookie_expired calls
    cookie_expired_called = []

    def fake_notify_cookie_expired():
        cookie_expired_called.append("猎聘")

    # Mock API response with flag != 1
    fake_resp = json.dumps({"flag": 0, "msg": "未登录", "data": {}}).encode()

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
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "lt_auth=x;XSRF-TOKEN=tok"))

    assert jobs == [], f"Expected empty list, got {jobs}"
    assert cookie_expired_called == [
        "猎聘"
    ], f"Expected cookie expired called, got {cookie_expired_called}"


# ── Additional coverage tests ─────────────────────────────────────────────


def test_load_cookies_missing_path():
    """_load_cookies returns [] when path is None or file missing."""
    from agent_core.platforms.liepin import _load_cookies

    assert _load_cookies(None) == []
    assert _load_cookies("/nonexistent/path/cookies.json") == []


def test_load_cookies_invalid_json(monkeypatch, tmp_path):
    """_load_cookies returns [] on invalid JSON."""
    from agent_core.platforms.liepin import _load_cookies

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json}", encoding="utf-8")
    result = _load_cookies(str(bad))
    assert result == []


def test_session_cookie_valid_expired():
    """_session_cookie_valid returns False when lt_auth is expired."""
    import time

    from agent_core.platforms.liepin import _session_cookie_valid

    past = time.time() - 3600
    cookies = [{"name": "lt_auth", "value": "x", "expires": past}]
    assert _session_cookie_valid(cookies) is False


def test_session_cookie_valid_no_lt_auth():
    """_session_cookie_valid returns False when no lt_auth cookie."""
    from agent_core.platforms.liepin import _session_cookie_valid

    cookies = [{"name": "other_cookie", "value": "x", "expires": -1}]
    assert _session_cookie_valid(cookies) is False


def test_session_cookie_valid_session_cookie():
    """_session_cookie_valid returns True for no-expiry session cookie."""
    from agent_core.platforms.liepin import _session_cookie_valid

    cookies = [{"name": "lt_auth", "value": "x", "expires": -1}]
    assert _session_cookie_valid(cookies) is True


def test_notify_cookie_expired_handles_import_error(monkeypatch):
    """_notify_cookie_expired does not raise on Windows toast import error."""
    from agent_core.platforms import liepin

    # Simulate import error in windows_toast module
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if "agent_core.notify.windows_toast" in name:
            raise ImportError("no toast")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    # Should not raise
    liepin._notify_cookie_expired()


def test_search_no_cookie_returns_empty(monkeypatch):
    """search returns [] when cookie file is missing."""
    from agent_core.platforms import liepin

    cookie_expired_called = []

    def fake_notify():
        cookie_expired_called.append("猎聘")

    monkeypatch.setattr(liepin, "_load_cookies", lambda p: [])
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "全国", cookie_path="/nonexistent"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_invalid_session_cookie(monkeypatch):
    """search returns [] when lt_auth is expired."""
    from agent_core.platforms import liepin

    cookie_expired_called = []

    def fake_notify():
        cookie_expired_called.append("猎聘")

    monkeypatch.setattr(
        liepin,
        "_load_cookies",
        lambda p: [{"name": "lt_auth", "value": "x", "expires": 1}],
    )
    monkeypatch.setattr(liepin, "_session_cookie_valid", lambda c: False)
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter.search(["AMR"], "全国"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_keyword_api_http_error_notifies(monkeypatch):
    """_search_keyword_api calls _notify_cookie_expired on HTTPError."""
    import urllib.error

    from agent_core.platforms import liepin

    cookie_expired_called = []

    def fake_notify_cookie():
        cookie_expired_called.append("猎聘")

    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError("https://example.com", 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify_cookie)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "lt_auth=x"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_keyword_api_generic_exception_notifies(monkeypatch):
    """_search_keyword_api calls _notify_cookie_expired on generic exception."""
    from agent_core.platforms import liepin

    cookie_expired_called = []

    def fake_notify_cookie():
        cookie_expired_called.append("猎聘")

    def fake_urlopen(req, timeout=20):
        raise ValueError("connection broken")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(liepin, "_notify_cookie_expired", fake_notify_cookie)

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "lt_auth=x"))
    assert jobs == []
    assert len(cookie_expired_called) >= 1


def test_search_keyword_api_empty_job_list(monkeypatch):
    """_search_keyword_api returns [] when jobCardList is empty."""

    fake_resp = json.dumps({"flag": 1, "data": {"data": {"jobCardList": []}}}).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "lt_auth=x"))
    assert jobs == []


def test_api_item_to_job_minimal_card():
    """_api_item_to_job handles a minimal card with no optional fields."""
    adapter = LiepinAdapter()

    card = {
        "comp": {"compName": "Minimal Corp"},
        "job": {
            "title": "Engineer",
            "salary": "20-30k",
            "dq": "深圳",
            "link": "https://www.liepin.com/a/789.shtml",
        },
        "recruiter": {},
    }

    job = adapter._api_item_to_job(card)
    assert job.title == "Engineer"
    assert job.company == "Minimal Corp"
    assert job.location == "深圳"
    assert job.salary_min == 20000
    assert job.salary_max == 30000


def test_api_item_to_job_no_job_id_fallback():
    """_api_item_to_job generates ID from company+title when jobId missing."""
    adapter = LiepinAdapter()

    card = {
        "comp": {"compName": "Fallback Corp"},
        "job": {
            "title": "Tester",
            "salary": "10-15k",
            "dq": "北京",
            "link": "https://liepin.com/a/noid",
        },
        "recruiter": {},
    }

    job = adapter._api_item_to_job(card)
    assert job.title == "Tester"
    assert job.id  # Some ID should be generated


def test_fetch_full_jd_invalid_url(monkeypatch):
    """fetch_full_jd returns '' when job has no valid URL."""
    from agent_core.platforms import liepin

    monkeypatch.setattr(
        liepin,
        "_load_cookies",
        lambda p: [{"name": "lt_auth", "value": "x", "expires": -1}],
    )

    adapter = LiepinAdapter()
    job = Job(id="test", title="T", company="C", description="", platforms=["liepin"], urls={})
    job.security_id = ""
    job.lid = ""
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert result == ""


def test_fetch_full_jd_http_error(monkeypatch):
    """fetch_full_jd returns '' when both Playwright and HTTP fallback fail."""
    from agent_core.platforms import liepin

    monkeypatch.setattr(
        liepin,
        "_load_cookies",
        lambda p: [{"name": "lt_auth", "value": "x", "expires": -1}],
    )

    # fetch_full_jd is Playwright-first now; force the Playwright path to fail
    # (RuntimeError = playwright not installed) so it falls through to the
    # legacy urllib path, which we then break to verify '' is returned.
    async def _fake_playwright_unavailable(*a, **kw):
        raise RuntimeError("playwright not installed")

    monkeypatch.setattr(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright",
        _fake_playwright_unavailable,
    )

    def fake_urlopen(req, timeout=20):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = LiepinAdapter()
    job = Job(id="test", title="T", company="C", description="", platforms=["liepin"], urls={})
    job.security_id = "123"
    job.lid = "https://www.liepin.com/a/123.shtml"
    result = asyncio.run(adapter.fetch_full_jd(job, "/fake/cookies.json"))
    assert result == ""


def test_parse_salary_nok():
    """_parse_salary returns (None, None) when text has no K/k."""
    from agent_core.platforms.liepin import _parse_salary

    assert _parse_salary("薪资面议") == (None, None)
    assert _parse_salary("") == (None, None)
    assert _parse_salary("15-20万/年") == (None, None)


def test_parse_salary_single_k():
    """_parse_salary handles single K value like '15K'."""
    from agent_core.platforms.liepin import _parse_salary

    assert _parse_salary("15K") == (15000, None)


def test_parse_salary_variants():
    """_parse_salary handles various salary formats."""
    from agent_core.platforms.liepin import _parse_salary

    assert _parse_salary("8K-12K") == (8000, 12000)
    assert _parse_salary("20k-40k") == (20000, 40000)
    assert _parse_salary("25-35k·13薪") == (25000, 35000)
    assert _parse_salary("30k") == (30000, None)


def test_search_keyword_api_xsrf_extraction(monkeypatch):
    """_search_keyword_api correctly extracts XSRF-TOKEN from cookie string."""

    captured_headers = {}

    class FakeResp:
        @staticmethod
        def read():
            return json.dumps({"flag": 1, "data": {"data": {"jobCardList": []}}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        captured_headers["XSRF"] = req.headers.get("X-xsrf-token", "")
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = LiepinAdapter()
    asyncio.run(
        adapter._search_keyword_api(
            "AMR", "", "lt_auth=x; XSRF-TOKEN=extracted_token_via_cookie; other=y"
        )
    )
    assert captured_headers.get("XSRF") == "extracted_token_via_cookie"


def test_search_keyword_api_skip_card_on_error(monkeypatch):
    """_search_keyword_api logs and skips a card that causes exception during mapping."""

    fake_resp = json.dumps(
        {
            "flag": 1,
            "data": {
                "data": {
                    "jobCardList": [
                        {
                            "comp": {"compName": "Good Corp"},
                            "job": {
                                "title": "OK Job",
                                "salary": "10-15k",
                                "dq": "上海",
                                "link": "https://liepin.com/a/1",
                            },
                            "recruiter": {},
                        },
                        {
                            "comp": None,  # This will fail _api_item_to_job
                            "job": None,
                            "recruiter": None,
                        },
                    ]
                }
            },
        }
    ).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: FakeResp())

    adapter = LiepinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "", "lt_auth=x"))
    assert len(jobs) == 1  # Only the good card, bad one skipped
    assert jobs[0].company == "Good Corp"


def test_search_uses_rate_limit_param(monkeypatch):
    """search() updates _rate_limit_seconds when provided."""
    from agent_core.platforms import liepin

    # Simulate no cookies to avoid real API call
    monkeypatch.setattr(liepin, "_load_cookies", lambda p: [])

    adapter = LiepinAdapter(rate_limit_seconds=5.0)
    asyncio.run(adapter.search(["AMR"], "全国", cookie_path="/nonexistent", rate_limit_seconds=3.0))
    assert adapter._rate_limit_seconds == 3.0
