# 求职 AI Agent

自动搜职位→人工筛选→LLM精排匹配→简历定制→投递追踪的智能求职助手。

## 项目简介

求职 AI Agent（包名 `agent_core`）是一个自动化求职工具，从职位搜索到投递追踪全流程覆盖。支持多平台并发搜索、跨平台去重、人工筛选、LLM 精排匹配、简历定制和投递状态追踪。底层使用 DS 作为 LLM（通过 `DEEPSEEK_API_KEY` 环境变量配置）。

## 架构流程

```
搜索 (Search) → 人工筛选 (Review) → 精排 (Match) → 简历定制 (Tailor) → 投递追踪 (Track)
     ↓                ↓              ↓              ↓              ↓
 多平台并发      用户标记            LLM 精排       生成 .docx     7 阶段状态机
 HTTP API 直连   想投递/不合适       并发 5          + .md          + 时间线
 跨平台去重      Dashboard 展示     JSON 强制       自动打开       手动补录
                                    + 重试          岗位链接       外部投递
```

### 各阶段说明

- **Search**: 按关键词+地点在多平台并发搜索职位
- **Review**: 用户在 Dashboard 上查看搜索结果，标记 🌟想投递 / ❌不合适
- **Match**: LLM 对标记"想投递"的岗位做深度匹配，并发 5，JSON 强制 + 重试
- **Tailor**: 生成定制简历（.docx + .md），自动打开岗位链接
- **Track**: 7 阶段状态机（已投递→HR已读→约面→一面→二面→Offer→入职，任一可→已终止），支持时间线和手动补录外部投递

## 安装

```bash
cd agent-core
pip install -e .
playwright install chromium  # 智联招聘浏览器模式需要（login/搜索走持久 profile）
```

设置 DeepSeek API Key：

```bash
# Windows
setx DEEPSEEK_API_KEY "sk-your-key"

# Linux/Mac
export DEEPSEEK_API_KEY="sk-your-key"
```

## 配置

```bash
cp config.example.yaml config.yaml   # 首次使用：基于模板创建（或直接使用仓库内 config.yaml）
cp .env.example .env                 # 填写 DEEPSEEK_API_KEY 等密钥
```

### config.yaml 主要配置项

```yaml
platforms:
  boss_zhipin:
    enabled: true
    cookie_path: data/cookies/boss_zhipin.json
  liepin:
    enabled: true
    cookie_path: data/cookies/liepin.json
  job51:          # 存根（未实现）
  zhilian:        # 已实现（浏览器模式，登录一次长期可用）
  maimai:         # 存根（未实现）
  tencent/netease/byd/naura/yofc:  # 公开 API，无需 cookie

search:
  location: 全国
  min_salary: 6000
  exclude_keywords: ["外包", "派遣"]
  directions:
    default:
      resume_file: resumes/简历.txt   # 上传简历后自动写入

matching:
  match_min_score: 50

llm:
  provider: deepseek
  model: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY
  thinking:
    enabled: true
    effort: high

schedule:
  interval_hours: 6
  quiet_hours: [0, 7]  # 0-7 点安静时段

notify:
  windows_toast: true  # Windows 桌面通知

realtime:
  enabled: true        # Dashboard 实时语音面试（火山引擎 SC2.0）
  ws_port: 8766        # 浏览器 WebSocket 代理端口
  voice: saturn_zh_female_chengshujiejie_tob
```

### 环境变量

- `DEEPSEEK_API_KEY`: DeepSeek API 密钥（必需，用于 LLM 精排、简历定制等功能）
- `VOLC_APP_KEY` / `VOLC_APP_ID` / `VOLC_ACCESS_KEY`: 火山引擎实时语音密钥（可选，仅 Dashboard 实时语音面试需要）

## Cookie 获取流程

**重要**: 自动登录不可行（boss 检测 CDP，liepin 同理）。需手动导出 Cookie。

### 流程步骤

