# 求职 AI Agent -- 代码级逐条核实复盘

> ⚠️ **本文档已归档（2026-07-31）**
>
> 本文档为 **2026-06-25 历史基线快照**，多处内容与代码现状漂移（如 Flask → stdlib http.server、`/api/timeline` 已移除、覆盖率为 429 测试）。当前权威状态以仓库内 `README.md`、`docs/ARCHITECTURE.md` 及实际代码为准。本文件仅作历史复盘参考。

**核实日期**: 2026-06-25
**核实方法**: 全量代码审查（3 个并行子 agent 交叉验证）+ 针对性 grep 补查
**对照文档**: unfinished-work.md (06-20)、retrospective-2026-06-23.md (06-23, 06-25 更新)、development-plan.md (06-25)
**核实范围**: 46 个 Python 源文件、24 个测试文件、5 个配置文件、1 个 CI workflow

---

## 1. 核实方法说明

### 1.1 读了哪些文档

- `docs/unfinished-work.md` (11KB, 2026-06-20) -- 67 条 backlog，P0 已核实、P1-P3 待核实
- `docs/retrospective-2026-06-23.md` (17KB, 最终更新 2026-06-25) -- 复盘报告，含 06-25 追加的"最终完成状态"章节
- `docs/development-plan.md` (26KB, 最终更新 2026-06-25) -- 项目基线，第 6 节标注"全部完成"

### 1.2 核对了哪些代码

| 类别 | 检查的文件 | 核实方法 |
|------|-----------|----------|
| CLI 命令 | `agent_core/cli.py` (全量) | 逐个 `@app.command()` 装饰器计数，验证函数体是否 import 实际模块 |
| 平台适配器 | 10 个 `platforms/*.py` | 读每个 `search()`/`get_jobs()` 方法，区分真实实现 vs `NotImplementedError` |
| Pipeline 模块 | 11 个 `pipeline/*.py` | 检查 orchestrator.py 的 import 链，确认 enrichment 是否集成 |
| Dashboard | `server/serve.py` (全量) | 搜索 swagger/openapi/auth/pagination/timeline 关键字 |
| 调度器 | `scheduler/scheduler.py` (全量) | 验证 PID 锁、catch-up、quiet_hours |
| LLM 层 | `llm/providers.py` (全量) | 验证 AsyncOpenAI、指数退避、function-calling |
| 数据库 | `storage/db.py` (全量) | 验证 WAL、schema_version 表、迁移系统 |
| 配置 | `config.py` (全量) | 验证 Pydantic BaseModel、PrescreenRulesConfig |
| 测试 | `tests/` 目录 + `pyproject.toml` | 检查测试文件列表、coverage 配置 |
| CI/工具链 | `.github/workflows/ci.yml`、`.pre-commit-config.yaml`、`pyproject.toml` | 验证 ruff/mypy/bandit 配置 |
| Chat 模式 | `agent/tools.py` + `agent/repl.py` | 验证 function-calling 工具定义和 REPL 循环 |

### 1.3 判定标准

- **真未完成**: 代码里确实没有实现（NotImplementedError / 文件不存在 / 函数不存在），文档说未完成属实
- **已完成（误报）**: 文档标注"未完成/待核实"但代码中已有完整实现，含测试
- **部分完成**: 框架/代码存在但缺测试覆盖、缺集成、缺验证，或功能退化但未清理
- **阻塞**: 需要用户外部操作（抓包/登录/提供 API key/恢复 Git remote）才能推进，AI 无法自行完成

---

## 2. 真未完成清单

### P0 级别

#### 2.1 job51 适配器 -- 存根未实现
- **文档出处**: unfinished-work.md P0-2, development-plan.md 6.1 (❌ job51)
- **代码证据**: `agent_core/platforms/job51.py:13` -- `raise NotImplementedError("job51 adapter not yet implemented")`，文件仅 26 行
- **判定**: 用户决定当前不实现，属主动放弃而非遗漏
- **建议优先级**: P3（不实现）

