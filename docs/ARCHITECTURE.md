# JobAgent 项目架构与文件清单

> 求职 AI Agent — 自动搜索 / LLM 精排 / 简历定制 / HR 消息 / 材料审核 / 投递追踪 / 面试准备与模拟面试
> 更新：2026-08-17（对齐代码现状：56 个源文件 / 17 CLI / 12 张业务表 / 8 live 平台 / 10 tab / schema v12）

## 目录结构（完整文件清单）

```
agent-core/
├── agent_core/                          # 主包（56 个 Python 模块）
│   ├── __init__.py
│   ├── cli.py                           # Typer CLI：17 个命令（search/pipeline/match/tailor/serve/cleanup/...）
│   ├── config.py                        # Pydantic 配置 + .env 加载 + RealtimeConfig（火山 SC2.0）
│   ├── cookie_health.py                 # Cookie 体检 + 重抓指引
│   ├── agent/                           # chat 对话模式
│   │   ├── tools.py                     # 11 个 function-calling 工具（ToolDispatcher）
│   │   └── repl.py                      # 交互式 REPL
│   ├── llm/                             # LLM 层
│   │   ├── base.py                      # Provider 抽象
│   │   └── providers.py                 # DeepSeekProvider + 指数退避重试 + thinking
│   ├── notify/
│   │   └── windows_toast.py             # Windows 桌面通知（winotify + PowerShell fallback）
│   ├── pipeline/                        # 流水线模块
│   │   ├── search.py                    # 多平台搜索 + 跨平台去重
│   │   ├── filter.py                    # 规则过滤
│   │   ├── enrichment.py                # JD 补全（enrich_job_jd）
│   │   ├── match.py                     # LLM 精排（并发 5 + JSON 强制 + 二次意见仲裁）
│   │   ├── orchestrator.py              # search/filter/enrich/match 编排 + 测试环境写库保护
│   │   ├── tailor.py                    # 简历定制（事实防幻觉 + .docx/.md）
│   │   ├── cover_letter.py              # HR 打招呼消息（150-200 字）
│   │   ├── interview_prep.py            # 面试题预测 + 终端/SSE 模拟面试 + 题库匹配/评估
│   │   ├── offer_eval.py                # Offer 8 维评估 + 多 Offer 对比
│   │   ├── salary_advice.py             # 薪资谈判策略
│   │   ├── file_catalog.py              # generated_files 索引（catalog_file / backfill_from_disk）
│   │   └── text_utils.py                # 长文本完整性检测 + 重试公共工具
│   ├── platforms/                       # 职位源适配器（8 live + 2 存根）
│   │   ├── base.py                      # Job 模型 + PlatformAdapter 抽象
│   │   ├── boss_zhipin.py / boss_browser.py       # BOSS HTTP API + 浏览器兜底
│   │   ├── liepin.py / zhilian.py / zhilian_browser.py  # 猎聘 / 智联双模式
│   │   ├── tencent.py / netease.py / byd.py / naura.py / yofc.py  # 公司官网公开 API
│   │   ├── job51.py / maimai.py         # 存根（未实现）
│   │   ├── company_site.py              # 通用公司官网解析
│   │   ├── playwright_jd.py             # Playwright JD 抓取
│   │   ├── registry.py                  # 平台适配器注册表/工厂（统一入口）
│   │   ├── browser_utils.py             # 持久浏览器共享锁清理/失败标记
│   │   └── cookie_utils.py              # Cookie 格式转换
│   ├── scheduler/
│   │   └── scheduler.py                 # 定时搜索 + 投递提醒 + PID 锁
│   ├── server/
│   │   ├── serve.py                     # Dashboard HTTP 服务（10 tab + 全部 API 路由）
│   │   ├── dashboard_html.py            # 内嵌前端 HTML/CSS/JS/OpenAPI（从 serve.py 拆出）
│   │   ├── http_utils.py                # HTTP 响应/鉴权/JSON 工具（从 serve.py 拆出）
│   │   ├── daemon.py                    # Dashboard 守护进程启停（从 serve.py 拆出）
│   │   └── realtime_proxy.py            # 实时语音 WS 代理（浏览器 8766 ↔ 火山引擎 SC2.0）
│   ├── storage/
│   │   ├── db.py                        # SQLite + 12 版本迁移（schema v12）
│   │   └── models.py                    # 数据模型 + 合法状态列表
│   └── tracking/
│       └── tracker.py                   # 投递追踪状态机 + 时间线
│
├── tests/                               # pytest（65 个 py 文件，1306 passed / 6 skipped）
│   ├── test_core.py / test_advanced.py / test_cli.py / test_chat.py      # 核心 + CLI + chat
│   ├── test_boss.py / test_liepin.py / test_zhilian.py / test_byd.py ... # 各平台适配器
│   ├── test_serve*.py / test_serve_more.py / test_serve_handlers2.py   # Dashboard handler/feature/timeline
│   ├── test_mock_api.py / test_mock_end.py                               # 模拟面试 HTTP / 收尾逻辑
│   ├── test_realtime_protocol.py / test_realtime_proxy.py / test_realtime_proxy_more.py  # 实时语音协议 / 代理
│   ├── test_materials.py / test_interview_prep_confirm.py                # 材料与面试准备
│   ├── test_tracking_full.py / test_db_migration.py / test_enterprise_jd.py
│   ├── test_registry.py / test_browser_utils.py / test_http_utils.py / test_serve_auth.py / test_scripts.py
│   ├── test_zhilian_more.py / test_boss_browser_more.py / test_playwright_jd_more.py / test_orchestrator_more.py
│   ├── test_cli_more.py / test_repl_more.py / test_daemon_more.py / test_providers_more.py / test_scheduler_more.py
│   └── conftest.py / phase1_verify.py / __init__.py
│
├── docs/                                # 文档
│   ├── USAGE.md                         # 使用/操作手册（启动、CLI、Dashboard、运维、排错）
│   ├── ARCHITECTURE.md                  # 本文件（架构 + 文件清单）
│   ├── development-plan.md              # 开发计划 + 历史决策
│   ├── job-agent-test-flow.md           # 完整测试 SOP（阶段 0-10 + Dashboard 10 tab）
│   ├── cookie-refresh-boss.md / cookie-refresh-zhilian.md  # Cookie 重抓指引
│   ├── dedup-eval-guide.md              # 跨平台去重评估手册
│   ├── retrospective-2026-06-25.md / retrospective-2026-08-16-mock-interview.md  # 复盘
│   ├── retrospective-2026-08-16-search-audit.md  # 职位搜索专项复盘
│   ├── unfinished-work.md               # 未完成工作清单
│   ├── project-structure.md             # 文件分类索引（2026-08-18）
│   └── research/pharma-recruitment-api-research.md
│
├── scripts/                             # 辅助脚本
│   ├── import_cookies.py                # 浏览器 Cookie 导入
│   └── check_llm_naming.py              # LLM 命名规范检查（禁外名）
│
├── AGENTS.md                            # AI 助手长期记忆（行为铁律 + DOM/UI 防错清单 + 权威实现索引）
├── config.yaml                          # 当前配置（platforms/directions/llm/schedule/realtime）
├── pyproject.toml                       # 依赖 + entrypoint + ruff/mypy/bandit/pytest/coverage 配置
├── .pre-commit-config.yaml              # black + ruff pre-commit
├── .github/workflows/ci.yml             # CI：ruff/mypy/bandit/命名检查/pytest-cov(门槛 70)
├── .env                                 # API 密钥（gitignored）
├── data/                                # 运行时数据（gitignored）
│   ├── agent.db                         # SQLite（WAL，schema v12）
│   ├── agent.db.bak-pre-v10 / backups/  # 历史快照 + 手工备份
│   ├── agent.log / dashboard.log / dashboard.pid  # 日志与 daemon PID
│   ├── cookies/                         # 平台 Cookie JSON
│   ├── zhilian_browser_profile/         # 智联 Playwright 持久 profile（登录态）
│   ├── boss_browser_profile/            # BOSS 浏览器 profile
│   ├── scheduler_state.json             # 调度状态
│   └── log_archive/                     # 测试证据：截图/音频/时间线/备份（勿删）
├── output/                              # 生成产物（简历/HR消息/面试准备/模拟面试/Offer）
├── offers/                              # Offer 输入 .txt
├── resumes/                             # 原始简历
└── docs/reference/                       # 参考资料（火山引擎实时语音接入文档等）

```

