# BOSS直聘 Cookie 重抓 SOP

> 适用范围：`agent-core` 求职 AI Agent 项目  
> 目标平台：boss_zhipin（BOSS直聘）  
> 关联命令：`job-agent import-cookies`、`job-agent check-cookies`

## 前置说明

### 为什么不能 Playwright 自动登录

BOSS直聘服务端检测 CDP（Chrome DevTools Protocol）协议。一旦识别出浏览器是由 Playwright/Puppeteer 等自动化工具启动的，服务端会直接返回空白页或重定向，无法正常渲染任何页面。项目代码已确认这一点（`boss_zhipin.py` 的 `boss_login()` 函数直接返回 `False`，提示用户手动导出 cookie）。

因此项目改用**直接 HTTP API 调用**方式：读取保存的 cookie，以 HTTP header 形式附加到 API 请求中，不经过浏览器。

### 为什么 cookie 会过期

BOSS直聘的关键 session cookie 有两类：

| Cookie | 有效期 | 说明 |
|--------|--------|------|
| `wt2` | 约 30 天 | 主登录态 token，过期后 API 直接拒绝请求 |
| `__zp_stoken__` | 数天（短效） | 反爬安全 token，过期后搜索 API 返回 `code:37` 或空结果 |

另外，`__zp_stoken__` **必须通过真实浏览行为触发刷新**。只登录不浏览，这个 token 不会生成或更新。因此每次重抓时需要完成"登录 + 搜索浏览"两步骤。

### 反爬信号 code 37

当搜索 API 返回 `"code":37` 时，表示触发了 BOSS 直聘的反爬挑战。代码检测逻辑（`boss_zhipin.py` 第 196-214 行）：

- `code == 37` 或 `zpData` 中包含 `seed`/`name`/`ts` 字段
- 触发后自动等待 120 秒退避，避免重复被封
- 极端情况下 `__zp_stoken__` 即使有效也会触发，说明需要更新 cookie

---

## 步骤 1：Chrome 准备

**建议使用无痕窗口或干净的 Chrome profile**，减少已有 CDP 检测痕迹的干扰。

1. 关闭所有 Chrome 窗口
2. 打开 Chrome **无痕窗口**（`Ctrl+Shift+N`）—— 或者用一个不常跑自动化脚本的 profile
3. 安装 **Cookie-Editor** 扩展（Chrome Web Store 搜索 "Cookie-Editor"）—— 如果已有可跳过
4. 确认 Cookie-Editor 扩展图标出现在工具栏

> 如果能正常使用日常 Chrome 且没有触发过 BOSS 反爬，也可以直接用日常 profile，但要确保已退出之前的登录态后再重新登录。

---

## 步骤 2：登录并触发搜索

这一步的关键是**不仅登录，还要真实浏览搜索结果页**，让 `__zp_stoken__` 自然刷新。

1. 打开 https://www.zhipin.com
2. 点击右上角 "登录" 按钮
3. 用你的账号完成登录（手机验证码或微信扫码均可）
4. 登录成功后，在首页搜索框中输入一个关键词（如 "前端"、"后端"、"产品经理"），选择城市，点击搜索
5. **翻页浏览至少 2-3 页搜索结果**（这是关键步骤，让 `__zp_stoken__` 生成）
6. 可选：点进几个职位详情页，进一步增强 cookie 的"真人浏览"特征

---

## 步骤 3：导出 Cookie

### 代码接受的格式

项目代码 `cookie_utils.py` 中的 `convert()` 函数接受 **Cookie-Editor / EditThisCookie 导出的 JSON 数组格式**：

```json
[
  {
    "name": "wt2",
    "value": "D...",
    "domain": ".zhipin.com",
    "path": "/",
    "expirationDate": 1783191600.022548,
    "httpOnly": true,
    "secure": false,
    "sameSite": "Lax"
  }
]
```

关键字段：`name`、`value`、`domain`、`path`、`expirationDate`（浏览器格式）或 `expires`（Playwright 格式均可）、`httpOnly`、`secure`、`sameSite`

### 导出步骤

1. 保持在 zhipin.com 页面上（不要切换到其他网站）
2. 点击 Chrome 工具栏的 **Cookie-Editor** 图标
3. 确认弹出面板左上角域名显示为 `zhipin.com`
4. 点击面板右下方的 **Export** 按钮（向下箭头图标）
5. 在弹出的 Export 对话框中，确认格式为 **JSON**
6. 点击 **Copy** 按钮
7. 在项目目录下创建新文件：
   ```powershell
   # PowerShell：将剪贴板中的 JSON 保存为 UTF-8 文件
   Get-Clipboard | Set-Content -Encoding UTF8 data/cookies/boss_export.json
   ```
8. 确认文件是有效的 JSON 数组（开头是 `[`，包含几十条 cookie）

### 验证导出质量

在保存前确认导出的 JSON 中包含以下关键 cookie：

- `wt2` — 主登录态
- `__zp_stoken__` — 反爬安全 token
- `wbg` — BOSS 网关 token
- `boss_token` — BOSS 平台 token

