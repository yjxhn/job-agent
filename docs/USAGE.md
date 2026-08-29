# 求职 AI Agent 使用手册

自动搜职位 -> 人工筛选 -> LLM 精排匹配 -> 简历定制 -> 投递追踪的智能求职助手。

> 手册版本：2026-08-16（覆盖 17 个 CLI 命令、Dashboard 10 个 Tab、文字/实时语音模拟面试、12 张业务表）

---

## 环境要求

- **Python**: >= 3.12
- **操作系统**: Windows / Linux / macOS（部分功能仅 Windows，如 Toast 桌面通知）
- **浏览器**:
  - Chromium：智联招聘浏览器模式需要（`playwright install chromium`）
  - Chrome / Edge：Dashboard 实时语音面试需要浏览器麦克风 + WebSocket 支持


### 安装

```bash
cd agent-core
pip install -e .
```

要使用智联招聘的 Playwright 浏览器模式或旧版 `login` 命令：

```bash
playwright install chromium
```

### 设置 API Key

项目使用 DeepSeek 作为 LLM（通过 OpenAI 兼容端点），API key 通过环境变量设置：

```bash
# Windows
setx DEEPSEEK_API_KEY "sk-your-key"

# Linux / Mac
export DEEPSEEK_API_KEY="sk-your-key"
```

也可创建 `.env` 文件放在项目根目录（与 `config.yaml` 同级）：

```
DEEPSEEK_API_KEY=sk-your-key
```

> 不设置 API key 时，非 LLM 命令（`login`、`search`、`track`、`schedule`）仍可正常使用；LLM 相关命令会提示环境变量未设置。

### 设置实时语音面试密钥（可选）

Dashboard 的「实时语音」面试模式通过本地 WebSocket 代理（默认 `ws://127.0.0.1:8766`）对接火山引擎豆包实时语音 SC2.0。需要设置三个环境变量：

```bash
# Windows
setx VOLC_APP_KEY "你的AppKey"
setx VOLC_APP_ID "你的AppID"
setx VOLC_ACCESS_KEY "你的AccessKey"

# Linux / Mac
export VOLC_APP_KEY="你的AppKey"
export VOLC_APP_ID="你的AppID"
export VOLC_ACCESS_KEY="你的AccessKey"
```

三者也可以配置在 `config.yaml` 的 `realtime` 段（见下）；缺任一密钥时实时语音模式会自动禁用，文字面试不受影响。

---

## 首次配置

### 1. 理解 config.yaml

配置文件位于 `agent-core/config.yaml`，由 Pydantic v2 校验。关键配置区域：

**平台开关** (`platforms`)：控制哪些职位源参与搜索。`enabled: true` 的平台才会被搜到。`job51` 和 `maimai` 默认为 `enabled: false`（未实现）。

每个平台的 `rate_limit_seconds`（请求间隔）和 `search_max_pages`（每关键词抓取页数，默认 1；Boss/猎聘/智联等反爬平台建议保持 1，官网公开 API 可用 2）都按平台独立配置。智联的 `browser_profile_dir` 指定持久化浏览器 profile。

**搜索方向** (`search.directions`)：定义你要找的职位方向，每个方向有：
- `keywords`：搜索关键词列表
- `resume_file`：该方向对应的简历文件路径（相对于项目根目录）

**匹配参数** (`matching`)：
- `match_min_score`：LLM 精排最低分数线（0-100，低于此分的岗位不展示）
- `enrich_in_pipeline`：是否在 Pipeline 中抓取完整 JD（默认 false，避免反爬）
- `enrich_top_n`：enrich 时取前 N 个岗位抓 JD

**LLM 配置** (`llm`)：
- `provider`：固定 `deepseek`
- `model`：默认为 `deepseek-v4-flash`
- `api_key_env`：环境变量名（默认 `DEEPSEEK_API_KEY`）
- `base_url`：API 端点（默认 `https://api.deepseek.com`）
- `temperature`、`max_tokens`：生成参数

### 思考模式（thinking）

deepseek-v4-flash 原生支持思考模式（thinking mode），开启后模型先输出内部思维链再给最终答案，可提升复杂推理的准确性。

```yaml
llm:
  thinking:
    enabled: false      # 默认关闭；设为 true 开启思考模式
    effort: "high"      # high | max
```

**effort 档位说明**：

| effort | 含义 | 适用场景 |
|--------|------|---------|
| `high` | 标准深度推理 | 大多数 LLM 精排场景，性价比最高 |
| `max` | 最大深度推理 | 特别难判断的岗位匹配，响应更慢但更精细 |

`low`/`medium` 会被映射为 `high`，`xhigh` 会被映射为 `max`，不会报错但也不会产生独立档位。

**注意事项**：
- 思考模式下 `temperature`、`top_p` 等参数设置后不生效（不报错但被忽略）
- 思考模式显著增加延迟和 token 消耗，默认关闭
- 思维链通过 API 响应的 `reasoning_content` 字段返回
- 工具调用（chat 模式）与思考模式兼容，`reasoning_content` 已正确回传到后续请求

**使用建议**：
- `match` 精排阶段建议开 `high`，能显著提升岗位-简历匹配质量
- `interview-prep`、`cover-letter` 等深度推理任务也值得开启
- `max` 按需使用，仅在极难判断的岗位匹配时开启

**实时语音面试** (`realtime`)：
- `enabled`：是否启用实时语音面试（默认 `false`；当前 `config.yaml` 已开启）
- `ws_port`：浏览器 WebSocket 代理端口（默认 8766）
- `volc_endpoint`：火山引擎实时语音端点（默认 `wss://openspeech.bytedance.com/api/v3/realtime/dialogue`）
- `model`：SC2.0 模型版本（默认 `2.2.0.0`）
- `voice`：面试官音色（当前 `saturn_zh_female_chengshujiejie_tob`，可按火山文档换）
- `resource_id`：默认 `volc.speech.dialog`
- `app_key_env` / `app_id_env` / `access_key_env`：密钥环境变量名（默认 `VOLC_APP_KEY` / `VOLC_APP_ID` / `VOLC_ACCESS_KEY`）

