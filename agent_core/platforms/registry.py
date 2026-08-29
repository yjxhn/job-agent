"""Central platform-adapter registry.

Replaces the repeated if/elif dynamic-import blocks in search.py,
enrichment.py and cookie_health.py. New adapters register once here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from agent_core.platforms.base import PlatformAdapter

# Each factory lazily imports its adapter class and constructs it with the
# shared PlatformConfig knobs. ``max_pages`` is the optional CLI override.
AdapterFactory = Callable[[Any, int | None], PlatformAdapter]

_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {}


def _register(name: str) -> Callable[[AdapterFactory], AdapterFactory]:
    def deco(fn: AdapterFactory) -> AdapterFactory:
        _ADAPTER_FACTORIES[name] = fn
        return fn

    return deco


def _adapter_kwargs(pc: Any, max_pages: int | None) -> dict[str, Any]:
    """Build constructor kwargs, omitting None values.

    Omitting None keeps legacy call sites (and tests that stub __init__ with
    no args) working while still passing real config through in production.
    """
    kwargs: dict[str, Any] = {}
    if pc is not None and getattr(pc, "rate_limit_seconds", None) is not None:
        kwargs["rate_limit_seconds"] = pc.rate_limit_seconds
    if max_pages is not None:
        kwargs["max_pages"] = max_pages
    if pc is not None and getattr(pc, "browser_profile_dir", None):
        kwargs["browser_profile_dir"] = pc.browser_profile_dir
    return kwargs


@_register("boss_zhipin")
def _boss_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    return BossZhipinAdapter(**_adapter_kwargs(pc, max_pages))


@_register("liepin")
def _liepin_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.liepin import LiepinAdapter

    return LiepinAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


@_register("zhilian")
def _zhilian_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.zhilian import ZhilianAdapter

    kwargs = _adapter_kwargs(pc, max_pages)
    if "browser_profile_dir" not in kwargs:
        kwargs["browser_profile_dir"] = "data/zhilian_browser_profile"
    return ZhilianAdapter(**kwargs)  # type: ignore[return-value]


@_register("tencent")
def _tencent_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.tencent import TencentAdapter

    return TencentAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


@_register("netease")
def _netease_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.netease import NeteaseAdapter

    return NeteaseAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


@_register("byd")
def _byd_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.byd import BydAdapter

    return BydAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


@_register("naura")
def _naura_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.naura import NauraAdapter

    return NauraAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


@_register("yofc")
def _yofc_factory(pc: Any, max_pages: int | None) -> PlatformAdapter:
    from agent_core.platforms.yofc import YofcAdapter

    return YofcAdapter(**_adapter_kwargs(pc, max_pages))  # type: ignore[return-value]


def create_adapter(
    platform: str,
    platform_config: Any = None,
    max_pages: int | None = None,
) -> PlatformAdapter:
    """Create an adapter instance for a registered platform key."""
    factory = _ADAPTER_FACTORIES.get(platform)
    if factory is None:
        raise KeyError(f"Platform adapter not registered: {platform}")
    return factory(platform_config, max_pages)


def is_registered(platform: str) -> bool:
    return platform in _ADAPTER_FACTORIES


def registered_platforms() -> list[str]:
    return list(_ADAPTER_FACTORIES.keys())


def make_job_id(platform: str, url: str) -> str:
    """Central stable job-id generator (md5 of platform+url, 16 hex chars)."""
    return hashlib.md5(  # nosec B324 -- job ID, not security
        f"{platform}:{url}".encode()
    ).hexdigest()[:16]
