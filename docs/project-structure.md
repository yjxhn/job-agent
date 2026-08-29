# 项目文件分类索引

> 2026-08-18 整理。本文件把 agent-core 的主要文件按用途分类，方便快速定位；同时已清理空目录/缓存，并把草稿脚本归入 `scripts/dev/`。

## 1. 核心代码（agent_core/）

| 分类 | 路径 | 说明 |
|---|---|---|
| 配置 | `agent_core/config.py` | Pydantic 配置模型 |
| CLI | `agent_core/cli.py` | Typer 命令行入口 |
| Agent/对话 | `agent_core/agent/` | REPL + 工具调度 |
| LLM 驱动 | `agent_core/llm/` | Provider + 超时/重试 |
| Pipeline | `agent_core/pipeline/` | 搜索/匹配/定制/面试/Offer/薪资/文本工具 |
| 平台适配 | `agent_core/platforms/` | 各招聘平台 + 浏览器 + 注册表 |
| 调度 | `agent_core/scheduler/` | 定时搜索 + 提醒 |
| 服务 | `agent_core/server/` | Dashboard HTTP + 实时语音 + 守护进程 |
| 存储 | `agent_core/storage/` | SQLite + 模型 |
| 追踪 | `agent_core/tracking/` | 投递状态机 |
| 通知 | `agent_core/notify/` | Windows Toast |
| Cookie 健康 | `agent_core/cookie_health.py` | Cookie 探测 |

## 2. 测试（tests/）

| 分类 | 文件 |
|---|---|
| 核心/CLI/聊天 | `test_core.py` `test_advanced.py` `test_cli.py` `test_chat.py` `test_misc.py` `test_cli_more.py` `test_repl_more.py` |
| 平台 | `test_boss*.py` `test_liepin.py` `test_zhilian*.py` `test_tencent.py` `test_netease.py` `test_byd.py` `test_naura.py` `test_yofc.py` `test_zhilian_more.py` `test_boss_browser_more.py` `test_playwright_jd_more.py` |
| 服务/API | `test_serve*.py` `test_http_utils.py` `test_serve_auth.py` `test_serve_more.py` `test_serve_handlers2.py` |
| 模拟面试 | `test_mock_api.py` `test_mock_end.py` `test_realtime_proxy.py` `test_realtime_proxy_more.py` |
| 工具/浏览器 | `test_browser_utils.py` `test_boss_browser_utils.py` `test_playwright_jd_utils.py` `test_zhilian_browser_utils.py` `test_browser_manager.py` |
| 数据/归档 | `test_file_catalog.py` `test_db_migration.py` `test_cookie_health.py` `test_daemon.py` `test_repl.py` `test_windows_toast.py` `test_stub_platforms.py` `test_text_utils.py` `test_interview_prep_utils.py` `test_scripts.py` `test_daemon_more.py` `test_providers_more.py` `test_scheduler_more.py` |

## 3. 脚本（scripts/）

| 文件 | 说明 |
|---|---|
| `check_llm_naming.py` | LLM 命名规范检查 |
| `import_cookies.py` | 导入平台 Cookie |
| `dev/_query_draft.py` | 草稿/临时查询脚本（开发辅助） |

## 4. 文档（docs/）

| 分类 | 文件 |
|---|---|
| 文档入口 | `README.md` |
| 用户手册 | `USAGE.md` |
| 架构 | `ARCHITECTURE.md` |
| 开发计划 | `development-plan.md` |
| 测试流程 | `job-agent-test-flow.md` |
| 复盘 | `retrospective-*.md`（含 `retrospective-2026-08-18-coverage-boost.md`、`retrospective-2026-08-18-full-delivery.md`） |
| 参考 | `reference/`（火山引擎实时语音接入文档等） |
| 研究 | `research/`（医药招聘 API 调研） |
| 未完成 | `unfinished-work.md` |
| Cookie 指南 | `cookie-refresh-*.md` |
| 去重评估 | `dedup-eval-guide.md` |
| 本索引 | `project-structure.md` |

## 5. 数据与产物（data/、output/、offers/、resumes/）

| 路径 | 说明 |
|---|---|
| `data/agent.db` | SQLite 主数据库 |
| `data/log_archive/` | 历史测试证据/日志 |
| `data/backups/` | 数据备份 |
| `output/` | 生成文件（简历/HR/面试等） |
| `offers/` | Offer 原始文本 |
| `resumes/` | 简历原文 |

## 6. 工程配置

| 文件 | 说明 |
|---|---|
| `pyproject.toml` | 依赖/工具配置 |
| `config.yaml` | 运行配置 |
| `.env` | 密钥环境变量 |
| `.github/workflows/ci.yml` | CI |
| `.pre-commit-config.yaml` | 格式/检查钩子 |
| `AGENTS.md` | AI 助手长期记忆 |
| `README.md` | 项目总览 |