**定时调度** (`schedule`)：
- `interval_hours`：搜索间隔（默认 6 小时）
- `directions`：定时搜的方向列表
- `quiet_hours`：安静时段（`[0, 7]` 表示 0-7 点不搜）

**通知** (`notify`)：
- `windows_toast`：是否启用 Windows 桌面通知
- `notify_on_zero_results`：零结果时是否通知

### 2. 准备简历文件

在 `resumes/` 目录下放置纯文本简历（通过 Dashboard「文件上传」tab 上传，或手动放入）。文件名对应 `config.yaml` 中 `search.directions.default.resume_file`。例如：

```
resumes/
  简历.txt
```

### 3. 获取 Cookie（BOSS 直聘 / 猎聘 / 智联）

这三个平台需要登录态。流程：

1. 在 Chrome 中登录目标网站
2. 使用 "Cookie-Editor" 浏览器扩展导出全部 Cookie 为 JSON 文件
3. 用 `import-cookies` 命令转换并保存：

```bash
job-agent import-cookies data/cookies/boss_export.json boss_zhipin --domain zhipin.com
job-agent import-cookies data/cookies/liepin_export.json liepin --domain liepin.com
job-agent import-cookies data/cookies/zhilian_export.json zhilian --domain zhaopin.com
```

4. 检查状态：

```bash
job-agent check-cookies
job-agent check-cookies --probe  # 带探活（实际发请求验证）
```

> BOSS 直聘的 `__zp_stoken__` 是短效 Cookie（几小时到一天），过期后搜索会返回 code-37 反爬，需要重新导出。

---

## 快速开始

最小流程跑通一次完整的搜岗-匹配-定制：

```bash
# 1. 导入 Cookie（首次使用）
job-agent import-cookies data/cookies/boss_export.json boss_zhipin --domain zhipin.com

# 2. 检查登录状态
job-agent check-cookies

# 3. 运行完整 Pipeline（搜索 -> 筛选 -> 精排）
job-agent pipeline

# 4. 查看 Top 匹配结果，记录 job-id（如 abc123def456）
# 5. 为高匹配度岗位定制简历
job-agent tailor abc123def456

# 6. 记录投递
job-agent track add abc123def456
```

---

## CLI 命令参考

所有命令通过 `job-agent` 入口调用。以下列出全部 17 个命令。

### login -- 登录管理

管理平台 Cookie 登录态。

```bash
# 检查所有已启用平台的 Cookie 状态
job-agent check-cookies

# 为某个平台打开浏览器手动登录（旧 Playwright 路径）
job-agent login --platform boss
job-agent login --platform liepin
job-agent login --platform zhilian
```

支持的 `--platform` 别名：`boss` (=boss_zhipin)、`zhipin` (=boss_zhipin)、`liepin`、`zl` (=zhilian)、`51` (=job51)。

输出示例：

```
  boss_zhipin: 12 cookies, 10 valid, 2 expired
  liepin: NOT LOGGED IN (no cookie file)
```

---

### import-cookies -- 导入 Cookie

将浏览器导出的 Cookie JSON 转换为项目可用格式。

```bash
job-agent import-cookies <导出文件路径> <平台键> [--domain 域名过滤]
```

示例：

```bash
job-agent import-cookies data/cookies/boss_export.json boss_zhipin --domain zhipin.com
job-agent import-cookies data/cookies/liepin_export.json liepin --domain liepin.com
```

转换器会自动检测已知 session cookie（Boss 的 `wt2`/`__zp_stoken__`，猎聘的 `lt_auth` 等），并在输出中告知是否存在。

---

### check-cookies -- Cookie 体检

检查各平台 Cookie 的健康状态，包括过期时间分析和重抓指引。

```bash
# 仅检查文件 + 过期时间（不发请求）
job-agent check-cookies

# 带探活（实际发搜索请求验证 Cookie 是否有效）
job-agent check-cookies --probe
```

输出包含每个平台的状态图标、状态标签、关键 Cookie 过期时间，以及需要重抓的平台的重抓指南。

- 智联招聘使用浏览器持久化登录（`data/zhilian_browser_profile/`），**不依赖** `data/cookies/zhilian.json`；无 `--probe` 时显示“需探活确认”，不会误报缺失。
- `--probe` 对智联会打开持久化浏览器实测一次搜索。

> 注意：`--probe` 会消耗 BOSS 直聘的请求额度，可能触发反爬。

---

### search -- 搜索职位

多平台并发搜索职位，支持跨平台去重、关键词相关性过滤和平台别名。

```bash
# 按关键词搜索所有启用平台（--keyword 必填）
job-agent search --keyword "AI Agent,Python"

# 限定平台（逗号分隔；支持 boss/zhipin/zl/51 别名）
job-agent search --keyword AMR --platforms boss_zhipin,liepin
job-agent search --keyword AMR --platforms boss,zl

# 每平台每关键词抓取页数（覆盖 config 的 search_max_pages）
job-agent search --keyword AMR --max-pages 2

# 按公司名过滤（大小写不敏感，子串匹配）
job-agent search --keyword AMR --company 大疆

# --direction 在显式关键词模式下作为入库方向标签
job-agent search --keyword AMR --direction equipment_amr
```

- 搜索结果会先经过共享关键词相关性过滤（完整关键词命中，或中文关键词字面重合率 ≥ 2/3），过滤掉官网/智联的无关推广岗位。
- `job-agent search` 会应用 `config.yaml` 的排除关键词、最低薪资和地点过滤（与 pipeline 一致）。
- 搜索结果为 0 时会自动诊断 Cookie 健康状态；智联按浏览器持久化登录判断，不再误报“cookie 文件缺失”。

---

### pipeline -- 运行 Pipeline

运行搜索、筛选、精排的完整或部分流程。

```bash
# 运行全流程（默认 stages: search,filter,match）
job-agent pipeline --keyword AMR

# 仅运行搜索和筛选
job-agent pipeline --keyword AMR --stages search,filter

# 每平台每关键词抓取页数
job-agent pipeline --keyword AMR --max-pages 2

# 仅精排（使用已有搜索结果）
job-agent pipeline --stages match
```

可用的 stage 值：`search`、`filter`、`enrich`、`match`。

