"""Cookie health check: expiry analysis, regrab guides, and platform diagnostics.

Central module for all cookie-related user guidance. The CLI `check-cookies` command
and runtime empty-result diagnostics both source their regrab instructions from here,
so users always get consistent, actionable guidance.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

EXPIRY_WARNING_SECONDS = 7 * 86400  # 7 days


class CookieStatus(StrEnum):
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"  # within 7 days
    EXPIRED = "expired"
    MISSING = "missing"  # no cookie file
    NO_COOKIE_NEEDED = "no_cookie_needed"  # public API
    UNVERIFIED = "unverified"  # probe not run


# ---------------------------------------------------------------------------
# Platform cookie specifications
# ---------------------------------------------------------------------------


@dataclass
class PlatformCookieSpec:
    """Describes one platform's cookie requirements and key cookie names.

    ``cookie_path`` is mutable so callers (check_cookies) can override it
    with the config-specified path.
    """

    platform_key: str
    display_name: str
    needs_cookie: bool
    critical_cookies: set[str]  # key session-cookie names whose expiry we check
    cookie_path: str = ""  # relative to project root, e.g. "data/cookies/boss.json"

    @property
    def path_obj(self) -> Path:
        return Path(self.cookie_path)


# Map from platform config key to its cookie spec.
PLATFORM_SPECS: dict[str, PlatformCookieSpec] = {
    "boss_zhipin": PlatformCookieSpec(
        platform_key="boss_zhipin",
        display_name="boss 直聘",  # Boss直聘
        needs_cookie=True,
        critical_cookies={"wt2", "__zp_stoken__"},
        cookie_path="data/cookies/boss.json",
    ),
    "liepin": PlatformCookieSpec(
        platform_key="liepin",
        display_name="猎聘",  # 猎聘
        needs_cookie=True,
        critical_cookies={"lt_auth"},
        cookie_path="data/cookies/liepin.json",
    ),
    "zhilian": PlatformCookieSpec(
        platform_key="zhilian",
        display_name="智联招聘",  # 智联招聘
        needs_cookie=True,
        critical_cookies={"x-zp-client-id", "FSSBBIl1UgzbN7NS"},
        cookie_path="data/cookies/zhilian.json",
    ),
    "tencent": PlatformCookieSpec(
        platform_key="tencent",
        display_name="腾讯招聘",  # 腾讯招聘
        needs_cookie=False,
        critical_cookies=set(),
        cookie_path="",
    ),
    "netease": PlatformCookieSpec(
        platform_key="netease",
        display_name="网易招聘",  # 网易招聘
        needs_cookie=False,
        critical_cookies=set(),
        cookie_path="",
    ),
}

# ---------------------------------------------------------------------------
# Regrab guides -- single source of truth for all cookie-regrab instructions
# ---------------------------------------------------------------------------


def _regrab_guide_boss() -> str:
    return (
        "│ 【Boss直聘 重抓指引】\n"
        "│   1. Chrome 登录 zhipin.com 正常搜索浏览"
        "（刷新 __zp_stoken__）\n"
        "│   2. EditThisCookie 导出全部 cookie\n"
        "│   3. 覆盖 data/cookies/boss.json\n"
        "│   提示：__zp_stoken__ 短效（约数天），"
        "code:37 或 0 结果就重抓。\n"
        "│   命令：job-agent import-cookies <导出文件> boss_zhipin"
    )


def _regrab_guide_liepin() -> str:
    return (
        "│ 【猎聘 重抓指引】\n"
        "│   1. Chrome 登录 liepin.com\n"
        "│   2. EditThisCookie 导出（含 lt_auth）\n"
        "│   3. 覆盖 data/cookies/liepin.json\n"
        "│   命令：job-agent import-cookies <导出文件> liepin"
    )


def _regrab_guide_zhilian() -> str:
    return (
        "│ 【智联招聘 重抓指引】\n"
        "│   1. Chrome 访问 sou.zhaopin.com 正常搜索"
        "（让 Akamai sensor 活跃）\n"
        "│   2. F12 -> Network -> 找 /c/i/search/positions ->"
        " 右键 Copy as cURL (bash)\n"
        "│   3. 用 cURL 里的 cookie 刷新"
        " data/cookies/zhilian.json\n"
        "│   命令：job-agent import-cookies <cURL文件> zhilian"
        " --domain zhaopin.com\n"
        "│   提示：EditThisCookie 导出的 Akamai sensor"
        " 会被 shadowban；cURL 抓的活跃请求 cookie 才有效。\n"
        "│   Akamai 软封（count>0 但 list 空）就重抓 cURL；"
        "httpx 窗口期内有效，定期刷新。"
    )


def _regrab_guide_no_cookie(display_name: str) -> str:
    return f"│ 【{display_name}】\n" "│   公开 API，无需 cookie。"


REGRAB_GUIDES: dict[str, str] = {
    "boss_zhipin": _regrab_guide_boss(),
    "liepin": _regrab_guide_liepin(),
    "zhilian": _regrab_guide_zhilian(),
}


def get_regrab_guide(platform_key: str) -> str:
    """Return the regrab guide text for a platform (or a generic message)."""
    spec = PLATFORM_SPECS.get(platform_key)
    if spec is None:
        return f"│ 【{platform_key}】\n│   无重抓指引。"
    if not spec.needs_cookie:
        return _regrab_guide_no_cookie(spec.display_name)
    return REGRAB_GUIDES.get(platform_key, _regrab_guide_no_cookie(spec.display_name))


# ---------------------------------------------------------------------------
# Cookie file loading and parsing
# ---------------------------------------------------------------------------


def _load_cookie_file(cookie_path: str) -> list[dict] | None:
    """Load cookies from a Playwright-format JSON file. Returns None if missing/invalid."""
    p = Path(cookie_path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            cookies = json.load(f)
        if isinstance(cookies, list):
            return cookies
        logger.warning(f"Cookie file {cookie_path} is not a JSON array")
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load {cookie_path}: {e}")
        return None


def _parse_cookie_expiry(cookie: dict) -> tuple[float, str]:
    """Return (expires_timestamp, description) for a cookie.

    Handles both Playwright format (``expires``) and browser-export format
    (``expirationDate``).  Values <= 0 mean a session cookie with no explicit
    expiry.
    """
    exp = cookie.get("expires") or cookie.get("expirationDate") or -1
    try:
        exp = float(exp)
    except (TypeError, ValueError):
        exp = -1.0

    if exp <= 0:
        return exp, "session"
    return exp, ""


def _cookie_file_mtime(cookie_path: str) -> float | None:
    """Return the modification time (unix seconds) of a cookie file, or None."""
    p = Path(cookie_path)
    if not p.exists():
        return None
    return p.stat().st_mtime


# ---------------------------------------------------------------------------
# Health check result types
# ---------------------------------------------------------------------------


@dataclass
class CookieHealthResult:
    platform_key: str
    display_name: str
    status: CookieStatus
    file_exists: bool
    needs_cookie: bool
    details: list[str] = field(default_factory=list)
    regrab_guide: str = ""

    @property
    def status_icon(self) -> str:
        icons = {
            CookieStatus.VALID: "✅",  # ✅
            CookieStatus.EXPIRING_SOON: "⚠️",  # ⚠️
            CookieStatus.EXPIRED: "❌",  # ❌
            CookieStatus.MISSING: "❌",  # ❌
            CookieStatus.NO_COOKIE_NEEDED: "ℹ️",  # ℹ️
            CookieStatus.UNVERIFIED: "\U0001f512",  # 🔒
        }
        return icons.get(self.status, "?")

    @property
    def status_label(self) -> str:
        labels = {
            CookieStatus.VALID: "有效",  # 有效
            CookieStatus.EXPIRING_SOON: "即将过期",  # 即将过期
            CookieStatus.EXPIRED: "已过期",  # 已过期
            CookieStatus.MISSING: "缺失",  # 缺失
            CookieStatus.NO_COOKIE_NEEDED: "无需cookie",  # 无需cookie
            CookieStatus.UNVERIFIED: "需探活确认",  # 需探活确认
        }
        return labels.get(self.status, "未知")  # 未知


# ---------------------------------------------------------------------------
# Single-platform health check
# ---------------------------------------------------------------------------


def _check_single_platform(spec: PlatformCookieSpec) -> CookieHealthResult:
    """Check cookie health for one platform (no probe)."""
    result = CookieHealthResult(
        platform_key=spec.platform_key,
        display_name=spec.display_name,
        status=CookieStatus.MISSING,
        file_exists=False,
        needs_cookie=spec.needs_cookie,
        details=[],
        regrab_guide=get_regrab_guide(spec.platform_key),
    )

    if not spec.needs_cookie:
        result.status = CookieStatus.NO_COOKIE_NEEDED
        result.details.append("公开API，无需cookie")  # 公开API，无需cookie
        return result

    cookies = _load_cookie_file(spec.cookie_path)
    if cookies is None:
        result.status = CookieStatus.MISSING
        result.details.append(f"文件不存在: {spec.cookie_path}")  # 文件不存在
        return result

    result.file_exists = True
    now = time.time()
    cookie_map = {c.get("name", ""): c for c in cookies}
    total_count = len(cookies)

    result.details.append(f"共 {total_count} 个 cookie")  # 共 N 个 cookie

    # Check each critical cookie
    all_valid = True
    any_expiring = False
    any_expired = False
    critical_details: list[str] = []

    for name in sorted(spec.critical_cookies):
        c = cookie_map.get(name)
        if c is None:
            critical_details.append(f"缺失: {name}")  # 缺失
            all_valid = False
            any_expired = True
            continue

        exp, desc = _parse_cookie_expiry(c)
        if exp <= 0:
            if desc == "session":
                critical_details.append(f"{name}: session (未见显式过期)")
            else:
                critical_details.append(f"{name}: expires={exp}")
            continue

        remaining = exp - now
        exp_str = _format_expiry_time(exp)
        if remaining <= 0:
            critical_details.append(f"{name}: 已过期 ({exp_str})")  # 已过期
            all_valid = False
            any_expired = True
        elif remaining <= EXPIRY_WARNING_SECONDS:
            days_left = remaining / 86400
            critical_details.append(f"{name}: {days_left:.1f}天后过期 ({exp_str})")  # N天后过期
            all_valid = False
            any_expiring = True
        else:
            days_left = remaining / 86400
            critical_details.append(f"{name}: {days_left:.0f}天后过期 ({exp_str})")

    result.details.extend(critical_details)

    # Add file modification time
    mtime = _cookie_file_mtime(spec.cookie_path)
    if mtime is not None:
        result.details.append(f"文件修改: {_format_expiry_time(mtime)}")  # 文件修改

    if any_expired:
        result.status = CookieStatus.EXPIRED
    elif any_expiring:
        result.status = CookieStatus.EXPIRING_SOON
    elif not all_valid:
        result.status = CookieStatus.MISSING
    else:
        result.status = CookieStatus.VALID

    return result


def _format_expiry_time(ts: float) -> str:
    """Format a unix timestamp in ISO-ish local time."""
    import datetime

    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Probe: send a lightweight search request to confirm cookie works
# ---------------------------------------------------------------------------


async def _probe_platform(spec: PlatformCookieSpec, config_location: str) -> CookieHealthResult:
    """Probe a platform by sending one real search request.

    Returns an updated CookieHealthResult with probe findings appended.
    """
    result = _check_single_platform(spec)
    if not result.needs_cookie:
        return result
    if not result.file_exists:
        return result

    try:
        jobs: list[Any] = []
        if spec.platform_key == "boss_zhipin":
            from agent_core.platforms.boss_zhipin import BossZhipinAdapter

            boss_adapter = BossZhipinAdapter()
            jobs = await boss_adapter.search(
                keywords=["测试"],
                location=config_location,
                cookie_path=spec.cookie_path,
                rate_limit_seconds=30,
            )
        elif spec.platform_key == "liepin":
            from agent_core.platforms.liepin import LiepinAdapter

            liepin_adapter = LiepinAdapter()
            jobs = await liepin_adapter.search(
                keywords=["测试"],
                location=config_location,
                cookie_path=spec.cookie_path,
                rate_limit_seconds=30,
            )
        elif spec.platform_key == "zhilian":
            from agent_core.platforms.zhilian import ZhilianAdapter

            zhilian_adapter = ZhilianAdapter()
            jobs = await zhilian_adapter.search(
                keywords=["测试"],
                location=config_location,
                cookie_path=spec.cookie_path,
                rate_limit_seconds=30,
            )
        else:
            return result

        if jobs:
            result.details.append(f"探活成功: 返回 {len(jobs)} 个职位")  # 探活成功: 返回 N 个职位
            # If file check found issues but probe works, don't downgrade
        else:
            result.details.append(
                "探活返回 0 个职位（可能软封或 cookie 失效）"
            )  # 探活返回 0 个职位
            if result.status == CookieStatus.VALID:
                result.status = CookieStatus.UNVERIFIED
    except Exception as e:
        # Don't log a full stack trace to avoid confusion; the probe is best-effort
        result.details.append(f"探活失败: {e}")  # 探活失败
        logger.info(f"[cookie_health] Probe failed for {spec.platform_key}: {e}")

    return result


# ---------------------------------------------------------------------------
# Main entry point: check all enabled platforms
# ---------------------------------------------------------------------------


async def check_cookies(config: Any, probe: bool = False) -> list[CookieHealthResult]:
    """Check cookie health for all enabled platforms.

    Args:
        config: The project Config object (from config.py).
        probe: If True, send one real search request per platform to confirm
               the cookie actually works (detects soft bans, count=0, etc.).
               Default False — Boss tokens are short-lived, avoid wasting them.

    Returns:
        A list of CookieHealthResult, one per enabled platform.
    """
    import copy as _copy

    results: list[CookieHealthResult] = []

    for pname, pc in config.platforms.items():
        if not pc.enabled:
            continue

        spec = PLATFORM_SPECS.get(pname)
        if spec is None:
            results.append(
                CookieHealthResult(
                    platform_key=pname,
                    display_name=pname,
                    status=CookieStatus.UNVERIFIED,
                    file_exists=False,
                    needs_cookie=True,
                    details=[f"未知平台: {pname}"],
                    regrab_guide="",
                )
            )
            continue

        # Use config-provided cookie_path; spec has a sensible default.
        spec_copy = _copy.copy(spec)
        if pc.cookie_path:
            spec_copy.cookie_path = pc.cookie_path

        if probe and spec_copy.needs_cookie:
            r = await _probe_platform(spec_copy, config.search_location)
        else:
            r = _check_single_platform(spec_copy)

        results.append(r)

    return results


# ---------------------------------------------------------------------------
# Runtime diagnosis: called after search/pipeline returns 0 results
# ---------------------------------------------------------------------------


def diagnose_empty_results(config: Any) -> str | None:
    """Check cookie health and return a user-facing diagnostic message.

    Called from CLI after a search/pipeline returns 0 jobs.  Uses only sync
    file checks (no network/async) so it is safe to call from within an
    existing ``asyncio.run()`` context.
    """
    import copy as _copy

    issues: list[CookieHealthResult] = []

    for pname, pc in config.platforms.items():
        if not pc.enabled:
            continue

        spec = PLATFORM_SPECS.get(pname)
        if spec is None or not spec.needs_cookie:
            continue

        spec_copy = _copy.copy(spec)
        if pc.cookie_path:
            spec_copy.cookie_path = pc.cookie_path

        r = _check_single_platform(spec_copy)
        if r.status in (CookieStatus.EXPIRED, CookieStatus.MISSING):
            issues.append(r)

    if not issues:
        return None

    lines: list[str] = []
    lines.append("")
    lines.append("┌" + "─" * 58 + "┐")
    lines.append("│  ⚠️  搜索返回 0 个职位" "，检测到 cookie 问题：")
    lines.append("│")

    for r in issues:
        lines.append(f"│  {r.status_icon} {r.display_name}: {r.status_label}")
        for detail in r.details:
            lines.append(f"│     {detail}")

    lines.append("│")
    lines.append("│  请按以下步骤重新抓取 cookie：")

    for r in issues:
        if r.regrab_guide:
            lines.append(r.regrab_guide)

    lines.append("│")
    lines.append("│  重抓后重跑: python -m agent_core.cli search")
    lines.append("└" + "─" * 58 + "┘")
    lines.append("")

    return "\n".join(lines)
