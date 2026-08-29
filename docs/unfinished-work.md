# Job Seeker AI Agent — Backlog Baseline

> **本文档已归档（2026-06-25）**
>
> 本 backlog 经代码级逐条核实，标注"未完成/待核实"的条目**已全部完成**（误报率 26.9%，P1-P3 待核实项 100% 误报）。本文档仅作历史快照保留，**不再反映项目现状**。
>
> 当前权威状态以以下文档为准：
> - `docs/retrospective-2026-06-25.md` — 代码级逐条核实复盘（**已归档 2026-07-31，历史基线**）
> - `docs/development-plan.md` — 已更新的开发计划（**已归档 2026-07-24，历史基线**）
> - `AGENTS.md` — AI 助手长期记忆锚点（跨会话行为铁律，进入仓库先读）
- `README.md` / `docs/ARCHITECTURE.md` / `docs/USAGE.md` — 当前权威（2026-08-16 全项目整理时再次订正对齐代码）
- `docs/retrospective-2026-08-16-mock-interview.md` — 模拟面试专项复盘（2026-08-16）
- `docs/retrospective-2026-08-16-search-audit.md` — 职位搜索专项复盘（2026-08-16）
>
> 如需了解真正未完成的工作，请直接阅读上述复盘报告第 2 节"真未完成清单"。

**生成日期**: 2026-06-20

**说明**: 本文件为 backlog 基线，P0 证据已逐一核实（行号准确），P1-P3 证据待全仓抽查并标注相应说明。

---

## 总览

- **核查条目**: 67 条
- **已完成**: 31 条 (46.3%)
- **部分完成**: 18 条 (26.9%)
- **未完成**: 18 条 (26.9%)
- **生产就绪度**: 约 75%
- **P0 优先级**: P0-1、P0-3 已完成；P0-2 阻塞(需真实 API)

**进度说明**:
- P0-1/P0-3 于 2026-06-21 实现完成，测试通过
- P0-2 阻塞：需用户抓包提供 job51/zhilian/maimai 真实 API，按先验证再构建原则不盲写
- 回归测试：117/122 通过，5 个失败与本次 P0 实现无关(非回归)

---

## P0 — 必须修复的阻塞性问题

### P0-1: rate_limit 配置未生效 + Boss code-37 降级逻辑缺失

**实际状态**: ✅ 已完成 (2026-06-21)

**实现摘要**:
- `rate_limit_seconds`(per-platform,默认 30s)已接入 boss_zhipin.py / liepin.py 的 HTTP 调用间隔，替换原固定 1.5s/2.0s,取不到 config 时 fallback 默认值
- code-37 触发时 `_ANTI_BOT_BACKOFF_SECONDS` 退避(默认 300s)并 break,保留 toast 通知
- search.py 调度层已传 rate_limit_seconds 给适配器,无需改
- 新增 4 个测试(test_boss.py),全过

---

### P0-2: 3 平台适配器未实现

**实际状态**: ❌ 未完成 (阻塞:需用户抓包提供真实 API)

**阻塞原因**:
- 按"先验证再构建"原则，不能盲写 job51/zhilian/maimai 适配器
- 需用户提供真实抓包数据确认 API 端点/参数/响应格式
- 当前 liepin 适配器已验证可用，可作参考模式

**修复**: 等待用户抓包后实现，优先级 job51 > zhilian > maimai。

---

### P0-3: Prescreen 规则硬编码

**状态**: ❌ 已移除 (2026-07-03) — prescreen 阶段已从 pipeline 中整体移除，改为人工标记筛选 + LLM 精排。`prescreen.py` 文件及配置、测试已全部删除。

---

### P2-1: 死依赖清理 + login 命令重命名(原 P0-4,已降级)

**状态**: ⚠️ 部分完成(轻量技术债,非阻塞)