> `enrich` 阶段需要 `config.yaml` 中 `matching.enrich_in_pipeline: true` 才会生效（默认关闭，因为批量抓 JD 容易触发反爬）。

---

### tailor -- 定制简历

根据岗位 JD 生成定制简历，输出 .docx 和 .md 两种格式，并自动在浏览器中打开岗位链接。

```bash
job-agent tailor <job-id>
```

输出文件保存在 `output/` 目录下：
- `output/<公司>_<岗位>.docx`
- `output/<公司>_<岗位>.md`

定制规则：保持所有原始经历不变（日期、公司、职位、技能），仅重新排序和措辞以突出与该岗位相关的经验。不会凭空发明任何经验或技能。

---

### cover-letter -- 生成HR打招呼消息

```bash
job-agent cover-letter <job-id>
```

生成 150-300 字的中文HR打招呼消息，保存到 `output/<公司>_<岗位>_hrmsg.md`。

---

### interview-prep -- 面试准备

根据岗位 JD 预测面试题目。

```bash
job-agent interview-prep <job-id>
```

生成三个类别的预测题目：
- **technical**：技术问题（3-5 题）
- **behavioral**：行为问题（2-3 题）
- **project**：项目深挖（2-3 题）

每题包含问题 + 答题要点（中文 bullet points）。保存到 `output/<公司>_<岗位>_interview.md`。

---

### mock-interview -- 模拟面试

在终端中启动交互式模拟面试。

```bash
job-agent mock-interview <job-id>                                 # 自由问答模式
job-agent mock-interview <job-id> --from-prep                     # 严格使用面试准备题库
job-agent mock-interview <job-id> --from-prep --focus 项目深挖     # 只考题库中命中关键词的题
job-agent mock-interview <job-id> --from-prep --difficulty hard    # 难度软提示
```

- **默认自由模式**：面试官根据 JD + 简历出题，交互后给出评估。
- **`--from-prep` 题库模式**：必须先有 `interview-prep` 生成的 `output/<公司>_<岗位>_interview.json`。此模式只从题库出题、禁止额外追问；候选人答案必须由你输入，系统不会编造答案。
- **`--focus`**：按关键词过滤题库题目（如「技术」「项目深挖」「光伏」）；命中 0 题时直接取消并提示，不会悄悄退回全题库。
- **`--difficulty`**：`easy` / `normal` / `hard`，仅作为软提示写入系统提示词；题库模式题量不变。
- 输入 `quit` 可提前退出。正常结束时保存 `output/<公司>_<岗位>_mock_interview.md`（生成评估时加 `_assessment.json`）。

Dashboard 的「🎤 模拟面试」Tab 提供同样的文字面试，并支持实时语音模式（见 `serve` 一节）。

---

### rematch -- 重新匹配

简历更新后重新运行匹配。

```bash
# 重新匹配单个岗位
job-agent rematch <job-id>

# 批量重新匹配（自某日期以来的所有岗位）
job-agent rematch --all-since 2026-06-01
```

单岗位模式会自动抓取完整 JD 后再匹配；批量模式不抓 JD（避免反爬），使用已存储的描述。

---

### track -- 投递追踪

管理职位投递状态，支持 7 阶段状态机和完整时间线。

```bash
# 记录投递
job-agent track add <job-id>
job-agent track add https://www.zhipin.com/job_detail/xxx.html  # 外部投递（URL）

# 查看全部投递
job-agent track list

# 按状态过滤
job-agent track list --status 约面
job-agent track list --status Offer

# 查看详情 + 时间线
job-agent track show <app-id>

# 推进状态
job-agent track update <app-id> --status HR已读
job-agent track update <app-id> --status 二面
```

**状态流转规则**：

```
待投递 -> 已投递 / 已终止
已投递 -> HR已读 / 约面 / 已终止
HR已读 -> 约面 / 已终止
约面   -> 一面 / 已终止
一面   -> 二面 / 已终止
二面   -> Offer / 已终止
Offer  -> 入职 / 已终止
入职   -> (终态)
已终止 -> (终态)
```

`待投递` 是材料审核台确认后自动建的初始态（dashboard-only）。不合法的状态跳转会报错并提示允许的目标状态。

**2026-07-17 投递追踪改造**：
- **确认即入追踪**：在材料审核台确认简历+HR消息后，自动在投递追踪建记录（status=待投递），无需手动 `track add`
- **周期提醒**：Dashboard 投递追踪 tab 顶部「投递状态」区可设提醒周期（天）；Dashboard 后台每小时检查一次，对未终止且超周期的投递发 Windows toast 提醒（同一提醒 24h 内去重），不再依赖定时搜索进程
- **终止停通知**：status=已终止 的投递不再触发提醒
- **Dashboard 操作**：投递追踪 tab -> 「📍投递状态」区，每职位可下拉改状态（待投递/已投递/HR已读/约面/一面/二面/Offer/入职/已终止），右侧设提醒周期

**2026-08-18 投递追踪增强**：
- 状态列改为彩色 Tag 下拉，进度一眼可辨
- 顶部新增「全部状态」筛选、岗位/公司搜索、更新时间排序
- 表格上方新增按状态分组统计标签（待投递/已投递/HR已读/面试中/Offer/入职/已终止）
- 数据多时显示「共 N 条」+「加载更多」
- 新增「➕ 手动新增」：弹窗填岗位 ID + 初始状态，可直接补录线下投递

---

### offer-eval -- Offer 评估

综合评估一份 Offer 的竞争力、成长性和风险。

```bash
job-agent offer-eval \
  --company 宁德时代 \
  --title 高级AI工程师 \
  --location 宁德 \
  --salary 25K-35K \
  --bonus 年终2-4月 \
  --benefits 五险一金+补充医疗+免费宿舍 \
  --level P7 \
  --notes "团队做工业大模型落地"
```

输出包含：
- 综合评价（满分 10）
- 竞争力 / 成长性 / 风险 分项评分
- 优势列表
- 劣势列表
- 谈判杠杆（如适用）

---

### salary-advice -- 薪资谈判建议

获取薪资谈判策略和话术。

