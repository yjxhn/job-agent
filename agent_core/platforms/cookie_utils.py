"""Cookie format conversion: browser-export JSON -> Playwright-format cookie file.

Shared by the `job-agent import-cookies` CLI command and the standalone
`import_cookies.py` script.
"""

import json
from pathlib import Path

# Known session-cookie names per platform (for sanity checks after import).
SESSION_COOKIES = {
    "boss_zhipin": {"wt2", "wbg", "boss_token", "__zp_stoken__"},
    "liepin": {"lt_auth", "lt_auth_v2", "XSRF-TOKEN"},
}


def convert(exported: list, domain_filter: str = "") -> list:
    """Convert browser-exported cookies to Playwright add_cookies format."""
    out = []
    for c in exported:
        domain = c.get("domain", "")
        if domain_filter and domain_filter not in domain:
            continue
        same = (c.get("sameSite") or "Lax").capitalize()
        if same not in ("Strict", "Lax", "None"):
            same = "Lax"
        out.append({
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": domain,
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate") or c.get("expires") or -1,
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": same,
        })
    return out


def convert_and_save(export_path: str, platform: str, domain_filter: str = "") -> dict:
    """Convert an exported cookie file and write the platform cookie file.

    Returns a dict: {count, session_found, out_path, platform}.
    Raises ValueError on bad input / no cookies.
    """
    with open(export_path, encoding="utf-8") as f:
        exported = json.load(f)
    if not isinstance(exported, list):
        raise ValueError(
            f"导出文件应为 JSON 数组，实际类型: {type(exported).__name__}")

    cookies = convert(exported, domain_filter)
    if not cookies:
        raise ValueError(
            f"转换后 0 条 cookie（domain 过滤 '{domain_filter}' 是否正确？）")

    out_path = Path("data/cookies") / f"{platform}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    session_keys = SESSION_COOKIES.get(platform, set())
    found = sorted({c["name"] for c in cookies} & session_keys)
    return {"count": len(cookies), "session_found": found,
            "out_path": str(out_path), "platform": platform}