1. **Chrome 登录目标站点**
   - Boss 直聘: 登录 https://www.zhipin.com
   - 猎聘: 登录 https://www.liepin.com

2. **导出 Cookie 为 JSON**
   - 安装 Chrome 扩展 "Cookie-Editor"
   - 导出该域名**全部** cookie 为 JSON 文件
   - Boss 需包含: `wt2`, `__zp_stoken__`
   - Liepin 需包含: `lt_auth`

3. **保存到项目**
   - 存为 `data/cookies/boss_export.json` 或 `liepin_export.json`

4. **转换 Cookie 格式**
   ```bash
   # Boss 直聘
   python scripts/import_cookies.py data/cookies/boss_export.json boss --domain zhipin.com

   # 或使用 CLI
   job-agent import-cookies data/cookies/boss_export.json boss --domain zhipin.com

   # 猎聘
   python scripts/import_cookies.py data/cookies/liepin_export.json liepin --domain liepin.com
   ```

5. **验证 Session Cookie**
   转换器会检查 session cookie 是否存在：
   - `[OK] session cookies: wt2, __zp_stoken__` → 成功
   - `[WARN] 未发现已知 session cookie，请确认导出前已登录。` → 需重新导出

## 命令速查表

### 登录与状态

```bash
job-agent login --platform boss      # 引导手动导出 cookie（Boss 检测 CDP，无法自动登录）
job-agent login --platform liepin    # 引导手动导出 cookie
job-agent login --platform zhilian   # 打开浏览器手动登录（profile 持久化）
job-agent check-cookies              # 体检各平台 cookie 健康状态
job-agent check-cookies --probe      # 带探活（实际发请求验证）
```

### 搜索与匹配

```bash
job-agent search --keyword Python --platforms boss_zhipin,liepin  # 按关键词搜（--keyword 必填）
job-agent search --keyword AMR --platforms boss,zl                # 平台别名（boss→BOSS）
job-agent search --keyword AMR --company 大疆                     # 按公司名过滤
job-agent search --keyword AMR --max-pages 2                      # 每平台抓取页数
job-agent pipeline --stages search,filter,match --keyword Python  # 搜索->筛选->精排
job-agent pipeline --stages search,filter --keyword Python        # 仅搜索和筛选
job-agent rematch <job-id>            # 简历更新后重新匹配单个岗位
job-agent rematch --all-since 2026-06-01  # 批量重新匹配（简历更新后）
```


### 简历与HR打招呼消息

```bash
job-agent tailor <job-id>            # 定制简历(.docx+.md)，自动打开岗位链接
job-agent cover-letter <job-id>      # 生成HR打招呼消息（150-200字）
```

### 投递追踪

```bash
job-agent track add <job-id>         # 记录投递
job-agent track add https://www.zhipin.com/job_detail/xxx.html  # 手动补录外部投递
job-agent track list                 # 查看全部投递
job-agent track list --status 约面   # 按状态过滤
job-agent track show <app-id>        # 查看详情+时间线
job-agent track update <app-id> --status 二面  # 推进状态
```

### 面试准备

```bash
job-agent interview-prep <job-id>    # 预测面试题(技术/行为/项目深挖)
job-agent mock-interview <job-id>    # 终端交互式模拟面试（自由问答）
job-agent mock-interview <job-id> --from-prep --focus 项目深挖 --difficulty easy
```
### Offer 评估

```bash
job-agent offer-eval --company 宁德时代 --title 高级工程师 \
  --location 宁德 --salary 20K-28K --bonus 年终2-4月

job-agent salary-advice --company 宁德时代 --title 高级工程师 \
  --salary 24K --target 30K --strengths "Agent架构0→1落地"
```

### 调度与看板

```bash
job-agent schedule on                # 开启定时搜岗
job-agent schedule run               # 启动 daemon 循环（Ctrl+C 停止）
job-agent schedule status            # 查看调度状态
job-agent schedule off               # 关闭定时搜岗
job-agent serve                      # 启动本地 dashboard → http://localhost:8765
job-agent serve --daemon             # 后台启动
job-agent serve --stop               # 停止后台 dashboard
```