```bash
job-agent salary-advice \
  --company 宁德时代 \
  --title 高级AI工程师 \
  --salary 24K \
  --target 30K \
  --strengths "Agent架构0到1落地经验,主导过3个工业AI项目"
```

输出包含：
- 锚点薪资
- 自信度评估
- 谈判筹码列表
- 让步方案
- 可直接使用的话术

---

### schedule -- 定时搜岗

管理定时自动搜索。

```bash
# 查看状态
job-agent schedule status

# 开启定时搜岗
job-agent schedule on

# 启动 daemon 循环（按 interval_hours 间隔自动搜）
job-agent schedule run

# 关闭
job-agent schedule off
```

`schedule run` 会启动一个前台 daemon，按 `config.yaml` 中 `schedule.interval_hours` 间隔（默认 6 小时）自动运行 pipeline。在 `quiet_hours`（默认 0-7 点）期间跳过。按 Ctrl+C 停止。

daemon 使用 PID 锁文件（`data/scheduler.lock`）防止重复启动。

---

### cleanup -- 清理缓存 / 日志

```bash
job-agent cleanup --dry-run   # 只列出将清理的内容
job-agent cleanup --cache     # 清理浏览器缓存（保留登录态）
job-agent cleanup --logs      # 清理日志文件
job-agent cleanup --all       # 清理浏览器 profile + 日志 + 数据库（需重新登录）
```

默认不会动 `output/`、`resumes/`、`offers/`、`data/cookies/` 和 `data/log_archive/`。

---

### serve -- 启动 Dashboard

启动本地 HTTP 看板。

```bash
job-agent serve                 # 前台运行（Ctrl+C 停止）
job-agent serve --port 9000     # 自定义端口
job-agent serve --daemon        # 后台进程（退出终端后继续运行）
job-agent serve --stop          # 停止后台进程
```

访问 `http://localhost:8765`（`/docs` 为 OpenAPI/Swagger 页面），包含 10 个 Tab：

- 📄 文件上传：上传/管理原始简历
- 📋 人工初筛：岗位列表 + 🌟/❌ 标记
- 🎯 Agent智能匹配结果：精排结果 + 多选生成简历与求职信
- 📝 材料审核台：审核简历+HR消息草稿，可填改进意见再生成，确认后保存归档
- 📅 投递追踪：状态彩色 Tag + 筛选/搜索/排序/统计/加载更多 + 手动新增 + 设提醒周期
- 🎤 模拟面试：文字面试 + 实时语音面试（火山引擎 SC2.0，浏览器麦克风 ↔ ws://127.0.0.1:8766）
- 💼 Offer评估：8 维综合评估（竞争力/成长性/风险等）
- 💰 薪资谈判：薪资谈判策略与话术
- 📁 已生成文件：搜索/类型筛选/排序/加载更多 + 预览/下载/删除
- ⚙️ Pipeline：9 阶段状态总览（搜索/筛选/匹配/生成材料/审核/投递/面试/Offer/薪资）

#### API 端点一览

> 完整路由见 `serve.py` 的 `do_GET`/`do_POST`/`do_DELETE` 分发器（50+ 端点）。下表为全部端点：

| 端点 | 方法 | 说明 | 关键参数 |
|------|------|------|----------|
| `/api/results` | GET | 岗位列表（分页+筛选） | `page`, `page_size`, `platform`, `company`, `title`, `location`, `user_flag` |
| `/api/results` | DELETE | 清空岗位+搜索状态 | 无 |
| `/api/pipeline` | GET | Pipeline 阶段状态 | 无 |
| `/api/match` | GET | 匹配结果（分页，支持最低分过滤） | `page`, `page_size`, `min_score` |
| `/api/match` | DELETE | 清空匹配结果 | 无 |
| `/api/match/run` | POST | 对 🌟 标记岗位跑 LLM 精排 | 无 |
| `/api/match/progress` | GET | 精排进度轮询 | 无 |
| `/api/match/feedback` | POST | 记录评分校准反馈 | `{job_id, feedback_type, note}` |
| `/api/match/feedback` | DELETE | 清除全部历史校准反馈 | 无 |
| `/api/jd/fetch` | POST | 对 🌟 标记岗位抓取完整 JD | 无 |
| `/api/jd/manual` | POST | 手动导入 JD 文本 | `{job_id, jd}` |
| `/api/jd/view` | GET | 想投递岗位 JD + 反爬标识 | `job_id` |
| `/api/jd/progress` | GET | JD 抓取进度轮询 | 无 |
| `/api/flag/{id}` | POST/DELETE | 标记岗位 🌟/❌/清除 | `flag`=interested/rejected/clear |
| `/api/flag/batch` | POST | 批量标记 | `{ids, flag}` |
| `/api/materials/{generate,regenerate,confirm}` | POST | 求职材料草稿生成/再生成/确认 | `{job_id(s), feedback?}` |
| `/api/materials/drafts` | GET | 草稿列表（draft/confirmed/all） | `status` |
| `/api/materials/jobs` | GET | 有草稿的职位（模拟面试下拉） | 无 |
| `/api/materials` | DELETE | 删除草稿+面试文件 | `{job_ids}` |
| `/api/applications` | GET | 投递记录列表 | 无 |
| `/api/application` | POST | 手动新增投递记录 | `{job_id, status?}` |
| `/api/application/{update,reminder}` | POST | 更新投递状态 / 设提醒周期 | `{id, status}` / `{days}` |
| `/api/application` | DELETE | 删除投递（级联 timelines） | `id` |
| `/api/resume/{upload,default,preview}` | GET/POST | 简历上传/设默认/预览 | `{name, content}` |
| `/api/resume` | DELETE | 删除简历 | `name` |
| `/api/offer/{template,list,upload,evaluate,preview,compare,compare/save,save,delete}` | * | Offer 全流程（17 字段解析+8 维评估+对比+缓存） | `{file_name}` |
| `/api/salary-advice{,/save}` | POST | 薪资谈判建议生成/保存 | `{company, ...}` |
| `/api/mock-interview/start` | POST | 开始面试会话 | `{job_id, from_prep?, focus?, difficulty?}` |
| `/api/mock-interview/reply` | POST | 流式对话回合（SSE：delta/turn_end/end/error） | `{session_id, text?}` |
| `/api/mock-interview/end` | POST | 手动结束：保存记录 + 生成评估（中途结束会标注） | `{session_id}` |
| `/api/mock-interview/abandon` | POST | 放弃会话，不保存任何文件 | `{session_id}` |
| `/api/mock-interview/latest-transcript` | GET | 最近一次记录下载(.txt) | `job_id`, `mode`=text/realtime |
| `/api/mock-assessment/preview` | GET | 评估文本→结构化解析 | `name`（output/ 下的文件名） |
| `/api/files` | GET | 已生成文件列表（catalog 驱动） | 无 |
| `/api/files/zip` | POST | 批量下载文件为 zip | `{names}` |
| `/api/file` | GET/DELETE | 读取/删除文件 | `path`, `download` |
| `/api/realtime/config` | GET | 实时语音面试配置 | 无 |
| `/api/openapi.json` | GET | OpenAPI 规范（部分） | 无 |