## 数据流

```
search(8源) -> 人工筛选(🌟❌) -> enrich(按需) -> LLM精排(match)
   -> 生成简历+HR消息(tailor + cover_letter) -> 材料审核台(草稿→确认)
   -> 投递追踪(applications 自动建记录) -> 周期提醒(scheduler toast)
   -> 面试准备(interview-prep) -> 模拟面试(文字 SSE / 实时语音 WS)
```

## Dashboard 10 个 Tab

| Tab | 功能 |
|---|---|
| 📄 文件上传 | 上传/管理原始简历 + Offer .txt（统一入口） |
| 📋 人工初筛 | 岗位列表 + 🌟/❌ 标记 + 批量 |
| 🎯 Agent智能匹配结果 | 精排结果 + 缺口分级 + 多选生成简历与求职信 |
| 📝 材料审核台 | 草稿审核（简历+HR消息）+ 再生成(feedback) + 确认保存 |
| 📅 投递追踪 | 投递状态区（状态下拉 + 周期设置）+ 时间线 |
| 🎤 模拟面试 | 文字（SSE）+ 实时语音（WS 8766 ↔ 火山 SC2.0）；prep 题库/focus/难度软提示/评估 |
| 💼 Offer评估 | 8 维评估 + 多 Offer 对比 + 缓存预览 |
| 💰 薪资谈判 | 谈判策略与话术（锚点可视化 + 导入已评估 Offer） |
| 📁 已生成文件 | catalog 驱动的生成文件列表（预览/下载/zip/删除） |
| ⚙️ Pipeline | 6 阶段状态（search/filter/match/tailor/materials/track）+ 后置 3 卡 |