### Cookie 导入

```bash
job-agent import-cookies data/cookies/boss_export.json boss --domain zhipin.com
job-agent import-cookies data/cookies/liepin_export.json liepin --domain liepin.com
```

## 完整工作流示例

```bash
# 1. 导入 Cookie（首次使用）
job-agent import-cookies data/cookies/boss_export.json boss --domain zhipin.com
job-agent import-cookies data/cookies/liepin_export.json liepin --domain liepin.com

# 2. 检查登录状态
job-agent check-cookies

# 3. 运行完整流程（搜索→人工筛选→精排）
job-agent pipeline --stages search,filter,match --keyword Python

# 4. 查看匹配结果，选择高匹配度岗位定制简历
job-agent tailor <job-id>

# 5. 投递后记录追踪
job-agent track add <job-id>
job-agent track update <app-id> --status HR已读

# 6. 面试准备
job-agent interview-prep <job-id>
job-agent mock-interview <job-id> --from-prep --focus 项目深挖

# 7. Offer 评估
job-agent offer-eval --company 宁德时代 --title 高级工程师 --salary 20K-28K

# 8. 开启定时自动搜岗
job-agent schedule on
job-agent schedule run  # 启动 daemon（每 interval_hours 小时一次）
```

## 职位源接入方式

### 招聘平台（需登录态）

**Boss 直聘**
- **API**: `https://www.zhipin.com/wapi/zpgeek/search/joblist.json` (GET + cookie)
- **职位数据**: `zpData.jobList`
- **反爬**: 存在 code-37 反爬挑战（Cookie 短效或频繁调用触发，触发后 120s 退避）
- **JD 抓取**: 按需 4 级回退（HTML 抓取 → playwright_jd → 持久浏览器 profile → wapi/card.json）

**猎聘**
- **API**: `https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job` (POST + JSON body + cookie)
- **职位数据**: `data.data.jobCardList`
- **反爬**: 较干净；`lt_auth` 有效期较长
- **JD 抓取**: 按需（Playwright 渲染优先，urllib+正则回退）

**智联招聘**
- **方式**: Playwright headed 浏览器（持久 profile，登录一次长期可用），XHR 拦截 `fe-api.zhaopin.com` 响应
- **反爬**: Akamai Bot Manager 保护，必须活体浏览器；HTTP 回退已禁用
- **登录态**: at/rt cookie，浏览器 profile 持久化（`data/zhilian_browser_profile/`）

### 公司官网（公开 API，无需登录）

- **腾讯**: `careers.tencent.com` (GET)
- **网易**: `hr.163.com` (POST)
- **比亚迪**: `job.byd.com` (POST，分页重叠用 positionType 绕过)
- **北方华创**: `career.naura.com`（北森 API，需先取 session cookie）
- **长飞光纤**: `yofccampus.zhiye.com`（北森/zhiye.com API，关键词过滤失效→客户端过滤）

### 优势

- 招聘平台走 HTTP/浏览器直连，公司官网走公开 API，全并发搜索
- 跨平台去重（公司别名表 + 标准化标题 exact-match），避免重复职位
- 反爬平台自动 Toast 通知 + 退避

## 已知限制

### Cookie 有效期

- Boss 直聘的 `__zp_stoken__` 为短效 Cookie（几小时~一天）
- 过期后搜索返回 code-37 反爬挑战，会弹出 Windows Toast 提示
- 需重新导出 Cookie 并转换
- 频繁调用也易触发 code-37，建议降低搜索频率

### JD 详情抓取