#### 2.2 maimai 适配器 -- 存根未实现
- **文档出处**: unfinished-work.md P0-2, development-plan.md 6.1 (❌ maimai)
- **代码证据**: `agent_core/platforms/maimai.py:13` -- `raise NotImplementedError("maimai adapter not yet implemented")`，文件仅 26 行
- **判定**: 同上，用户决定不碰
- **建议优先级**: P3（不实现）

### P1 级别

#### 2.3 Apply 阶段 -- Pipeline 中无自动投递
- **文档出处**: development-plan.md 6.1 表格 (Apply ❌ "依赖用户手动投递，无自动投递接口")
- **代码证据**: `agent_core/pipeline/orchestrator.py` -- 全文搜索 `apply`/`Apply`/`_apply` 无匹配，orchestrator 只编排 search/filter/match/tailor/cover_letter 阶段（prescreen 已于 2026-07-03 移除）
- **判定**: Phase 1 设计文档列出了 7 阶段含 Apply，但代码中 Apply 是纯手动步骤。这不一定是 bug（自动投递有法律/反爬风险），但文档称"7 阶段 Pipeline"有误导
- **建议优先级**: P2（文档修正即可，不需要代码改动）

#### 2.4 行业适配器 backlog -- 6 家大厂未实现
- **文档出处**: retrospective-2026-06-23.md 6.1 (6 个 backlog 大厂适配器: 字节/华为/小米/百度未实现)
- **代码证据**: `agent_core/platforms/` 目录无 `byte_dance.py`、`huawei.py`、`xiaomi.py`、`baidu.py` 等文件
- **判定**: 计划写了但未实现，需分别调研各厂 API
- **建议优先级**: P2（需先调研 API 可用性，部分可能无公开 API）

#### 2.5 Coverage 未在 CI 中强制执行
- **文档出处**: development-plan.md 6.1 (覆盖率 85.5%, fail_under=79)
- **代码证据**: `.github/workflows/ci.yml:39` -- CI 只运行 `python -m pytest -q`，**没有传 `--cov` 参数**，即使本地 `pyproject.toml:72` 设了 `fail_under = 79`，CI 中覆盖率门禁实际不生效
- **判定**: 覆盖率门禁只在本地有效，CI 中形同虚设
- **建议优先级**: P1（加 `--cov=agent_core --cov-report=term --cov-fail-under=79` 到 CI）

#### 2.6 所有改动未 commit
- **文档出处**: retrospective-2026-06-23.md 第 6.2 节, development-plan.md 第 11 节
- **代码证据**: `git status` 显示大量未跟踪文件和已修改文件（Batch W 全部内容）
- **判定**: 用户禁止 push 且删除了 GitHub 远程仓库。代码仅在本地工作区，无版本历史保护
- **建议优先级**: P0（数据安全风险：一次误操作 `git clean -fd` 会丢失所有改动）

### P2 级别

#### 2.7 BOSS __zp_stoken__ 定期过期 -- SOP 存在但自动化程度低
- **文档出处**: development-plan.md 6.4 (技术债务: BOSS `__zp_stoken__` 定期过期)
- **代码证据**: `agent_core/cookie_health.py:530` 行完整模块内有 Boss cookie 检查/重抓 SOP，但重抓仍需用户手动操作（boss_zhipin.py 的 login 方法只打印指南）
- **判定**: 检测机制完善（cookie_health.py），但重抓仍需人工。非代码问题，属平台反爬限制
- **建议优先级**: P2（无法代码解决，完善 SOP 文档即可）