可以用以下命令快速检查（PowerShell 或 bash 均可）：
```powershell
python -c "import json; cookies=json.load(open('data/cookies/boss_export.json')); names={c['name'] for c in cookies}; print('缺失wt2' if 'wt2' not in names else 'wt2 OK'); print('缺失__zp_stoken__' if '__zp_stoken__' not in names else '__zp_stoken__ OK')"
```

---

## 步骤 4：导入 Cookie

### 方式 A：CLI 命令（推荐）

```powershell
job-agent import-cookies data/cookies/boss_export.json boss_zhipin
```

不需要 `--domain` 参数，因为 Cookie-Editor 在 zhipin.com 页面上导出时，导出的 JSON 自然只包含该域名的 cookie。

### 方式 B：独立脚本

```powershell
python scripts/import_cookies.py data/cookies/boss_export.json boss_zhipin
```

### 成功输出示例

```
[OK] 42 cookies -> data\cookies\boss_zhipin.json
     session cookies: ['__zp_stoken__', 'boss_token', 'wbg', 'wt2']
     [OK] 登录态 cookie 存在。
```

如果输出 `[WARN] 未发现已知 session cookie`，说明导出有问题，回到步骤 3 重新导出。

---

## 步骤 5：验证

### 方式 A：检查 cookie 健康状态

```powershell
job-agent check-cookies
```

这会显示每个平台关键 cookie 的过期时间。对于 boss_zhipin，关注 `wt2` 和 `__zp_stoken__` 是否都显示有效。

### 方式 B：探活（可选，会消耗一次搜索请求）

```powershell
job-agent check-cookies --probe
```

加上 `--probe` 参数会实际发送一次搜索请求确认 cookie 有效。成功时显示 "探活成功: 返回 N 个职位"。

### 方式 C：直接执行搜索

```powershell
job-agent search
```

观察日志输出：
- `API code=0` — 搜索正常，cookie 有效
- `API code=37` — 触发反爬，cookie 有问题，需要 120 秒退避后重试或重新抓取
- `No cookie at data/cookies/boss_zhipin.json` — 文件路径不对或导入失败

---

## 常见问题

### Q1: 出现 code 37 反爬怎么办？

1. 程序已内置 120 秒退避机制，等 2 分钟
2. 如果重试后仍然 code 37：
   - 按本文步骤重新抓取 cookie（特别是 `__zp_stoken__` 过期了）
   - 确保步骤 2 中确实浏览了搜索结果页（这是生成 `__zp_stoken__` 的必要步骤）
3. 如果反复出现，考虑换一个 Chrome profile 或等 1-2 小时再试

### Q2: 搜索返回 0 个职位但 code 为 0 是什么情况？

可能是搜索条件太严格或该城市真的没有匹配职位。尝试用更宽泛的关键词（如 "测试"）配合 `job-agent check-cookies --probe` 探活确认。

### Q3: 可以用别的浏览器（Firefox、Edge）吗？

可以。只要能用 Cookie-Editor 扩展导出 JSON 格式即可。但 BOSS 的反爬检测对 Chrome 更友好，建议优先使用 Chrome。

### Q4: Cookie-Editor 导出的 cookie 会被 shadowban 吗？

对于 BOSS 直聘，Cookie-Editor 导出是常规方案，项目目前使用此方式未发现额外风险。关键在于 cookie 来自**真实 Chrome 浏览行为**（不是在自动化浏览器中导出的）。

### Q5: 为什么必须用真实浏览器，不能用 Playwright 绕过 CDP 检测？

Playwright 的 CDP 检测是在底层协议级别的。即使修改 User-Agent、WebDriver 标记等，BOSS 服务端能从连接握手阶段识别 CDP 客户端。如果未来需要自动化，可考虑使用 `undetected-chromedriver` 等方案，但目前手动导出 cookie 是最可靠的方式。

### Q6: wt2 和 __zp_stoken__ 的过期时间各是多少？多久需要重新抓一次？

- `wt2`：约 30 天，过期后必须重新登录
- `__zp_stoken__`：通常 1-7 天，取决于浏览行为。如果不频繁使用，可能 2-3 天就过期

建议：每天运行 `job-agent check-cookies` 检查状态；每周或遇到 code 37 时按本文重新抓取。

### Q7: 导出时 Cookie-Editor 面板左上角显示的不是 zhipin.com 怎么办？

这说明你当前不在 zhipin.com 页面上。务必**先在 zhipin.com 页面上点击 Cookie-Editor 图标**，不要在空白标签页或其他网站上操作。如果已登录 zhipin.com 但左上角仍不对，刷新页面后再试。

---

## 快速检查清单

- [ ] Chrome 无痕窗口或干净 profile
- [ ] 登录 zhipin.com 成功
- [ ] 搜索并浏览结果页 2-3 页
- [ ] Cookie-Editor 在 zhipin.com 页面上导出 JSON
- [ ] 导出文件包含 wt2、__zp_stoken__、wbg、boss_token
- [ ] `job-agent import-cookies data/cookies/boss_export.json boss_zhipin` 执行成功，输出 `boss_zhipin.json`
- [ ] `job-agent check-cookies` 显示 wt2 和 __zp_stoken__ 有效
- [ ] `job-agent search` 返回 code 0 且有职位结果

> 注：cookie 文件路径在 `config.yaml` 的 `platforms.boss_zhipin.cookie_path`，与导入工具输出名（`boss_zhipin.json`）一致。