**核实结论(2026-06-20 实测)**:
- login 命令**已不依赖 Playwright**。`boss_login`(`platforms/boss_zhipin.py:302-315`)和 `liepin_login`(`platforms/liepin.py:320-332`)均只打印手动 cookie 导出指南并返回 False,不启动浏览器；搜索全走 HTTP API。
- 全仓 Playwright 残留仅两处无害引用:`config.py:90` 默认 `login_method="playwright_cookie"`(过时字符串)、`pyproject.toml:20` 声明 `playwright>=1.50`(死依赖)。

**修复动作**:
- (a) login 命令重命名为 `cookie-guide` 或移除;
- (b) 从 pyproject.toml 删 playwright 死依赖;
- (c) 清理 config.py:90 过时 login_method 值。

---

## P1 — 核心功能不完整

**说明**: 以下条目证据未逐一抽查，行号待全仓核实。

### P1-1: DB 迁移无版本管理

- 状态: ❌ 未完成
- 待核实: `db.py` 迁移段；无 schema_version 表；未使用 Alembic

### P1-2: .coveragerc 缺失

- 状态: ❌ 未完成
- 已确认: 全仓无 .coveragerc，覆盖率无佐证
- 阈值: 75%/80% 要求无法验证

### P1-3: interview-prep CLI 不完整

- 状态: ✅ 已完成 (2026-07-19 核实)
- 实现: `cli.py:534` interview-prep 命令 + `pipeline/interview_prep.py:29` predict_questions
- mock-interview 命令已补齐，见 P1-4

### P1-4: 模拟面试功能缺失

- 状态: ✅ 已完成 (2026-07-19 核实)
- 实现: `cli.py:582` mock-interview 命令 + `pipeline/interview_prep.py:79` mock_interview (终端交互式)
- 测试: `tests/test_cli.py:977` test_cli_mock_interview
- Stage 3 (2026-07-19): Dashboard 在线模拟面试 + SSE 流式。`serve.py` 加 `/api/mock-interview/start|reply|end`；`interview_prep.py` 加 `start_mock_session`/`stream_mock_turn`/`end_mock_session`（对话循环与终端 I/O 分离，chat_stream 流式）；前端 mock tab + 聊天气泡 + fetch ReadableStream 解析 SSE
- Stage 4 (2026-07-19): 语音 STT+TTS（浏览器原生 SpeechRecognition + SpeechSynthesis，零新依赖）。mock tab 🎤 麦克风按钮 + 朗读面试官开关

---

## P2 — 可维护性/质量问题

**说明**: 以下条目证据未逐一抽查，行号待全仓核实。

### P2-1: 无代码规范工具

- 状态: ❌ 未完成
- 待核实: pre-commit hooks；black/ruff 配置
- 影响: 代码风格不一致

### P2-2: 无 CI/CD

- 状态: ❌ 未完成
- 待核实: `.github/workflows/` 目录
- 影响: 无自动化测试/部署

### P2-3: 日志混用 print/logging

- 状态: ⚠️ 部分完成
- 待核实: 全仓抽查（`grep -rE "^\s*print\(" | grep -v test | grep -v "#" | wc -l`）

### P2-4: config 未校验

- 状态: ❌ 未完成
- 待核实: 无 Pydantic 验证
- 影响: 类型错误/缺失配置可能导致运行时错误

### P2-5: 无安全扫描

- 状态: ❌ 未完成
- 待核实: bandit 配置/扫描结果

### P2-6: 无类型检查

- 状态: ❌ 未完成
- 待核实: mypy 配置/扫描结果

---

## P3 — 锦上添花

**说明**: 以下条目证据未逐一抽查，行号待全仓核实。

### P3-1: mock-interview 命令缺失

- 状态: ✅ 已完成 (2026-07-19 核实)
- 实现: `cli.py:582` mock-interview 命令已暴露

### P3-2: offer-eval / salary-advice CLI 暴露情况待核实

- 状态: ⚠️ 部分完成
- 待核实: CLI 层面暴露状态