#### 2.8 login 命令未重命名/移除
- **文档出处**: unfinished-work.md P2-1: "login 命令重命名为 cookie-guide 或移除"
- **代码证据**: `agent_core/cli.py:54` -- `@app.command()` 装饰的 `login` 命令仍存在。虽然其内部已不依赖 Playwright（`agent_core/config.py:54` -- `login_method: str = Field(default="import_cookies")`），但旧命令名保留，可能误导用户
- **判定**: 功能已退化（只打印指南），但命令名未更新
- **建议优先级**: P3（轻量技术债，不影响功能）

#### 2.9 enrichment.py 位于 platforms/ 而非 pipeline/
- **文档出处**: unfinished-work.md 遗漏 2: "enrichment.py 未集成进 Pipeline"
- **代码证据**: 
  - `agent_core/pipeline/orchestrator.py:36` -- 已从 `agent_core.platforms.enrichment` import `enrich_job_jd`，集成已完成
  - 但文件物理位置在 `platforms/enrichment.py`(70行) 而非 `pipeline/enrichment.py`(不存在)
- **判定**: 功能已集成、代码存在，但模块归属有歧义（enrichment 属数据增强而非平台适配，放 pipeline/ 更合理）
- **建议优先级**: P3（不影响功能，重构时可迁移）

---

## 3. 部分完成清单

#### 3.1 智联 Playwright 浏览器 -- 需首次手动登录
- **文档出处**: development-plan.md 6.3 (智联: 零维护（浏览器）)
- **代码证据**: 
  - `agent_core/platforms/zhilian_browser.py` -- 328 行完整实现，persistent profile + 反检测 JS
  - `agent_core/platforms/zhilian.py:143` -- search() 双模式（浏览器优先，HTTP fallback）
- **判定**: 代码完整，但初次使用需用户手动登录一次（`zhilian_browser.py:215-217` 打印登录指引）。登录后长期可用。文档称"零维护"稍乐观，应为"登录一次后零维护"
- **建议优先级**: P2（第一次使用需要用户操作 30 秒）

#### 3.2 Windows Toast 通知 -- 实现存在但未集成测试验证
- **文档出处**: unfinished-work.md P3-5: "Windows Toast 未实测触发"
- **代码证据**: 
  - `agent_core/notify/windows_toast.py` -- 48 行完整实现（winotify + PowerShell fallback）
  - `tests/test_notify_integration.py` -- 73 行，但其中 6 个 skipped 测试需要 `--run-integration` 标志
- **判定**: 代码完整，但只有人工确认过通知确实弹出，无自动化验收
- **建议优先级**: P3（在 Windows 环境跑一次 `pytest tests/test_notify_integration.py --run-integration` 即可关闭）

#### 3.3 跨平台去重 fuzzy 75% -- 算法存在但效果未量化评估
- **文档出处**: unfinished-work.md 遗漏 3: "跨平台去重 fuzzy 75% 算法未验证"
- **代码证据**: 
  - `agent_core/pipeline/search.py:40` -- `_normalize_company()` 公司名标准化
  - `agent_core/pipeline/search.py:159-175` -- `_dedup()` 去重逻辑
- **判定**: 代码存在且被调用，但缺少专门的测试来验证去重准确率（误杀率/漏杀率），也缺少跨平台同名岗位的标注数据集
- **建议优先级**: P3（需人工标注数据才能验证，非紧急）

#### 3.4 print 语句残留 -- 均在交互式/用户提示代码中，可接受
- **文档出处**: unfinished-work.md P2-3: "日志混用 print/logging"
- **代码证据**: 
  - `agent_core/agent/repl.py:64-68,74,80,89,122,147,153,164,174` -- chat REPL 交互输出（14 处，合理）
  - `agent_core/platforms/zhilian_browser.py:215-217,227,231` -- 浏览器登录指引（5 处，合理）
  - `agent_core/platforms/zhilian.py:495-499` -- 登录指引（5 处，合理）
  - `agent_core/platforms/liepin.py:368-373` -- cookie 导出指引（6 处，合理）
  - `agent_core/platforms/boss_zhipin.py:377` -- 登录指引（1 处，合理）
  - **非交互代码中无 print 残留**
