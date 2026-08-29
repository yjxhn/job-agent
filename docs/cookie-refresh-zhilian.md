# 智联招聘 Cookie 重抓 SOP

> 适用范围：`agent-core` 求职 AI Agent 项目
> 目标平台：zhilian（智联招聘）
> 关联命令：`job-agent check-cookies`、`job-agent search`

## 前置说明

### 为什么不能用 EditThisCookie

智联招聘的 fe-api 搜索端点（`fe-api.zhaopin.com/c/i/search/positions`）使用 **at/rt token 认证**，不依赖旧的 Akamai sensor cookie（`FSSBBIl1UgzbN7NS`）。

EditThisCookie 扩展导出的 cookie 虽然包含所有 cookie，但导出的 `FSSBBIl1UgzbN7NS` 等 Akamai sensor 在非浏览器环境中可能因缺少 JavaScript sensor 指纹而失效。项目代码已确认 fe-api 端点只需有效的 `at`（access token）和 `rt`（refresh token），因此改用 cURL 方式直接从活跃的 HTTP 请求中提取这些 token。

### 为什么必须用 cURL

- fe-api 端点通过 `at`/`rt` 认证，这两个 token 在每次浏览器请求中通过 Cookie header 发送
- 从 Network 面板 Copy as cURL 可以直接拿到**活跃请求中的完整 Cookie header**，包含浏览器实时使用的 `at`/`rt` 值
- 此方法不依赖任何浏览器扩展，也不需要理解 Akamai sensor 机制
- `at`/`rt` 是会话级 token，过期后需重抓；通常有效期几天到几周

### 关键 Cookie 说明

| Cookie | 说明 | 必需 |
|--------|------|------|
| `at` | Access token，fe-api 端点认证主 token | 是 |
| `rt` | Refresh token，配合 at 使用 | 是 |
| `x-zp-client-id` | 客户端设备标识 | 是 |
| `x-zp-device-sn` | 设备序列号 | 推荐 |
| `FSSBBIl1UgzbN7NS` | 旧 Akamai sensor cookie | **不需要** |

---

## 步骤 1：Chrome 登录并搜索

1. 打开 Chrome，访问 https://www.zhaopin.com
2. 登录你的智联账号（手机验证码或扫码均可）
3. 登录后在首页搜索框中输入一个关键词（如 "AMR"、"Java"、"前端"），选择城市，点击搜索
4. 等待搜索结果页面加载完成（确认能看到职位列表）
5. 可选：翻页浏览 1-2 页，让 cookie 保持活跃状态

---

## 步骤 2：获取 cURL 请求

1. 保持在 zhaopin.com 搜索结果页面上
2. 按 `F12` 打开 Chrome DevTools
3. 切换到 **Network**（网络）面板
4. 在 Filter 输入框中输入 `search/positions` 过滤请求
5. 找到 `fe-api.zhaopin.com/c/i/search/positions` 这个 POST 请求
   - 方法列显示 `POST`，Status 显示 `200`
6. **右键点击**该请求 -> **Copy** -> **Copy as cURL (bash)**

![Network 面板中找到 fe-api.zhaopin.com/c/i/search/positions 请求，右键 Copy as cURL (bash)](暂无截图，按步骤描述操作即可)

7. 将复制的 cURL 命令粘贴到一个临时文本文件中（如 `zhilian_curl.txt`）

> 注意：cURL 命令会很长（几百字符），包含大量 cookie。这是正常的。关键是其中的 `-b` 参数。

---

## 步骤 3：从 cURL 提取 Cookie 并生成 JSON

### 3.1 理解 cURL 中的 Cookie 格式

cURL 命令中的 cookie 格式如下（脱敏示例）：

```bash
curl 'https://fe-api.zhaopin.com/c/i/search/positions' \
  -H 'cookie: at=abc123; rt=def456; x-zp-client-id=ghi789; x-zp-device-sn=jkl012; HMACCOUNT=...; ...' \
  ...
```

你只需要提取 `-H 'cookie: ...'` 或 `-b '...'` 中的 cookie 字符串。

### 3.2 将 Cookie 字符串转为 JSON 数组

项目中 `import-cookies` 命令目前**只支持 JSON 数组格式**（即 Cookie-Editor 导出的格式），不支持直接解析 cURL。

你需要手动将 cURL 中的 cookie 转成 JSON 数组格式，或直接编辑 `data/cookies/zhilian.json`。