### P3-3: Dashboard 简陋

- 状态: ⚠️ 部分完成
- 待核实: API 文档、错误处理、认证机制

### P3-4: Timeline 未在 Dashboard 展示

- 状态: ❌ 未完成
- 待核实: 前端 Timeline 组件实现

### P3-5: Windows Toast 未实测触发

- 状态: ❌ 未完成
- 待核实: 缺少手动测试命令
- 影响: 通知功能无验收依据

---

## 计划自身遗漏

### 遗漏 1: Prescreen 配置化的具体配置项结构未定义

- 影响范围: P0-3 修复（已于 2026-07-03 随 prescreen 阶段整体移除）

### 遗漏 2: enrichment.py 未集成进 Pipeline

- 影响范围: 核心数据流
- 当前状态: 只能手动 rematch 后 enrich
- 建议: 集成到 `pipeline/search.py` 或新建 `pipeline/enrich.py` 调用链

### 遗漏 3: 跨平台去重"fuzzy 75%"算法未验证

- 影响范围: 数据质量
- 缺失内容: fuzzy 算法实现与测试
- 待核实: 实际去重效果、误杀率/漏杀率

### 遗漏 4: 测试数量矛盾

- 数据: 计划写 115 pytest 用例，实测 9 个测试文件
- 疑问: 115 用例 / 9 文件 不必然矛盾，需 `pytest --collect-only` 核实用例数
- 待核实: 实际测试用例总数、覆盖范围

---

## 修复路线（约 3 周）

### 阶段 1 (1 周, P0 优先级)

**目标**: 修复阻塞性问题，确保核心功能可用

- **P0-1**: rate_limit 配置接入 + Boss code-37 自动降级延时
- **P0-2**: 实现 job51、zhilian、maimai 三个平台适配器
- **P0-3**: Prescreen 规则配置化（新增 config 段 + 读取逻辑）
- **P0-4**: 废弃旧 login 命令，统一使用 import-cookies（README 更新 + liepin_login 核实）

**验收标准**:
- rate_limit_seconds 配置生效（HTTP 请求间隔动态）
- Boss code-37 触发时自动加长延时（≥5 分钟）并降级页数（≤5 页）
- 3 平台适配器返回真实 HTTP 数据（非 NotImplementedError）
- （Prescreen 已于 2026-07-03 整体移除）
- 旧 login 命令报错，import-cookies 命令可用

---

### 阶段 2 (1 周, 质量提升)

**目标**: 补齐测试与基础设施，提升代码质量

- **P1-1**: DB 迁移版本化管理（Alembic 或 schema_version 表）
- **P1-2**: 添加 .coveragerc，确保 75%/80% 覆盖率有佐证
- **P2-1**: 添加 pre-commit hooks（black + ruff）
- **P2-2**: 添加 CI/CD（GitHub Actions，至少包含测试+lint）
- **P2-3**: 全仓日志统一（print → logging）
- **P2-4**: 添加 Pydantic config 校验
- **P2-5**: 添加 bandit 安全扫描（GitHub Actions）
- **P2-6**: 添加 mypy 类型检查（GitHub Actions）

**验收标准**:
- DB 迁移有版本号表 + 版本记录
- .coveragerc 存在，覆盖率 ≥80%（新增测试补齐）
- pre-commit hooks 覆盖测试 + lint + 安全扫描
- CI/CD 在 PR 时自动运行测试 + lint + 类型检查
- 全仓 print 语句 ≤5%（仅在测试/调试中保留）
- config 缺失字段或类型错误在启动时报错（Pydantic 校验）
- bandit 扫描无 CRITICAL/HIGH 风险
- mypy 无未定义变量/类型错误

---

### 阶段 3 (3 天, 功能文档)

**目标**: 补齐遗漏功能，完善文档