- **判定**: 所有 print 均在面向前端/用户的交互输出或操作指引中，属于合理使用。核心库代码已全部迁移到 logging
- **建议优先级**: 无需处理（状态可从"部分完成"升级为"已完成"）

---

## 4. 误报清单（文档说未完成，代码证明已完成）

以下条目在 unfinished-work.md (2026-06-20) 中被标注为"❌ 未完成"或"⚠️ 部分完成"，但代码核实证明**已全部落地**。这也是复盘报告（06-25 更新）和开发计划（06-25 更新）已修正的内容。

### 4.1 P0 级别误报

| # | 条目 | 文档状态 | 代码证据 | 说明 |
|---|------|---------|---------|------|
| 1 | P0-3: Prescreen 规则硬编码 | ❌ 已于 2026-07-03 移除 | prescreen 阶段整体删除，文件/配置/测试均已清除 | |
| 2 | zhilian 适配器"存根" | unfinished-work.md P0-2 称 3 平台未实现 | `agent_core/platforms/zhilian.py` -- 553 行完整实现，search() at :143 | unfinished-work.md 严重过时，zhilian 早已不是存根 |

### 4.2 P1 级别误报

| # | 条目 | 文档状态 | 代码证据 |
|---|------|---------|---------|
| 3 | P1-1: DB 迁移无版本管理 | unfinished-work.md: ❌ 未完成 | `agent_core/storage/db.py:11` SCHEMA_VERSION=2, `:23-31` schema_version 表, `:138-141` _MIGRATIONS 列表, `:144-162` migrate() |
| 4 | P1-2: .coveragerc 缺失 | unfinished-work.md: ❌ 未完成 | `.coveragerc` 文件存在（含 branch coverage + exclude_lines）；`pyproject.toml:64-72` 另有 `[tool.coverage.*]` 配置 |
| 5 | P1-3: interview-prep CLI 不完整 | unfinished-work.md: ⚠️ 部分完成 | `agent_core/cli.py:404` interview_prep 命令, `agent_core/pipeline/interview_prep.py` 134 行（技术题/行为题/项目深挖） |
| 6 | P1-4: 模拟面试功能缺失 | unfinished-work.md: ❌ 未完成 | `agent_core/cli.py:433` mock_interview 命令, 调用 `pipeline/interview_prep.py` 中的 `mock_interview()` 函数 |

### 4.3 P2 级别误报

| # | 条目 | 文档状态 | 代码证据 |
|---|------|---------|---------|
| 7 | P2-1: 无代码规范工具 | unfinished-work.md: ❌ 未完成 | `.pre-commit-config.yaml` (black + ruff), `pyproject.toml:49-55` ruff 配置 |
| 8 | P2-2: 无 CI/CD | unfinished-work.md: ❌ 未完成 | `.github/workflows/ci.yml` -- ruff/mypy/bandit/pytest 四步 |
| 9 | P2-4: config 未校验 | unfinished-work.md: ❌ 未完成 | `agent_core/config.py:34-127` 8 个 Pydantic BaseModel 类, 含 field_validator |
| 10 | P2-5: 无安全扫描 | unfinished-work.md: ❌ 未完成 | `pyproject.toml:57-62` bandit 配置 (skips B101/B110), `ci.yml:36` bandit 步骤 |
| 11 | P2-6: 无类型检查 | unfinished-work.md: ❌ 未完成 | `pyproject.toml:74-81` mypy 配置, `ci.yml:33` mypy 步骤, 实测 63 文件 0 错误 |

### 4.4 P3 级别误报