**认证**：设置环境变量 `AGENT_DASHBOARD_TOKEN` 启用 Bearer token 认证（API 端点需要）。不设置时处于 dev mode（无需认证）。

```bash
# 启用认证
export AGENT_DASHBOARD_TOKEN="your-secret-token"
```

除上表 HTTP 端点外，实时语音面试使用独立的 WebSocket 代理：

| 端点 | 方法 | 说明 |
|------|------|------|
| `ws://127.0.0.1:8766` | WebSocket | 浏览器 ↔ 火山引擎 SC2.0 音频流代理；控制消息为 JSON `{type:start/end/abandon, ...}`，音频为二进制 PCM 帧 |

#### 模拟面试 Tab 使用说明

1. **选择职位**：下拉只列有求职材料草稿的职位；无草稿需先在「材料审核台」生成并确认。
2. **配置项**：
   - `用 prep 题库`：勾选后严格使用该职位的 `interview.json` 题库，不追问、不编答案。
   - `focus 关键词`：只保留题库中命中关键词的题；命中 0 题时后端直接返回「未命中题库题目」，不会静默退回全题库。
   - `难度`：easy/medium/hard 软提示，使用 prep 题库时题量不变。
   - `模式`：文字面试 / 实时语音（实时语音未启用时自动回落到文字模式）。
   - `朗读面试官`：**默认关闭**，需要浏览器 TTS 朗读面试官回复时再勾选。
3. **按钮默认状态**：未选择职位时「开始面试」禁用；全默认且无任何记录时「清空」禁用；底部输入框占位提示「开始面试后可输入...」。
4. **文字面试**：点击「开始面试」→ 面试官开场 → 输入回答回车发送；回复为 SSE 流式输出。可勾选「朗读面试官」用浏览器 TTS 朗读。
5. **实时语音**：需 Chrome/Edge 授权麦克风；浏览器通过 `ws://127.0.0.1:8766` 采集 PCM 并直连火山引擎做 ASR/TTS。
6. **结束 / 清空**：
   - 「结束面试」保存记录并生成评估（题目没问完会标注“中途结束”）。
   - 「🗑 清空」在有进行中会话时先弹确认；确认后调用 abandon 丢弃当前会话（不落盘），并恢复表单默认值。
7. **产物**：文字面试 `_mock_interview.md` + `_mock_interview_assessment.txt`；实时语音 `_realtime_mock.md` + `_realtime_mock_assessment.txt`；「已生成文件」Tab 可预览/下载。

---

## 服务运维

### 启动 / 停止 / 重启

```bash
job-agent serve --daemon    # 后台启动（写 data/dashboard.pid，日志进 data/dashboard.log）
job-agent serve --stop      # 按 pid 文件停止
# 重启 = --stop 后再 --daemon（前台模式直接 Ctrl+C）
```

> Windows 下 `--stop` 用进程句柄终止；若 pid 文件丢失但进程还在，可用任务管理器结束 `python -m agent_core.server.serve` 进程后删除 `data/dashboard.pid`。

### 健康检查

```bash
curl -s http://127.0.0.1:8765/api/pipeline          # Dashboard 主服务
curl -s http://127.0.0.1:8765/api/realtime/config    # 实时语音是否可用
```

- 期望 `{"enabled": true, "ws_port": 8766}` 表示实时语音代理已启用；`enabled:false` 通常是因为 `realtime.enabled=false` 或 VOLC_* 三个密钥不完整。
- 实时语音代理随 Dashboard 启动（`serve` 启动时调用 `start_proxy_in_thread`），**不需要单独起进程**；浏览器 WS 端点固定为 `ws://127.0.0.1:8766`。

### 端口与进程

| 项 | 默认值 | 说明 |
|----|--------|------|
| Dashboard HTTP | `127.0.0.1:8765` | 只监听本机回环 |
| 实时语音 WS | `127.0.0.1:8766` | 仅在 `realtime.enabled=true` 且密钥齐全时监听 |
| PID 文件 | `data/dashboard.pid` | `serve --daemon` 写入，`--stop` 读取 |
| 主日志 | `data/dashboard.log` | daemon 模式下 Dashboard + 实时语音代理日志 |
| 业务日志 | `data/agent.log` | CLI pipeline 等任务日志 |

### 日志排查要点

- 实时语音连接/ASR/TTS 问题先看 `data/dashboard.log`，搜索 `realtime` / `Volc` / `ws` 关键字。
- 火山引擎额度类错误（如 `45000292 quota exceeded`）不是代码 bug，等待配额恢复后重试。
- 测试产物和截图证据统一保留在 `data/log_archive/`，不要散落在项目根目录。

---

### chat -- 对话模式

启动自然语言交互 REPL，DeepSeek function-calling 自动调用底层工具。

```bash
job-agent chat
```

支持的对话操作：搜索岗位、查看详情、投递追踪、简历定制、HR打招呼消息、面试准备、Offer 评估、薪资建议、Cookie 检查。共 11 个工具。

示例对话：

```
你: 搜深圳的AMR岗位
Agent: [调用工具] 找到 48 个岗位...

你: 帮我看看投了哪些
Agent: [调用工具] 共 3 条投递记录...

你: 把刚才那个宁德时代的岗位定制简历
Agent: [调用工具] 简历已生成...
```

---