以下是一个可复制的操作方式：

**方式 A：用 Python 一键转换（推荐）**

在项目目录下创建临时脚本 `_curl_to_json.py`（用完删除）：

```python
"""一次性脚本：将 cURL 的 cookie 转为 data/cookies/zhilian.json。用完删除。"""
import json, re, sys, time

curl_text = sys.stdin.read()
# 提取 cookie header 的值
m = re.search(r"(?:-b|-H\s+'cookie:)\s+'([^']+)'", curl_text)
if not m:
    m = re.search(r'(?:-b|-H\s+"cookie:)\s+"([^"]+)"', curl_text)
if not m:
    print("错误：未找到 cookie header，请确认复制的是完整的 cURL 命令")
    sys.exit(1)

cookie_str = m.group(1)
pairs = [p.strip().split("=", 1) for p in cookie_str.split(";") if "=" in p]

# 只保留 fe-api 端点实际需要的认证 cookie，过滤掉：
# - FSSBBIl1UgzbN7N* (Akamai sensor，会导致软封)
# - EO-Bot-* (EdgeOne 机器人检测 token)
# - sensorsdata*, HM*, ZL_REPORT_*, LastCity* 等分析/UI cookie
ESSENTIAL = {"at", "rt", "x-zp-client-id", "x-zp-device-sn"}
future = int(time.time()) + 86400 * 365  # 1 年后过期（占位值）
cookies = []
for name, value in pairs:
    if name not in ESSENTIAL:
        continue
    cookies.append({
        "name": name,
        "value": value,
        "domain": ".zhaopin.com",
        "path": "/",
        "expires": future,
        "httpOnly": False,
        "secure": True,
        "sameSite": "Lax",
    })

with open("data/cookies/zhilian.json", "w", encoding="utf-8") as f:
    json.dump(cookies, f, ensure_ascii=False, indent=2)

names = {c["name"] for c in cookies}
for required in ["at", "rt", "x-zp-client-id"]:
    status = "OK" if required in names else "缺失!"
    print(f"  {required}: {status}")
skipped = len(pairs) - len(cookies)
if skipped:
    print(f"已过滤 {skipped} 个非必要 cookie（EO-Bot/Akamai sensor/分析等）")
print(f"共 {len(cookies)} 个 cookie 写入 data/cookies/zhilian.json")
```

使用方式：
```powershell
# PowerShell：运行脚本，粘贴 cURL 内容，按 Ctrl+Z 然后 Enter 结束输入
python _curl_to_json.py
# 删除临时脚本
Remove-Item _curl_to_json.py
```


**方式 B：手动编辑**

1. 备份现有文件：`Copy-Item data/cookies/zhilian.json data/cookies/zhilian.json.bak`
2. 从 cURL 的 `-b '...'` 或 `-H 'cookie: ...'` 中提取 `name=value; name=value; ...` 字符串
3. 手动构建 JSON 数组（每个 cookie 一条记录）：

```json
[
  {
    "name": "at",
    "value": "你的at值",
    "domain": ".zhaopin.com",
    "path": "/",
    "expires": 1783200000,
    "httpOnly": false,
    "secure": true,
    "sameSite": "Lax"
  },
  {
    "name": "rt",
    "value": "你的rt值",
    "domain": ".zhaopin.com",
    "path": "/",
    "expires": 1783200000,
    "httpOnly": false,
    "secure": true,
    "sameSite": "Lax"
  },
  {
    "name": "x-zp-client-id",
    "value": "你的client-id值",
    "domain": ".zhaopin.com",
    "path": "/",
    "expires": 1783200000,
    "httpOnly": false,
    "secure": true,
    "sameSite": "Lax"
  },
  {
    "name": "x-zp-device-sn",
    "value": "你的device-sn值",
    "domain": ".zhaopin.com",
    "path": "/",
    "expires": 1783200000,
    "httpOnly": false,
    "secure": true,
    "sameSite": "Lax"
  }
]
```

4. `expires` 填入未来时间戳（如 `int(time.time()) + 86400*365`），项目只检查是否过期（> 当前时间即可），不需要精确值
5. `domain` 统一用 `.zhaopin.com`，`path` 用 `/`，`sameSite` 用 `Lax`
6. 保存文件

### 3.3 验证 JSON 格式

