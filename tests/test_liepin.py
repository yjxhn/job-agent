"""Tests for Liepin platform: HTTP API adapter."""

import asyncio
import json
import pytest

from agent_core.platforms.liepin import LiepinAdapter


def test_liepin_search_parses_jobcards(monkeypatch):
    """Test that search correctly parses jobCardList from API response."""
    from agent_core.platforms import liepin

    # Monkeypatch cookie helpers to return valid cookie
    def fake_load_cookies(p):
        return [{"name": "lt_auth", "value": "x", "expires": -1},
                {"name": "XSRF-TOKEN", "value": "tok"}]

    def fake_session_valid(c):
        return True

    # Track _notify_cookie_expired calls
    cookie_expired_called = []

    def fake_notify_cookie_expired():
        cookie_expired_called.append("猎聘")

    # Mock API response with one job card
    fake_resp = json.dumps({
        "flag": 1,
        "data": {
            "data": {
                "jobCardList": [{
                    "comp": {
                        "compName": "某公司",
                        "compScale": "100-499人",
                        "compIndustry": "机械/设备",
                        "compStage": "B轮"
                    },
                    "job": {
                        "title": "AMR工程师",
                        "jobId": "123",
                        "salary": "15-20k·13薪",
                        "dq": "苏州-常熟",
                        "link": "https://www.liepin.com/a/123.shtml",
                        "requireWorkYears": "3-5年",
                        "requireEduLevel": "本科",
                        "labels": ["ROS"]
                    },
                    "recruiter": {
                        "recruiterName": "张三",
                        "recruiterTitle": "HR"
                    }
                }]
            }
        }
    }).encode()

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
    assert cookie_expired_called == [], f"Cookie expired should NOT be called, got {cookie_expired_called}"


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
            "compStage": "C轮"
        },
        "job": {
            "title": "算法工程师",
            "jobId": "job456",
            "salary": "25-35k",
            "dq": "北京-海淀",
            "link": "https://www.liepin.com/a/456.shtml",
            "requireWorkYears": "5-10年",
            "requireEduLevel": "硕士",
            "labels": ["Python", "机器学习"]
        },
        "recruiter": {
            "recruiterName": "李四",
            "recruiterTitle": "技术HR"
        }
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
    fake_resp = json.dumps({
        "flag": 0,
        "msg": "未登录",
        "data": {}
    }).encode()

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
    assert cookie_expired_called == ["猎聘"], f"Expected cookie expired called, got {cookie_expired_called}"