| # | 条目 | 文档状态 | 代码证据 |
|---|------|---------|---------|
| 12 | P3-1: mock-interview 命令缺失 | unfinished-work.md: ❌ 未完成 | `agent_core/cli.py:433` mock_interview 命令 |
| 13 | P3-2: offer-eval/salary-advice CLI 暴露待核实 | unfinished-work.md: ⚠️ 部分完成 | `agent_core/cli.py:449` offer_eval, `:491` salary_advice |
| 14 | P3-3: Dashboard 简陋 (API 文档/认证) | unfinished-work.md: ⚠️ 部分完成 | `agent_core/server/serve.py:418-419` /docs Swagger UI, `:344-359` Bearer token 认证, `:441-452` 分页 |
| 15 | P3-4: Timeline 未在 Dashboard 展示 | unfinished-work.md: ❌ 未完成 | `agent_core/server/serve.py:413-415` GET /api/timeline, `:471-537` _api_timeline() 含分页/筛选 |

### 4.5 遗漏项误报

| # | 条目 | 文档状态 | 代码证据 |
|---|------|---------|---------|
| 16 | 遗漏 1: Prescreen 配置化结构未定义 | unfinished-work.md: 缺失 | `agent_core/config.py:89-95` PrescreenRulesConfig (feature_weight/keyword_weight/salary_high_multiplier/salary_high_bonus) |
| 17 | 遗漏 2: enrichment.py 未集成进 Pipeline | unfinished-work.md: 未集成 | `agent_core/pipeline/orchestrator.py:36` -- `from agent_core.platforms.enrichment import enrich_job_jd` |
| 18 | 遗漏 4: 测试数量矛盾 (115 vs 实测) | unfinished-work.md: 待核实 | 实测 429 passed / 6 skipped / 0 fail，远超计划的 115 |

### 4.6 复盘报告中的已修复项（06-25 更新已标注）

| # | 条目 | 06-23 状态 | 06-25 证据 |
|---|------|-----------|-----------|
| 19 | 覆盖率 76.2% 未达 79% 门禁 | retrospective: HIGH | 06-25 更新: 85.5%（超阈值 6.5%） |
| 20 | 2 个 pytest 回归失败 | retrospective: HIGH | 06-25 更新: 已修复（改用 byd 替代 boss） |
| 21 | Playwright 依赖残留 | retrospective: ⚠️ 部分 | `pyproject.toml` 中无 playwright；`config.py:54` login_method 默认 "import_cookies" |
| 22 | login_method 配置漂移 | unfinished-work.md P2-1 | `config.py:54` -- `login_method: str = Field(default="import_cookies")`，不再是 "playwright_cookie" |

### 4.7 误报统计

- **unfinished-work.md 中 18 条标注"未完成/待核实"实际已全部完成** -- 误报率 18/67 = 26.9%（低于任务说明估计的 36.8%，说明之前的复盘更新已修正部分）
- 其中 P1-P3 15 条待核实项中 15 条全部为误报（100%）
- 复盘报告 06-25 更新和开发计划 06-25 更新已正确反映实际状态

---

## 5. 阻塞项（需用户操作）

| # | 阻塞项 | 所需操作 | 优先级 | 阻塞原因 |
|---|--------|---------|--------|---------|
| 1 | **Git 改动未保护** | `git add -A && git commit -m "feat: final Batch W -- 8源全通 + chat + 85.5% cov"` | **P0** | 数据安全：一次误操作可能丢失所有改动 |
| 2 | **智联首次登录** | 运行 `job-agent login --platform zhilian` 手动登录一次 | P1 | Akamai 反爬必须活体浏览器登录，无法代码绕过 |
| 3 | **BOSS Cookie 刷新** | 按 `cookie_health.py` SOP 重抓 `__zp_stoken__` | P1 | Cookie 短效（几小时~天），过期后 BOSS 搜索返回空 |
| 4 | **猎聘 Cookie 确认** | 验证 `data/cookies/liepin.json` 是否有效 | P2 | Cookie 稳定但需确认未过期 |
| 5 | **GitHub 远程仓库** | 如需协作再 push（保持当前不 push 约束） | P2 | 2026-08-15 订正：origin 已重新存在为 https://github.com/yjxhn/job-agent-resume.git，不是“当前无 remote” |
| 6 | **job51/maimai 存根** | 决定：永久放弃 or 提供抓包数据后实现 | P3 | 需用户提供真实 API 端点/参数/响应 |
| 7 | **字节/华为/小米/百度适配器** | 调研各厂招聘 API（部分可能无公开 API） | P3 | 需先调研 API 可用性 |