## API 分组

| 组 | 端点 |
|---|---|
| 岗位与筛选 | `/api/results`、`/api/flag/{id}`、`/api/flag/batch`、`/api/jd/*` |
| 匹配 | `/api/match`、`/api/match/run`、`/api/match/progress`、`/api/match/feedback` |
| 材料与投递 | `/api/materials/*`、`/api/applications`、`/api/application/{update,reminder}` |
| 简历与文件 | `/api/resumes`、`/api/resume/*`、`/api/files`、`/api/files/zip`、`/api/file` |
| 模拟面试 | `/api/mock-interview/{start,reply,end,abandon}`、`latest-transcript`、`/api/mock-assessment/preview`、`/api/realtime/config` |
| Offer/薪资 | `/api/offer/*`、`/api/salary-advice{,/save}` |
| 元信息 | `/api/pipeline`、`/api/openapi.json`、`/docs` |

实时语音不走 HTTP：浏览器 WebSocket `ws://127.0.0.1:8766` 直连 `server/realtime_proxy.py`，再转发火山引擎 SC2.0（StartConnection/StartSession/TaskRequest 二进制协议）。

## 关键数据表（12 张）

| 表 | 用途 |
|---|---|
| jobs | 职位（8 源抓取） |
| match_results / match_feedback | LLM 精排结果 / 评分校准反馈 |
| generated_files | 生成文件索引（file_catalog 写入） |
| material_drafts | 简历+HR消息+面试准备草稿（v9，v12 加 interview_prep_md/confirmed） |
| offer_evaluations | Offer 评估结果缓存（v11） |
| applications / timelines | 投递状态 + 状态变更审计（v10 job_id UNIQUE） |
| pipeline_runs / search_status | 流水线运行记录 / 搜索状态 |
| platform_sessions | Cookie 存储 |
| schedules | 调度任务 |

另有 `schema_version` 迁移记录表。

## 运行与运维

```bash
job-agent serve --daemon          # 后台启动 Dashboard（http://127.0.0.1:8765，WS 8766）
job-agent serve --stop            # 停止后台进程
job-agent chat                    # 对话 agent（function calling）
job-agent search --keyword AMR --platforms boss_zhipin,liepin
job-agent pipeline --stages search,filter,match
job-agent tailor <job-id> / cover-letter <job-id> / interview-prep <job-id>
job-agent mock-interview <job-id> --from-prep --focus 项目深挖 --difficulty easy
job-agent schedule on / run / status / off
job-agent cleanup --dry-run / --cache / --logs / --all
```

详细操作见 `docs/USAGE.md`，测试 SOP 见 `docs/job-agent-test-flow.md`。

## 质量状态（2026-08-18）

- pytest：普通全量 **1306 passed / 6 skipped / 0 failed**；含 Windows Toast 集成 **1311 passed / 1 skipped / 0 failed**（约 8 分钟）
- black：`agent_core + scripts + tests` 全量格式化通过（pre-commit 强制执行）
- ruff：`agent_core + scripts + tests` 全量 0 告警
- mypy：56 个源文件 0 错误；bandit：0 告警（daemon subprocess 已加 nosec 说明）
- `scripts/check_llm_naming.py`：通过（禁 claude/anthropic/glm 等外名）
- 覆盖率：84.4%（门槛 70；serve.py 80.3% / realtime_proxy.py 93.3% / boss_browser.py 85.5% / playwright_jd.py 89.7%）
- 约束：不 commit / 不 push（用户私有仓库约定）