- 搜索阶段**不抓全量 JD**（避免触发反爬），改为按需抓取：
  - Dashboard「人工初筛」tab 勾选后点「📄 抓取JD」→ `/api/jd/fetch`（最多 20 条）
  - 精排/定制/面试准备前自动按需 enrich（`enrich_job_jd`，description 已有 JD 关键词则跳过）
  - CLI `rematch <job-id>` 单条模式也会先抓 JD
- Boss 触发 code-37 时 120s 退避 + Toast 通知

### 平台支持

- **已实现（8 源，全部 enabled）**: `boss_zhipin`, `liepin`, `zhilian`（Playwright headed 浏览器，登录一次长期可用）、`tencent`, `netease`（公开 API）、`byd`（比亚迪，公开 API）、`naura`（北方华创，Beisen API）、`yofc`（长飞光纤，Beisen/zhiye.com API）
- **存根（未实现）**: `job51`, `maimai`（`NotImplementedError`，用户暂不接入）
- **行业调研 backlog**（verify-before-building，未盲写；详见 `docs/research/`）：
  - **半导体**：中芯/长存（Beisen SSR，需 HTML 爬取）、华虹/兆易/中微（MokaHR 加密 API，需 JS 逆向）、长鑫（站点不可达）
  - **新能源**：宁德时代/晶科/天合（MokaHR 加密）、隆基（WinTalent 需 SPA 上下文）、远景（Avature 无 API）、亿纬（静态 HTML）
  - **制药**：恒瑞/百济/药明/齐鲁/复星——头部药企全部挂第三方闭源平台（智联/前程无忧/脉脉），无公开 API

## 对话模式（Chat）

```bash
job-agent chat  # 启动自然语言对话 REPL
```

用自然语言操作求职 Agent，DeepSeek function-calling 自动调用搜索/筛选/投递追踪/简历定制等 11 个工具：

```
你: 搜深圳的AMR岗位
Agent: [调用 search_jobs tool] 找到 48 个岗位...

你: 帮我看看投了哪些
Agent: [调用 list_tracked_applications tool] 共 3 条投递记录...

你: 把刚才那个宁德时代的岗位定制简历
Agent: [调用 tailor_resume tool] 简历已生成...
```

支持：搜索岗位、查看详情、投递追踪、简历定制、HR打招呼消息、面试准备、Offer 评估、薪资建议、Cookie 检查。

### 其他限制

- 配置文件中平台、方向、匹配参数需手动配置
- 简历文件需提前准备好（`resumes/` 目录）
- LLM 调用依赖 `DEEPSEEK_API_KEY`，未设置则无法使用 LLM 相关功能

## 测试

```bash
# 运行所有测试
python -m pytest tests/ -q

# 基础验证
python tests/phase1_verify.py
```

- **测试数量**: 普通全量 1306 passed / 6 skipped / 0 failed；含 Windows Toast 集成 1311 passed / 1 skipped / 0 failed（2026-08-18，含 Phase0-3 重构回归 + `*_more.py` 大批补测 + 10 Tab UI 优化）
- **覆盖率**: 2026-08-18 最近实测 84.4%（门槛 70；serve.py 80.3%、realtime_proxy.py 93.3%、boss_browser.py 85.5%、playwright_jd.py 89.7%、zhilian.py 92.9%）
- **测试目录**: `tests/test_core`, `tests/test_advanced`, `tests/test_misc`, `tests/test_cli`, `tests/test_boss`, `tests/test_liepin`, `tests/test_zhilian`, `tests/test_tencent`, `tests/test_netease`, `tests/test_byd`, `tests/test_naura`, `tests/test_yofc`, `tests/test_chat`, `tests/test_serve`, `tests/test_registry`, `tests/test_browser_utils`, `tests/test_http_utils`, `tests/test_serve_auth`, `tests/test_scripts`, 以及 `tests/test_*_more.py` 覆盖补充

## 数据文件

