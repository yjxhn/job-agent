# 求职 AI Agent

自动搜职位→筛选→初筛→LLM精排匹配→简历定制→投递追踪的智能求职助手。

## 项目简介

求职 AI Agent（包名 `agent_core`）是一个自动化求职工具，从职位搜索到投递追踪全流程覆盖。支持多平台并发搜索、跨平台去重、规则初筛、LLM 精排匹配、简历定制和投递状态追踪。底层使用 DeepSeek 作为 LLM（通过 `DEEPSEEK_API_KEY` 环境变量配置）。

## 架构流程

```
搜索 (Search) → 筛选 (Filter) → 初筛 (Prescreen) → 精排 (Match) → 简历定制 (Tailor) → 投递追踪 (Track)
     ↓               ↓                ↓              ↓              ↓              ↓
 多平台并发      薪资/地点/      规则打分+        LLM 精排       生成 .docx     7 阶段状态机
 HTTP API 直连   排除词过滤      方向选择        并发 5          + .md          + 时间线
 跨平台去重                   取 top 30      JSON 强制       自动打开       手动补录
                           省成本           + 重试          岗位链接       外部投递
```

### 各阶段说明

- **Search**: 多平台并发搜索，已从 Playwright 改为 HTTP API 直连（绕过反爬），支持跨平台去重
- **Filter**: 薪资、地点、排除词过滤
- **Prescreen**: 规则打分 + 方向选择，取 top 30 省成本，low-confidence 方向匹配有 -10 惩罚
- **Match**: LLM 精排，并发 5，JSON 强制 + 重试，通过 `match_min_score` 阈值过滤
- **Tailor**: 生成定制简历（.docx + .md），自动打开岗位链接
- **Track**: 7 阶段状态机（已投递→HR已读→约面→一面→二面→Offer→入职，任一可→已终止），支持时间线和手动补录外部投递

## 安装

```bash
cd agent-core
pip install -e .
playwright install chromium  # 仅 login 命令旧路径用，现已改 HTTP API
```

设置 DeepSeek API Key：

```bash
# Windows
setx DEEPSEEK_API_KEY "sk-your-key"

# Linux/Mac
export DEEPSEEK_API_KEY="sk-your-key"
```

## 配置

### config.yaml 主要配置项

```yaml
platforms:
  boss_zhipin:
    enabled: true
    cookie_path: data/cookies/boss.json
  liepin:
    enabled: true
    cookie_path: data/cookies/liepin.json
  job51:          # 存根（未实现）
  zhilian:        # 已实现（POST /c/i/search/positions）
  maimai:         # 存根（未实现）

search:
  min_salary: 15000
  exclude_keywords: ["外包", "派遣"]
  directions:
    industrial_ai_agent:
      keywords: ["工业 AI", "Agent", "智能体"]
      resume_file: resumes/industrial_ai_agent.txt
      feature_words: ["架构", "落地", "0-1"]
    equipment_amr:
      keywords: ["AMR", "移动机器人", "物流机器人"]
      resume_file: resumes/equipment_amr.txt
      feature_words: ["导航", "调度", "路径规划"]

matching:
  prescreen_top_n: 30
  match_min_score: 50

llm:
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY

schedule:
  interval_hours: 6
  quiet_hours: [0, 1, 2, 3, 4, 5, 6, 7]  # 凌晨 0-7 点安静时段

notify:
  toast_enabled: true  # Windows 桌面通知
```

### 环境变量

- `DEEPSEEK_API_KEY`: DeepSeek API 密钥（必需，用于 LLM 精排、简历定制等功能）

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
   python import_cookies.py data/cookies/boss_export.json boss --domain zhipin.com

   # 或使用 CLI
   job-agent import-cookies data/cookies/boss_export.json boss --domain zhipin.com

   # 猎聘
   python import_cookies.py data/cookies/liepin_export.json liepin --domain liepin.com
   ```

5. **验证 Session Cookie**
   转换器会检查 session cookie 是否存在：
   - `[OK] session cookies: wt2, __zp_stoken__` → 成功
   - `[WARN] 未发现已知 session cookie，请确认导出前已登录。` → 需重新导出

## 命令速查表

### 登录与状态

```bash
job-agent login --platform boss      # 打开浏览器手动登录（旧路径）
job-agent login --platform liepin    # 打开浏览器手动登录（旧路径）
job-agent login --status             # 检查各平台 Cookie 状态
```

### 搜索与匹配

```bash
job-agent search                     # 搜索所有方向的所有平台
job-agent search --direction industrial  # 仅搜索指定方向
job-agent search --platforms boss_zhipin  # 仅搜索指定平台
job-agent pipeline --stages all      # 搜索→筛选→初筛→精排 全流程
job-agent pipeline --stages search,filter  # 仅运行搜索和筛选
job-agent match <job-id>             # 单独评估匹配度（需简历已入库）
```

### 简历与求职信

```bash
job-agent tailor <job-id>            # 定制简历(.docx+.md)，自动打开岗位链接
job-agent cover-letter <job-id>      # 生成求职信
job-agent rematch <job-id>           # 简历更新后重新匹配单个岗位
job-agent rematch --all-since 2026-06-01  # 批量重新匹配（简历更新后）
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
job-agent mock-interview <job-id>    # 终端交互式模拟面试
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
job-agent login --status

