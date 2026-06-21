# -*- coding: utf-8 -*-
"""
将浏览器扩展导出的 cookie JSON 转成 Playwright/项目格式，写入 data/cookies/<platform>.json。

使用场景：Boss直聘等强反爬站点，Playwright 自动登录被拦截。改为：
  1. 在你日常 Chrome 里正常登录目标站点
  2. 用 Cookie-Editor 等扩展导出该域名 cookie 为 JSON（Export → JSON）
  3. 保存为例如 data/cookies/boss_export.json
  4. 运行: python import_cookies.py <export.json> <platform> [--domain zhipin.com]

输入格式（Cookie-Editor / EditThisCookie 通用）：
  [{"name":"x","value":"y","domain":".zhipin.com","path":"/",
    "expirationDate":1234567890,"secure":true,"httpOnly":true,"sameSite":"Lax"}, ...]

输出格式（Playwright add_cookies）：
  [{"name","value","domain","path","expires","secure","httpOnly","sameSite"}, ...]
"""

import os
import sys

# Add project root to sys.path to import cookie_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_core.platforms.cookie_utils import convert_and_save


def main():
    if len(sys.argv) < 3:
        print("用法: python import_cookies.py <export.json> <platform> [--domain zhipin.com]")
        print("示例: python import_cookies.py data/cookies/boss_export.json boss --domain zhipin.com")
        sys.exit(1)

    export_path = sys.argv[1]
    platform = sys.argv[2]
    domain_filter = ""
    if "--domain" in sys.argv:
        domain_filter = sys.argv[sys.argv.index("--domain") + 1]

    try:
        result = convert_and_save(export_path, platform, domain_filter)
        print(f"[OK] {result['count']} cookies -> {result['out_path']}")
        print(f"     session cookies found: {result['session_found'] if result['session_found'] else '(none)'}")
        if result['session_found']:
            print("     [OK] 登录态 cookie 存在，可尝试运行搜索。")
        else:
            print("     [WARN] 未发现已知 session cookie。")
            print("            请确认：1) 导出前已在浏览器登录该站点；")
            print("            2) 在 zhipin.com 页面上点导出（不是地址栏扩展图标单独导一条）；")
            print("            3) 导出文件应为几十条 cookie 的数组，不是单条。")
    except (ValueError, FileNotFoundError) as e:
        print(f"[FAIL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()