## Pipeline 阶段说明

Pipeline 是一个模块化的流程，通过 `--stages` 参数可灵活组合各阶段。

### 阶段顺序与依赖

```
search -> filter -> (enrich) -> match
```

- 每个阶段使用前一阶段的输出作为输入
- 如果跳过某阶段，下一阶段会自动回退到可用数据源（例如跳过 filter 时，match 直接使用 search 结果）
- `enrich` 阶段默认不运行（需配置 `matching.enrich_in_pipeline: true`）

### 各阶段详解

| 阶段 | 做什么 | 关键参数 | 成本 |
|------|--------|---------|------|
| **search** | 多平台并发搜索，HTTP API 直连（非浏览器），跨平台 exact-match 去重（公司名 75% fuzzy 归一化） | 平台、方向、关键词 | 低（HTTP 请求） |
| **filter** | 规则过滤：排除关键词、薪资下限、地点 | `exclude_keywords`、`min_salary`、`location` | 零（纯内存） |
| **enrich** | 抓取完整 JD 描述（按 salary_max 降序取 top N） | `enrich_in_pipeline`、`enrich_top_n` | 中（额外 HTTP 请求，易触发反爬） |
| **match** | LLM 精排，并发 5，JSON 强制 + 重试 2 次，按 `match_min_score` 阈值过滤 | `match_min_score` | 高（LLM API 调用，仅对人工标记的岗位调用） |

### 常用组合

```bash
# 只搜不看（快速扫市场）
job-agent pipeline --stages search

# 仅搜索+过滤（不花 LLM 费用）
job-agent pipeline --stages search,filter

# 仅重新精排（已有搜索结果，如更新了 match_min_score）
job-agent pipeline --stages match

# 全流程
job-agent pipeline --stages search,filter,match
```

---

## 职位源适配器

### 已实现（8 源）

| 平台 | 配置键 | 类型 | 登录方式 | 反爬情况 |
|------|--------|------|---------|---------|
| **BOSS 直聘** | `boss_zhipin` | 招聘平台 | Cookie（手动导出） | code-37 反爬，`__zp_stoken__` 短效（几小时~天），频繁调用易触发 |
| **猎聘** | `liepin` | 招聘平台 | Cookie（手动导出） | 较干净，`lt_auth` 有效期较长 |
| **智联招聘** | `zhilian` | 招聘平台 | Playwright 浏览器（headed）+ Cookie | Akamai Bot Manager 保护，必须用活体浏览器，静态 Cookie 可能被软屏蔽 |
| **腾讯** | `tencent` | 公司官网 | 无需登录（公开 API） | 无 |
| **网易** | `netease` | 公司官网 | 无需登录（公开 API） | 无 |
| **比亚迪** | `byd` | 公司官网 | 无需登录（公开 API） | 无 |
| **北方华创** | `naura` | 公司官网 | 无需登录（Beisen API） | 无 |
| **长飞光纤** | `yofc` | 公司官网 | 无需登录（Beisen/zhiye.com API） | 无 |

### 未实现（存根）

| 平台 | 配置键 | 状态 |
|------|--------|------|
| 前程无忧 | `job51` | `NotImplementedError`，用户暂不接入 |
| 脉脉 | `maimai` | `NotImplementedError`，用户暂不接入 |

### 各平台注意事项

- **BOSS 直聘**：Cookie 过期后搜索返回 code-37，需重新导出 Cookie 并 `import-cookies`。全量 JD 抓取（`FETCH_FULL_JD`）默认关闭，因为批量抓 10 次以上就会触发反爬。
- **智联招聘**：GET 端点被 Akamai 完全屏蔽（count=0），POST 端点可用但需要有效 Cookie。浏览器模式下登录一次后 profile 持久化在 `data/zhilian_browser_profile/`（gitignored），长期可用。
- **公司官网类**（腾讯/网易/比亚迪/北方华创/长飞）：公开 API 无需 Cookie，但返回数据格式各异，由各适配器归一化到统一 Job 模型。

---

## 数据与存储

### 数据库

所有数据存储在 `data/agent.db`（SQLite，WAL 模式，外键开启）。Schema 版本化管理，启动时自动迁移。

### 12 张业务表

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `jobs` | 职位主表 | id, title, company, company_normalized, salary_min/max, description, platforms(JSON), urls(JSON), direction, first_seen, last_seen, is_new |
| `applications` | 投递记录 | id, job_id(FK UNIQUE v10), status, resume_version, applied_at, updated_at, notes |
| `timelines` | 状态变更审计 | id, application_id(FK), from_status, to_status, created_at |
| `match_results` | LLM 精排结果 | id, job_id(FK), match_score, match_reason, missing_skills(JSON), strengths(JSON), job_title, company, direction, created_at |
| `pipeline_runs` | Pipeline 执行记录 | id, stage, created_at, job_count |
| `platform_sessions` | Cookie 存储 | platform, cookie_data, expires_at, updated_at |
| `schedules` | 调度任务 | direction, last_run_at, last_status, last_result_count, next_run_at |
| `search_status` | 搜索日志 | search_id, platform, status, result_count, error_message, created_at |
| `generated_files` | 生成文件索引 | id, filename, file_type, file_path, created_at |
| `match_feedback` | 匹配评分反馈 | id, match_result_id(FK), feedback, created_at |
| `material_drafts` | 简历+HR消息草稿 | id, job_id(FK), draft_type, content, status, feedback, version, created_at（v12 增 interview_prep_md / interview_confirmed） |
| `offer_evaluations` | Offer 评估结果缓存（v11） | id, company, title, salary, evaluation_json, created_at |

另有 `schema_version` 系统表用于数据库迁移管理。

### 数据文件