```powershell
python -c "import json; json.load(open('data/cookies/zhilian.json')); print('JSON OK')"
```

---

## 步骤 4：备份并覆盖 Cookie 文件

```powershell
# 备份旧文件
Copy-Item data/cookies/zhilian.json data/cookies/zhilian.json.bak

# 确认新文件的关键 cookie 存在
python -c "
import json
cookies = json.load(open('data/cookies/zhilian.json'))
names = {c['name'] for c in cookies}
for k in ['at', 'rt', 'x-zp-client-id']:
    print(f'{k}: {\"OK\" if k in names else \"缺失!\"}')"
```

---

## 步骤 5：验证

### 方式 A：探活确认

```powershell
job-agent check-cookies --probe
```

关注智联行输出：如果显示 "探活成功: 返回 N 个职位"（N > 0）则 cookie 有效。如果显示 "探活返回 0 个职位" 说明 `at`/`rt` 可能已失效，回到步骤 1 重新抓取。

### 方式 B：直接搜索

```powershell
job-agent search
```

观察智联日志行：应该显示 `'keyword': N jobs (total=M)` 且 N > 0。

---

## 常见问题

### Q1: 为什么 check-cookies --probe 返回 0 个职位？

可能原因按顺序排查：

1. `at`/`rt` cookie 值不对 —— 检查是否从正确的 cURL 中提取（必须是 `fe-api.zhaopin.com/c/i/search/positions` 这个请求，不是其他 zhaopin.com 请求）
2. `at`/`rt` 已过期 —— 这些是会话级 token，通常几天到几周后失效。回到步骤 1 在浏览器中重新搜索一次，获取新的 cURL
3. 搜索关键词太偏 —— 尝试用 "测试" 作为关键词

### Q2: 为什么不直接用 `job-agent import-cookies` 命令？

项目中的 `import-cookies` 命令目前只支持 Cookie-Editor / EditThisCookie 导出的 JSON 数组格式。cURL 格式需要手动转换（可按步骤 3.2 中的 Python 脚本一键完成）。

### Q3: cookie 多久需要重新抓取？

`at`/`rt` 是会话级 token，通常在几天到几周内有效。建议：
- 每天运行 `job-agent check-cookies --probe` 检查状态
- 遇到返回 0 职位时按本文重新抓取

### Q4: 为什么不需要 FSSBBIl1UgzbN7NS（Akamai sensor）？

项目使用的 fe-api.zhaopin.com 搜索端点通过 `at`/`rt` token 认证，不依赖 Akamai sensor。旧的 Akamai sensor 在非浏览器环境中（没有 JavaScript 执行环境）也无效。因此项目代码不再检查或要求这个 cookie。

### Q5: 可以用 Firefox 或其他浏览器吗？

可以。只要能从 DevTools Network 面板复制 cURL 命令即可。Firefox 的右键菜单中也有 "Copy as cURL" 选项。

### Q6: 如果 cURL 中没有 -b cookie header，而是 -H 'cookie: ...'？

格式不同但内容相同。步骤 3.2 中的 Python 脚本兼容两种格式（`-b '...'` 和 `-H 'cookie: ...'`）。

### Q7: 搜索成功但能用的关键词有限制吗？

智联 API 每次搜索返回最多 20 条结果。项目代码对每个关键词单独请求一次，建议每次用 2 个关键词以获取更全面的结果。

---

## 快速检查清单

- [ ] Chrome 登录 zhaopin.com 成功
- [ ] 搜索关键词并确认结果页面有职位列表
- [ ] F12 Network 中找到 `fe-api.zhaopin.com/c/i/search/positions` POST 请求
- [ ] 右键 Copy as cURL (bash) 成功
- [ ] 从 cURL 提取的 cookie 包含 `at`、`rt`、`x-zp-client-id`
- [ ] 已备份旧文件 `zhilian.json.bak`
- [ ] 新的 `data/cookies/zhilian.json` 是有效 JSON 数组
- [ ] `job-agent check-cookies --probe` 显示 "探活成功" 且返回职位数 > 0
- [ ] `job-agent search` 智联日志显示 N > 0 jobs

> 注：cookie 文件路径在 `config.yaml` 的 `platforms.zhilian.cookie_path`（默认 `data/cookies/zhilian.json`），与导入工具输出名（`zhilian.json`）一致。cURL 手动转换方式也写入同一路径。