---

## 6. 优先级排序的总推进建议

### 6.1 立即可做（AI 子 agent，无需用户）

| 优先级 | 任务 | 预估工作量 | 可派给 |
|--------|------|-----------|--------|
| P0 | **CI 加 coverage 门禁** -- ci.yml 加 `--cov=agent_core --cov-fail-under=79` | 5 分钟 | 单子 agent |
| P2 | **unfinished-work.md 归档** -- 标注为"已过期，以 retrospective-2026-06-25.md 为准" | 2 分钟 | 单子 agent |
| P2 | **enrichment.py 迁移** -- 从 platforms/ 移到 pipeline/（功能不变，归属修正） | 15 分钟 | 单子 agent |
| P3 | **login 命令废弃** -- 添加 deprecation warning，指向 import-cookies | 10 分钟 | 单子 agent |
| P3 | **print 残留审计** -- 确认无可疑 print，关闭 P2-3 | 已完成（本报告） | 无须操作 |

### 6.2 需要用户介入一次（5 分钟内）

| 优先级 | 任务 | 用户操作 |
|--------|------|---------|
| **P0** | **Git commit 保护改动** | `git add -A && git commit -m "..."` |
| P1 | **智联首次登录** | `job-agent login --platform zhilian`，扫码/账号登录 |
| P1 | **BOSS Cookie 刷新** | 按 SOP 重抓 `__zp_stoken__` |

### 6.3 需要调研后决策

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P2 | **6 家大厂适配器调研** | 先用 Playwright 快速探测各厂招聘页 API（不写代码，只确认是否有公开 API），再决定哪些值得实现 |
| P3 | **去重算法效果评估** | 需要先跑一次全平台搜索，人工标注跨平台重复岗位对，然后计算 precision/recall |

### 6.4 不需要做的

| 条目 | 原因 |
|------|------|
| job51/maimai 存根实现 | 用户决定不碰 |
| Apply 自动投递 | 法律/反爬风险，保持手动 |
| Dashboard 重大改造 | 当前 Flask + Swagger + 分页 + Timeline + 认证 已完整 |
| mock-interview / offer-eval / salary-advice | 代码完整、CLI 暴露、测试覆盖 |

---

## 7. 最终统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 真未完成 | 9 | job51/maimai/6大厂/Apply 阶段/CI coverage 门禁/未 commit |
| 部分完成 | 4 | 智联首次登录/Toast 实测/去重评估/print 残留（可接受） |
| 已完成（误报） | 22 | unfinished-work.md 中 15 条 + 复盘报告中 7 条已修复 |
| 阻塞 | 7 | 需用户操作 |
| **总计核实** | **42** | 覆盖三份文档的全部声明 |

### 最高优先级 3 条

1. **P0: Git commit 保护所有未提交改动** -- 误操作风险，涉及 46 个文件的所有 Batch W 工作
2. **P0: CI 加 coverage 门禁** -- `ci.yml` 缺少 `--cov` 参数，覆盖率 85.5% 的优势在 CI 中未体现
3. **P1: 智联首次登录** -- 8 源中最关键的反爬突破，需用户手动登录一次即可长期可用

---

**报告生成时间**: 2026-06-25
**核实方式**: 3 个并行 Explore agent 交叉验证 + 针对性 grep 补查
**下次复盘建议**: commit 改动后，或新增平台适配器后

---

## 8. 2026-06-25 追加更新（后续修复批次）

以下 7 项在本文档生成当天由子 agent 完成，状态已更新：