| 内容 | 路径 |
|------|------|
| 数据库 | `data/agent.db`（SQLite，WAL） |
| 数据库备份 | `data/backups/`（手工备份；`data/agent.db.bak-pre-v10` 为 v10 前快照） |
| 业务日志 | `data/agent.log` |
| Dashboard 日志 / PID | `data/dashboard.log` / `data/dashboard.pid` |
| Cookie（BOSS） | `data/cookies/boss_zhipin.json` |
| Cookie（猎聘） | `data/cookies/liepin.json` |
| Cookie（智联） | `data/zhilian_browser_profile/`（Playwright 持久化 profile） |
| Offer 输入 .txt | `offers/<公司>_<职位>.txt`（项目根目录 `offers/`，非 `data/offers/`） |
| 简历模板 | `resumes/*.txt` |
| 定制简历 .docx | `output/<公司>_<岗位>.docx` |
| 简历预览 .md | `output/<公司>_<岗位>.md` |
| HR打招呼消息 | `output/<公司>_<岗位>_hrmsg.md` |
| 面试准备 | `output/<公司>_<岗位>_interview.md` + `.json`（json 为题库/模拟面试导入源） |
| 模拟面试记录（终端） | `output/<公司>_<岗位>_mock_interview.md` + `_assessment.json` |
| 模拟面试记录（Dashboard 文字） | `output/<公司>_<岗位>_mock_interview.md` + `_assessment.txt` |
| 模拟面试记录（实时语音） | `output/<公司>_<岗位>_realtime_mock.md` + `_realtime_mock_assessment.txt` |
| 调度状态 | `data/scheduler_state.json` |
| 测试证据 / 截图 / 音频 | `data/log_archive/`（按测试批次归档，勿删） |

---

## 常见问题 / 排错

### 搜不到岗位？

1. 运行 `job-agent check-cookies` 检查 Cookie 是否过期
2. 运行 `job-agent check-cookies --probe` 带探活验证
3. 检查 `config.yaml` 中对应平台的 `enabled` 是否为 `true`
4. 确认关键词是否过于狭窄

### BOSS 直聘返回 code-37？

`__zp_stoken__` 是短效 Cookie，过期或频繁调用都会触发。解决：重新在 Chrome 中登录 BOSS 直聘 -> 导出 Cookie -> `job-agent import-cookies`。

### 智联招聘搜不到岗位？

智联使用 Akamai Bot Manager，静态 Cookie 可能被软屏蔽。建议：
1. 确保浏览器 profile 存在（`data/zhilian_browser_profile/`）
2. 使用 Playwright 浏览器模式（默认），不要手动替换 Cookie
3. 如仍无效，删除 profile 目录后重新运行让适配器重建

### LLM 命令不可用？

检查 `DEEPSEEK_API_KEY` 环境变量是否设置：

```bash
# Windows
echo %DEEPSEEK_API_KEY%

# Linux / Mac
echo $DEEPSEEK_API_KEY
```

如果未设置，参考"首次配置"章节设置。不需要 LLM 的命令（`search`、`login`、`track`、`check-cookies`）不受影响。

### 简历更新了怎么重新匹配？

```bash
# 批量
job-agent rematch --all-since 2026-06-01

# 单个
job-agent rematch <job-id>
```

### 外部投递怎么记录？

支持通过 URL 手动补录：

```bash
job-agent track add https://www.zhipin.com/job_detail/xxx.html
```

系统会自动创建占位岗位记录。

### 定时搜岗不工作？

```bash
job-agent schedule status
```

检查状态是否 `Enabled: true`，上次运行时间和错误信息。确认 daemon 正在前台运行（`job-agent schedule run`）。

### Dashboard 无法访问？

- 确认 `job-agent serve` 正在运行；后台模式可查看 `data/dashboard.pid`，或直接 `curl http://127.0.0.1:8765/`
- 默认端口 8765，如被占用可用 `--port` 换端口
- 如果设置了 `AGENT_DASHBOARD_TOKEN`，需要在请求中带 `Authorization: Bearer <token>` 头（浏览器直接访问 `/` 和 `/docs` 不需要认证）

### 实时语音面试不可用？

1. 访问 `http://127.0.0.1:8765/api/realtime/config`，`enabled:false` 说明后端未启用。
2. 检查 `config.yaml` 的 `realtime.enabled` 是否为 `true`。
3. 检查 `VOLC_APP_KEY` / `VOLC_APP_ID` / `VOLC_ACCESS_KEY` 三个环境变量是否都已设置（密钥改动后需重启 Dashboard）。
4. 浏览器需允许麦克风权限，且 WebSocket 端口 8766 未被其他程序占用。
5. 火山引擎额度类报错（如 `45000292 quota exceeded`）等待配额恢复后重试。

### 模拟面试提示 focus 未命中题库？

`--focus` / `focus` 关键词是“过滤”而不是“加题”。改成题库中实际存在的关键词（如「技术」「行为」「项目深挖」）或清空 focus 后重试；清空后会使用完整题库。

### 开了思考模式后响应变慢？

这是正常现象。思考模式下模型会先输出内部推理链（`reasoning_content`），增加了额外的 token 消耗和延迟。预计延迟增加 1.5-3 倍，token 消耗增加 2-5 倍。建议只在需要深度推理的阶段（`match` 精排、`interview-prep`）开启，日常搜索/schedule 保持关闭。

---

## 测试与质量

### 运行测试

```bash
# 全部测试（2026-08-18 实测 1306 passed / 6 skipped / 0 failed；含集成 --run-integration 为 1311 passed / 1 skipped）
python -m pytest tests/ -q
# 含 Windows Toast 集成
python -m pytest -q --run-integration

# 基础验证
python tests/phase1_verify.py

# 单模块快速回归（模拟面试相关）
python -m pytest tests/test_mock_end.py tests/test_mock_api.py tests/test_realtime_proxy.py -q
```

> ⚠️ **本地测试前需保证 `resumes/` 目录下有至少一份简历文件**（如 `echo test > resumes/example_resume.txt`）。
> 否则 `match` 相关测试（`test_core.py` / `test_match_legacy.py` 等约 4 项）会因 `load_resume` 找不到简历而
> 跳过 LLM 调用并失败（`resume load failed`）。CI 已通过创建示例简历规避，本地裸 clone 首次跑测试前需自行创建。
> 测试产物会写入 `resumes/`（上传流程）与 `output/`，测试证据归档在 `data/log_archive/`。

### 代码质量工具

