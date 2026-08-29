"""Tests for the central platform-adapter registry."""

from types import SimpleNamespace

import pytest

from agent_core.platforms.registry import (
    create_adapter,
    is_registered,
    make_job_id,
    registered_platforms,
)


def test_registered_platforms_include_live_adapters():
    names = registered_platforms()
    for expected in (
        "boss_zhipin",
        "liepin",
        "zhilian",
        "tencent",
        "netease",
        "byd",
        "naura",
        "yofc",
    ):
        assert expected in names


def test_is_registered_unknown():
    assert not is_registered("not_a_platform")


def test_create_adapter_with_config_passes_max_pages():
    pc = SimpleNamespace(rate_limit_seconds=7, search_max_pages=2)
    adapter = create_adapter("tencent", pc, max_pages=2)
    assert adapter is not None
    assert adapter.max_pages == 2


def test_create_adapter_without_config_uses_defaults():
    adapter = create_adapter("tencent")
    assert adapter is not None


def test_create_adapter_unknown_raises():
    with pytest.raises(KeyError):
        create_adapter("not_a_platform")


def test_make_job_id_stable():
    a = make_job_id("boss_zhipin", "https://example.com/job/1")
    b = make_job_id("boss_zhipin", "https://example.com/job/1")
    c = make_job_id("boss_zhipin", "https://example.com/job/2")
    assert a == b
    assert a != c
    assert len(a) == 16