### 8.1 已修复/已完成

| # | 原状态 | 现状态 | 改动 | 验证 |
|---|--------|--------|------|------|
| 1 | 🔴 P0: CI 无 coverage 门禁 | ✅ 已修 | `.github/workflows/ci.yml` pytest 步骤加 `--cov=agent_core --cov-report=term --cov-report=xml --cov-fail-under=79`，步骤名改 "Run tests with coverage" | pytest-cov 依赖已在 pyproject；ruff/mypy/bandit 步骤复核无遗漏 |
| 2 | 🔴 P2: unfinished-work.md 过时误导 | ✅ 已归档 | 文件顶部插入归档横幅，指向本报告为权威，原文完整保留 | — |
| 3 | 🔴 P3: enrichment.py 归属错误（platforms/）| ✅ 已迁移 | `agent_core/platforms/enrichment.py` → `agent_core/pipeline/enrichment.py`，5 个引用文件全改（orchestrator/cli/tools + 2 测试），旧文件已删，0 残留 | 14 enrich 测试 passed，ruff/mypy 干净 |
| 4 | 🔴 P3: login 命令名误导 | ✅ 已加弃用提示 | `cli.py` login 函数开头加 deprecation warning + docstring 更新，原逻辑保留 | 4 个 login 测试 passed |
| 5 | 🔴 智联浏览器竞态 bug（多方向 pipeline 丢数据）| ✅ 已修 | 根因：双重竞态——asyncio.Lock 只护单例创建，launch_persistent_context 在 _ensure_browser 里不在锁内，两协程并发都见 self._context is None 导致 Chrome singleton 锁冲突。修法：模块级 lazy singleton + _ensure_browser 移进锁内 + atexit/signal 清理，浏览器同进程复用不重启。改 4 文件（zhilian_browser/zhilian + 2 测试），Akamai 反检测逻辑保留 | 多方向真实搜索 industrial_ai_agent 40 + equipment_amr 40，零崩溃零 HTTP fallback；37 单元测试 pass；ruff/mypy 干净 |
| 6 | 🟡 P1: 智联首次登录 | ✅ 已完成（用户操作）| 用户手动登录，profile 在 `data/zhilian_browser_profile` | 浏览器模式单次搜索返回真实职位 |
| 7 | 🟡 猎聘 Cookie 确认 | ✅ 可用 | Cookie 文件 5943B，lt_auth 395 天有效 | 探活返回 42 职位，定向搜索去重后 79 职位，无拦截 |

### 8.2 复盘报告自身误报修正

本报告第 2.4 节称"6 家大厂适配器未实现"，经核实**本身也是误报**：
- **腾讯/网易**：代码早就是真实实现（公开 API，无需 cookie），且 config 一直是 `enabled: true`。实测腾讯返回 30 职位、网易 21 职位，无反爬。**从未被禁用**
- 实际只有**字节/华为/小米/百度** 4 家未实现（无代码），用户决定不做
- "6 家"这个数字来源是 `retrospective-2026-06-23.md:156` 把"4 家未实现 + 2 家（腾讯/网易）config disabled"凑成 6，但"config disabled"这半也查无实据

### 8.3 仍由用户处理的项（不变）

- Git commit：不做（config 含私人信息）
- BOSS Cookie 刷新：用户按 `docs/cookie-refresh-boss.md` SOP 自行操作
- 字节/华为/小米/百度适配器：不做
- Apply 自动投递：保持手动

### 8.4 本批次新增产出

- `docs/dedup-eval-guide.md`（788 行）——跨平台去重效果评估操作手册，含标注流程 + CSV 模板 + 可运行的 `dedup_eval.py` 评估脚本骨架。重要发现：去重实为 exact match（非 fuzzy 75%），75% 阈值只用于公司名归一化到别名表，title 仅做 lowercase+删括号——recall 瓶颈在 title 不同写法不合并