```bash
# 格式（项目标准为 black，pre-commit 会强制执行）
python -m black --check agent_core scripts tests

# Lint（ruff，源码 + 脚本 + 测试全扫）
python -m ruff check agent_core scripts tests

# 类型检查（mypy）
python -m mypy agent_core --ignore-missing-imports

# 安全扫描（bandit）
python -m bandit -r agent_core -c pyproject.toml

# LLM 命名规范（禁外名，如 claude/anthropic/glm 等）
python scripts/check_llm_naming.py
```

以上命令与 CI 保持一致（CI 额外跑 pytest-cov）。

覆盖率基准：2026-08-18 实测 **84.4%**（门槛 70）；主要模块：`serve.py` 80.3%、`realtime_proxy.py` 93.3%、`boss_browser.py` 85.5%、`playwright_jd.py` 89.7%、`zhilian.py` 92.9%。

---

## 本手册生成说明

- **初版**：2026-06-25；**最近全面订正**：2026-08-16
- **2026-08-16 更新内容**：补全 `cleanup` 命令；更新 `serve --daemon/--stop` 与「服务运维」章节；补充实时语音面试（火山引擎 SC2.0 / ws 8766 / VOLC_* 密钥）；更新模拟面试 API（新增 `/api/mock-interview/abandon`，download 参数改为 `job_id + mode`）；更新产物命名（Dashboard `_assessment.txt` vs 终端 `_assessment.json`）；同日职位搜索专项：`--keyword` 必填、平台别名、`--max-pages`、search_max_pages 配置、关键词相关性过滤、search_status 按平台展示、智联浏览器 cookie 判定等；同步测试数（703 collected / 697 passed / 6 skipped）与质量门禁。
- **2026-08-17 更新内容**：Phase0 数据安全修复（DB busy_timeout、tracker 事务、match 二次意见 resume 缓存、去重 Toast、company_normalized 兜底）；Phase1 serve.py 拆出 dashboard_html/http_utils/daemon 并修复 token 鉴权前端集成；Phase2 新增平台 registry/browser_utils、搜索并发上限；Phase3 新增 registry/browser_utils/http_utils/scripts/auth/浏览器工具/serve handler/面试准备 prompt/tailor 截断重试测试并把覆盖率门槛提到 54；另修复模拟面试评估卡死（`ASSESSMENT_TIMEOUT_SECONDS=120`）、生成求职材料卡死（`LLM_CALL_TIMEOUT_SECONDS=300` + `/api/materials/progress` 进度轮询）、反问环节防提前结束（文字+实时）、实时语音评估严格 JSON 重试、结束弹窗文件兜底。测试基线同步为 823 collected / 817 passed / 6 skipped。
- **实测基准（2026-08-17）**：`pytest` 817 passed / 6 skipped / 0 failed；black / ruff / mypy / bandit / check_llm_naming 全部通过；Dashboard 8765 + 实时语音 WS 8766 全流程实测通过。
- **2026-08-18 更新内容**：并行补齐 12 个 `tests/test_*_more.py`，全量测试从 817 → 1306 passed，覆盖率 59.9% → **84.4%**，门槛 54 → **70**；含 Windows Toast 集成实测 1311 passed / 1 skipped。Dashboard 10 Tab UI 全面优化（投递状态统计/手动新增、已生成文件搜索/排序/加载更多、匹配缺口点击展开、流水线 9 阶段漏斗等），新增 `DELETE /api/match/feedback` 与 `POST /api/application`。新增 `docs/README.md` 文档入口与 `docs/retrospective-2026-08-18-full-delivery.md` 复盘。
- **实际读过的关键文件**：
  - `agent_core/cli.py` — 全部 17 个 CLI 命令定义（含 `cleanup`）
  - `agent_core/config.py` — Pydantic 配置模型 + `.env` 加载 + `RealtimeConfig`
  - `config.yaml` — 当前配置文件（realtime.enabled=true）
  - `pyproject.toml` — 入口点、依赖、工具配置、覆盖率门槛
  - `agent_core/server/serve.py` — Dashboard HTTP 服务器（10 tab）+ 全部 API 路由 + daemon 启停
  - `agent_core/server/realtime_proxy.py` — 实时语音 WebSocket 代理（浏览器 ↔ 火山引擎 SC2.0）
  - `agent_core/pipeline/interview_prep.py` — 面试准备 + 终端/SSE 模拟面试 + 题库匹配/计数 + 评估
  - `agent_core/pipeline/file_catalog.py` — generated_files 索引（catalog/backfill）
  - `agent_core/pipeline/orchestrator.py` — Pipeline 编排（search/filter/enrich/match）
  - `agent_core/storage/db.py` — SQLite 迁移（schema v12 / 12 张业务表）
  - `agent_core/storage/models.py` — 数据模型 + 合法状态列表
  - `agent_core/llm/providers.py` — DeepSeek Provider + 重试逻辑
  - `agent_core/tracking/tracker.py` — 投递追踪状态机 + 时间线
  - `agent_core/scheduler/scheduler.py` — 定时调度 + PID 锁
  - `agent_core/agent/tools.py` + `agent/repl.py` — Chat 模式工具与 REPL
  - `scripts/import_cookies.py` / `scripts/check_llm_naming.py` — 辅助脚本
  - `docs/job-agent-test-flow.md` — 完整测试 SOP；`docs/retrospective-2026-08-16-mock-interview.md` — 模拟面试专项复盘
- **与代码不符之处**：已按 2026-08-16 代码现状订正；历史文档若仍写「schema v11」「模拟面试评估只存 json」「download 用 session_id」均为旧信息。
- **2026-08-29 整理**：清理项目缓存与调试残留（`__pycache__`/`.mypy_cache`/`.pytest_cache`/`.ruff_cache`/`.playwright-mcp`/空 `unused/`）；删除一次性调试脚本 `scripts/dev/_query_draft.py`；`website/index.html` 营销页纳入版本控制（.gitignore 加例外）；README/docs 索引同步区分公开文档与内部 gitignored 文档；本手册「运行测试」补充 `resumes/` 非空的前置要求。`data/log_archive/`（95MB 历史测试证据）与 `data/backups/` 按既有约定保留。
- **相关复盘**：`docs/retrospective-2026-08-16-mock-interview.md`（模拟面试）；`docs/retrospective-2026-08-16-search-audit.md`（职位搜索）。