| 内容 | 路径 |
|------|------|
| 数据库 | `data/agent.db` |
| 日志 | `data/agent.log` |
| Cookie | `data/cookies/boss_zhipin.json`, `liepin.json` |
| 简历模板 | `resumes/my_resume.txt` |
| 定制简历 | `output/<公司>_<岗位>.docx` |
| 简历预览 | `output/<公司>_<岗位>.md` |
| HR打招呼消息 | `output/<公司>_<岗位>_hrmsg.md` |
| 面试准备 | `output/<公司>_<岗位>_interview.md` |
| 模拟面试记录 | `output/<公司>_<岗位>_mock_interview.md` + `_assessment.txt/json` |
| 实时语音面试记录 | `output/<公司>_<岗位>_realtime_mock.md` + `_realtime_mock_assessment.txt` |
| Dashboard 日志/PID | `data/dashboard.log` / `data/dashboard.pid` |
| 测试证据 | `data/log_archive/` |

## Dashboard

```bash
job-agent serve  # 启动本地 HTTP dashboard
```

访问 http://localhost:8765，10 个 Tab：
- 📄 文件上传：上传/管理原始简历
- 📋 人工初筛：岗位列表 + 🌟/❌ 标记
- 🎯 Agent智能匹配结果：精排结果 + 多选生成简历与求职信
- 📝 材料审核台：审核简历+HR消息草稿，可填改进意见再生成，确认后保存归档
- 📅 投递追踪：投递状态区（下拉改状态 + 设提醒周期）
- 🎤 模拟面试：文字/实时语音（SC2.0）交互式模拟面试，5 维评估
  - 勾选「用 prep 题库」时题量由题库决定；`focus` 用于过滤题库，未命中会拒绝开始。难度（简单/中等/困难）只是面试官的软提示，不改变题量。
  - 未选职位时「开始面试」禁用；「朗读面试官」默认关闭；全默认且无记录时「清空」禁用。
- 💼 Offer评估：8 维综合评估（竞争力/成长性/风险等）
- 💰 薪资谈判：薪资谈判策略与话术
- 📁 已生成文件：简历(.md/.docx) + HR消息(.md) + 面试准备
- ⚙️ Pipeline：6 阶段状态总览（search/filter/match/tailor/materials/track + 后置 3 卡）

**模拟面试专项复盘**：`docs/retrospective-2026-08-16-mock-interview.md`（文字/实时语音全链路、focus/清空/评估/前端竞态修复记录与经验教训）。
**职位搜索专项复盘**：`docs/retrospective-2026-08-16-search-audit.md`（搜索链路 11 缺陷 + 7 策略、UPSERT 保标记、分页/相关性过滤、Dashboard 空状态与 DOM 回归教训）。
**AI 助手长期记忆**：`AGENTS.md`（进入本仓库先读：铁律、Dashboard HTML/JS 防错清单、搜索/模拟面试权威实现、测试与浏览器工具箱）。

**材料审核台流程**：match tab 勾选职位 -> 生成简历+HR消息草稿 -> 材料审核台审核（再生成带 feedback / 确认保存）-> 确认后自动入投递追踪（待投递）+ 文件归档至已生成文件。

**投递追踪改造**：确认即入追踪；投递追踪 tab 可设提醒周期（天），Dashboard 后台每小时自动检查，对未终止且超周期的投递发 Windows toast 提醒（同一提醒 24h 内去重）；status=已终止 自动停通知。

## FAQ

**搜不到岗？**
→ 运行 `job-agent check-cookies` 检查 Cookie 是否过期

**遇 code-37 反爬？**
→ Windows Toast 会弹出通知 → 重新导出 Boss Cookie 并转换

**简历更新了？**
→ 运行 `job-agent rematch --all-since 2026-06-01` 重新匹配

**外部投递？**
→ 运行 `job-agent track add https://www.zhipin.com/job_detail/xxx.html` 手动补录

**LLM 命令不可用？**
→ 检查 `DEEPSEEK_API_KEY` 环境变量是否设置

**定时搜岗不工作？**
→ 检查 `job-agent schedule status` 确认调度状态和上次运行时间