- **P1-3**: ✅ 已完成 -- interview-prep CLI + mock-interview 命令均已实现
- **P1-4**: ✅ 已完成 -- mock-interview CLI 功能已补齐
- **P3-3**: 完善 Dashboard（API 文档、错误处理、认证机制）
- **P3-4**: 在 Dashboard 添加 Timeline 组件
- **P3-5**: 添加手动测试命令（如 `pytest -k "toast" --run-integration`）

**验收标准**:
- interview-prep CLI 生成面试题（文本，✅ 已实现；语音输入✅ Dashboard 模拟面试 tab 用 Web Speech API STT/TTS）
- mock-interview CLI 可生成面试题 + 评估回答（✅ 已实现）
- Dashboard 有 API 文档页面（Swagger/OpenAPI）
- Dashboard 错误处理完善（404/500 页面 + 日志记录）
- Dashboard 有登录认证（至少基础 token 验证）
- Timeline 在 Dashboard 主页展示（按时间轴排序）
- Windows Toast 测试命令可触发通知（手动验证通过）

---

### 阶段 4 (1 天, 收尾验收)

**目标**: 全量测试，用户验收

- **全量测试**: 运行 `pytest --co -q` + `pytest --cov=agent_core --cov-report=html`
- **回归测试**: 所有修复功能走一遍完整流程
- **用户验收**: CLI + Dashboard 功能端到端测试
- **文档更新**: README 更新修复内容 + 使用示例

**验收标准**:
- 测试通过率 100%（无 FAILED）
- 覆盖率 ≥80%（新增测试补齐缺口）
- 用户手册包含所有新功能使用说明
- 代码提交消息符合约定式提交规范（feat/fix/refactor/docs）

---

## 附录：证据核查记录

### P0 证据核实完成

| P0 条目 | 核实方法 | 核实结果 | 行号确认 |
|---------|---------|---------|---------|
| P0-1 (rate_limit + code-37) | Read `boss_zhipin.py:152-159,119-170` | ✅ 已核实 | 152-159, 119-170 |
| P0-2 (3 适配器) | Read `job51.py:12-14`, `zhilian.py:12-14`, `maimai.py:12-14` | ✅ 已核实 | 12-14 每个文件 |
| P0-3 (Prescreen 硬编码) | ❌ 已移除 (2026-07-03) | ✅ 已核实 | 已删除 |
| P0-4 (login 冗余) | Read `cli.py:82-92,364-381` + `boss_zhipin.py` 检查 Playwright | ✅ 已核实 | 82-92, 364-381 |
| **合计** | | **4/4 已核实** | - |

### P1-P3 证据待核实

| 类别 | 条目数 | 核实状态 |
|------|-------|---------|
| P1 | 4 | ⏳ 待全仓抽查 |
| P2 | 6 | ⏳ 待全仓抽查 |
| P3 | 5 | ⏳ 待全仓抽查 |
| **合计** | **15** | - |

**全仓抽查命令建议**:
```bash
# P1 检查
grep -rE "class.*Migration|schema_version" agent_core/db.py
ls -la agent-core/.coveragerc 2>/dev/null || echo "未找到 .coveragerc"

# P2 检查
find .github/workflows -name "*.yml" 2>/dev/null || echo "未找到 CI 配置"
grep -rE "^\s*print\(" agent_core --exclude-dir=test --exclude="*.pyc" | wc -l
grep -rE "from pydantic" agent_core/*.py | wc -l
grep -rE "bandit" agent_core | wc -l
grep -rE "from typing import |from __future__ import annotations" agent_core/*.py | wc -l

# P3 检查
grep -rE "mock-interview" agent_core/cli.py | wc -l
grep -rE "offer-eval|salary-advice" agent_core/cli.py | wc -l
ls -la agent-core/前端/Dashboard 2>/dev/null || echo "Dashboard 路径待确认"
```

---

**文件生成时间**: 2026-06-20
**下次更新**: P1-P3 证据全仓抽查完成后