# 3. 运行完整流程（搜索→筛选→初筛→精排）
job-agent pipeline --stages all

# 4. 查看匹配结果，选择高匹配度岗位定制简历
job-agent tailor <job-id>

# 5. 投递后记录追踪
job-agent track add <job-id>
job-agent track update <app-id> --status HR已读

# 6. 面试准备
job-agent interview-prep <job-id>
job-agent mock-interview <job-id>

# 7. Offer 评估
job-agent offer-eval --company 宁德时代 --title 高级工程师 --salary 20K-28K

# 8. 开启定时自动搜岗
job-agent schedule on
job-agent schedule run  # 启动 daemon（每 interval_hours 小时一次）
```

## 双平台职位抓取

### Boss 直聘

- **API**: `https://www.zhipin.com/wapi/zpgeek/search/joblist.json` (GET + cookie)
- **职位数据**: `zpData.jobList`
- **反爬**: 存在 code-37 反爬挑战（Cookie 短效或频繁调用触发）

### 猎聘

- **API**: `https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job` (POST + JSON body + cookie)
- **职位数据**: `data.data.jobCardList`
- **反爬**: 干净无反爬

### 优势

- 两平台都不用浏览器，直接 HTTP，绕过 Playwright 反爬
- 跨平台去重，避免重复职位
- 并发搜索，提升效率

## 已知限制

### Cookie 有效期

- Boss 直聘的 `__zp_stoken__` 为短效 Cookie（几小时~一天）
- 过期后搜索返回 code-37 反爬挑战，会弹出 Windows Toast 提示
- 需重新导出 Cookie 并转换
- 频繁调用也易触发 code-37，建议降低搜索频率

### JD 详情抓取

- Boss 完整 JD 详情抓取（`FETCH_FULL_JD`，默认 False）：
  - 单次可用
  - 批量（10 次/搜索）会触发 code-37
  - 故默认关闭
- 猎聘 list API 只有简略字段（无完整 JD 正文），未实现详情抓取

### 平台支持

- **已实现（7 源）**: `boss_zhipin`, `liepin`, `zhilian`（POST API 直连）、`tencent`, `netease`（公开 API）、`byd`（比亚迪，公开 API）、`naura`（北方华创，JSON API + session cookie）
- **存根（未实现）**: `job51`, `maimai`（`NotImplementedError`，用户暂不接入）
- **行业调研 backlog**（verify-before-building，未盲写；详见 `docs/research/`）：
  - **半导体**：中芯/长存（Beisen SSR，需 HTML 爬取）、华虹/兆易/中微（MokaHR 加密 API，需 JS 逆向）、长鑫（站点不可达）
  - **新能源**：宁德时代/晶科/天合（MokaHR 加密）、隆基（WinTalent 需 SPA 上下文）、远景（Avature 无 API）、亿纬（静态 HTML）
  - **制药**：恒瑞/百济/药明/齐鲁/复星——头部药企全部挂第三方闭源平台（智联/前程无忧/脉脉），无公开 API；百济全球站 Workday CXS API 仅覆盖海外岗位。可选替代：丁香园/京东健康（有自建技术栈，待确认）

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

- **测试数量**: 115 个
- **覆盖率**: 约 75%（核心模块 80-100%）
- **测试目录**: `tests/test_core`, `tests/test_advanced`, `tests/test_misc`, `tests/test_cli`, `tests/test_boss`, `tests/test_liepin`, `tests/test_serve`

## 数据文件

| 内容 | 路径 |
|------|------|
| 数据库 | `data/agent.db` |
| 日志 | `data/agent.log` |
| Cookie | `data/cookies/boss.json`, `liepin.json` |
| 简历模板 | `resumes/industrial_ai_agent.txt`, `equipment_amr.txt` |
| 定制简历 | `output/<公司>_<岗位>.docx` |
| 简历预览 | `output/<公司>_<岗位>.md` |
| 求职信 | `output/<公司>_<岗位>_cover_letter.md` |
| 面试准备 | `output/<公司>_<岗位>_interview.md` |
| 模拟面试记录 | `output/<公司>_<岗位>_mock_interview.md` |

## Dashboard

```bash
job-agent serve  # 启动本地 HTTP dashboard
```

访问 http://localhost:8765，支持：
- 搜索框实时过滤
- 方向筛选
- 点击列头排序
- 自动刷新

## FAQ

**搜不到岗？**
→ 运行 `job-agent login --status` 检查 Cookie 是否过期

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