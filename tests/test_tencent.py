"""Tests for Tencent Careers adapter: response parsing, field mapping."""

import asyncio
import json

from agent_core.platforms.tencent import TencentAdapter, _parse_salary

# ── _parse_salary tests ──


def test_parse_salary_k_format():
    assert _parse_salary("15K-25K") == (15000, 25000)
    assert _parse_salary("8k-12k") == (8000, 12000)
    assert _parse_salary("20K") == (20000, None)


def test_parse_salary_wan_format():
    assert _parse_salary("1.5万-2.5万") == (15000, 25000)
    assert _parse_salary("8千-1.2万") == (8000, 12000)


def test_parse_salary_nianxin():
    assert _parse_salary("年薪30万") is not None
    mi, ma = _parse_salary("年薪30万")
    assert mi is not None and mi > 20000


def test_parse_salary_empty():
    assert _parse_salary("") == (None, None)
    assert _parse_salary(None) == (None, None)  # type: ignore[arg-type]


# ── _api_item_to_job tests ──


def make_tencent_post(
    recruit_post_name="AI Programmer",
    location_name="深圳",
    country_name="中国",
    bg_name="IEG",
    category_name="技术",
    responsibility="Design and implement AI systems.",
    post_id="2011285787706019840",
    post_url="https://careers.tencent.com/jobdesc.html?postId=2011285787706019840",
    years="三年以上工作经验",
):
    return {
        "Id": 0,
        "PostId": post_id,
        "RecruitPostId": 10002685,
        "RecruitPostName": recruit_post_name,
        "CountryName": country_name,
        "LocationName": location_name,
        "BGName": bg_name,
        "CategoryName": category_name,
        "Responsibility": responsibility,
        "LastUpdateTime": "2026年06月15日",
        "PostURL": post_url,
        "SourceID": 1,
        "IsCollect": False,
        "IsValid": True,
        "RequireWorkYearsName": years,
    }


def test_item_to_job_basic():
    adapter = TencentAdapter()
    post = make_tencent_post()
    job = adapter._api_item_to_job(post)

    assert job.title == "AI Programmer"
    assert job.company == "腾讯"
    assert "深圳" in job.location
    assert "IEG" in job.description
    assert "技术" in job.description
    assert "Design and implement AI systems" in job.description
    assert "三年以上工作经验" in job.description
    assert "tencent" in job.urls
    assert job.security_id == "2011285787706019840"


def test_item_to_job_overseas_location():
    adapter = TencentAdapter()
    post = make_tencent_post(
        recruit_post_name="AI Programmer",
        country_name="日本",
        location_name="东京",
    )
    job = adapter._api_item_to_job(post)
    assert "日本" in job.location
    assert "东京" in job.location


def test_item_to_job_no_salary():
    """Tencent list API doesn't include salary — verify None."""
    adapter = TencentAdapter()
    post = make_tencent_post()
    job = adapter._api_item_to_job(post)
    assert job.salary_min is None
    assert job.salary_max is None


def test_item_to_job_fallback_url():
    """When PostURL is empty, construct from postId."""
    adapter = TencentAdapter()
    post = make_tencent_post(post_url="", post_id="12345")
    job = adapter._api_item_to_job(post)
    assert "12345" in job.urls.get("tencent", "")


def test_item_to_job_tencent_with_bg():
    adapter = TencentAdapter()
    post = make_tencent_post(bg_name="TEG", category_name="产品")
    job = adapter._api_item_to_job(post)
    assert "BG: TEG" in job.description
    assert "类别: 产品" in job.description


# ── normalize tests ──


def test_normalize():
    adapter = TencentAdapter()
    job = adapter.normalize(
        {
            "id": "abc123",
            "title": "测试岗位",
            "company": "腾讯",
            "location": "深圳",
            "salary_min": None,
            "salary_max": None,
            "description": "测试描述",
            "url": "https://careers.tencent.com/123",
        }
    )
    assert job.id == "abc123"
    assert job.title == "测试岗位"
    assert "tencent" in job.platforms


# ── Search tests with mock ──


def make_tencent_items(*posts):
    """Build a fake Tencent API response."""
    return json.dumps(
        {
            "Code": 200,
            "Data": {
                "Count": len(posts),
                "Posts": list(posts),
            },
        }
    ).encode()


def test_search_parses_list(monkeypatch):
    """Search should parse results from Tencent API."""

    post = make_tencent_post(
        recruit_post_name="AI工程师",
    )

    class FakeResp:
        def read(self):
            return make_tencent_items(post)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = TencentAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert len(jobs) == 1
    assert jobs[0].title == "AI工程师"
    assert jobs[0].company == "腾讯"


def test_search_api_error_returns_empty(monkeypatch):
    """HTTP error should return empty list."""
    import urllib.error

    def fake_urlopen(req, timeout=20):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = TencentAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_search_non_200_code(monkeypatch):
    """Non-200 Code should return empty."""
    resp = json.dumps({"Code": 500, "Data": {"Count": 0, "Posts": []}}).encode()

    class FakeResp:
        def read(self):
            return resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = TencentAdapter(rate_limit_seconds=0)
    jobs = asyncio.run(
        adapter.search(
            keywords=["AI"],
            location="深圳",
            rate_limit_seconds=0,
        )
    )

    assert jobs == []


def test_rate_limit_default():
    adapter = TencentAdapter()
    assert adapter._rate_limit_seconds == 1.0


def test_rate_limit_custom():
    adapter = TencentAdapter(rate_limit_seconds=2.5)
    assert adapter._rate_limit_seconds == 2.5


def test_adapter_name():
    adapter = TencentAdapter()
    assert adapter.name == "tencent"
