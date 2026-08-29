# 2026-08-17 复盘：Phase0-3 重构 + 模拟面试/材料生成/简历截断修复

> 本复盘覆盖：
> 1. Phase 0-3 改进计划执行
> 2. 模拟面试反问列表截断修复
> 3. 材料审核台“面试准备未生成”静默失败修复
> 4. 定制简历截断修复 + 再生成意见残留修复
> 5. `max_tokens` 配置调整
> 6. 输出与收尾流程的自我改进

---

## 1. 背景

用户要求：
- 按 Phase 0 → Phase 3 顺序执行 agent-core 改进计划，Phase 4 暂不做；
- 全程不 commit / 不 push，不破坏用户数据，先备份，跑门禁与测试。

随后又反馈了三个实际使用问题：
- 模拟面试反问建议第 ③ 条内容为空；
- 「生成求职材料」只有简历+HR消息，面试准备没生成且无提示；
- 材料审核台某份简历不完整，再生成意见生成后仍留在输入框。

---

## 2. 完成的工作

### Phase 0：数据安全与低风险修复
- `get_db()` 增加 `PRAGMA busy_timeout=5000`。
- `tracker.update_status()` 改为状态更新 + timeline 同一事务。
- `match.py` 二次意见 resume 缓存 key 修复为 `(resume_file, direction)`。
- 移除 `scheduler.py` 中与 `run_pipeline()` 重复的搜索完成 Toast。
- `PlatformAdapter.normalize()` 兜底填充 `company_normalized`。
- `scripts/import_cookies.py` 修复 `--domain` 缺参数。
- 新增 `tests/test_scripts.py`。

### Phase 1：serve.py 可维护性重构
- 拆出 `server/dashboard_html.py`（前端 HTML/CSS/JS/OpenAPI）。
- 拆出 `server/http_utils.py`（鉴权/JSON/HTML/请求体工具）。
- 拆出 `server/daemon.py`（守护进程启停）。
- 修复 Dashboard token 鉴权：`/` 注入 token meta，前端 fetch 自动附带 Bearer。
- 删除未使用的 `DASHBOARD_PID_FILE`。

### Phase 2：平台层加固
- 新增 `platforms/registry.py`：统一平台适配器工厂。
- 新增 `platforms/browser_utils.py`：统一 stale lock 清理与启动失败标记。
- `cookie_utils.py` 新增 `load_cookies_for_playwright()`，`playwright_jd.py` 复用。
- `search_all()` 增加全局并发信号量（默认 4）。
- 统一 job ID 生成 `make_job_id()`。

### Phase 3：测试与质量提升
- 新增测试：`test_registry.py`、`test_browser_utils.py`、`test_http_utils.py`、`test_serve_auth.py`、`test_scripts.py`、`test_playwright_jd_utils.py`、`test_boss_browser_utils.py`、`test_interview_prep_prompt.py`。
- 扩展 `test_serve_handlers.py`：投递更新/提醒。
- 扩展 `test_advanced.py`：tailor 截断重试。
- 覆盖率门槛 48 → 54。

### 后续 Bug 修复
1. **模拟面试反问列表截断**
   - 根因：`max_tokens=1024` 且 thinking 模式共享输出额度，反问列表被截断。
   - 修复：终端与 SSE 模拟面试改为使用 `config.llm.max_tokens`；Prompt 强制“完整列出全部推荐反问”。
2. **面试准备静默失败**
   - 根因：`predict_questions()` JSON 解析失败时只进 `interview_prep_failed`，前端不展示。
   - 修复：`predict_questions()` 增加 strict JSON → 普通文本重试；前端弹窗展示 `interview_prep_failed`；`/api/materials/regenerate` 也返回该字段。
3. **定制简历截断**
   - 根因：thinking 模式思考链消耗共享输出额度，正文被截断。
   - 修复：`tailor_resume()` 检测必要章节缺失后，用 `thinking_enabled=False` 重试一次。
4. **再生成意见残留**
   - 根因：`feedback` 存库并回填输入框。
   - 修复：`/api/materials/regenerate` 成功后清空 `feedback`，前端重新加载后为空。
5. **max_tokens 配置**
   - 用户要求设置为 `384000`：`config.yaml` 与 `config.py` 默认值均已更新。

---

## 3. 关键技术结论

- **`max_tokens` 是输出上限，不是输入上限。**
- **DeepSeek thinking 模式下，`max_tokens` = reasoning + content 共享输出额度。**
- 长文本生成（简历、面试反问列表）必须给足 `max_tokens`，并考虑“thinking 关闭重试”作为截断兜底。
- “静默失败”比“失败”更伤用户体验：所有 best-effort 子任务必须向前端透出失败原因。
- 大文件重构要“拆文件 + 保持 re-export + 跑既有测试”，而不是一次性重写。

---

## 4. 遇到的问题与根因

| 问题 | 根因 | 解决 |
|---|---|---|
| 反问列表 ③ 为空 | `max_tokens=1024` + thinking 共享额度 | 改用 config 输出上限 + Prompt 约束 |
| 面试准备没生成 | `predict_questions()` JSON 解析失败被静默 | strict JSON 重试 + 前端展示失败 |
| 简历不完整 | thinking 思考链吃掉输出额度 | 章节完整性检测 + 关闭 thinking 重试 |
| 意见框残留 | `feedback` 存库并回填 | 成功后清空 feedback |
| 重复汇报 | 目标收尾时未检查“已汇报过” | 收尾只给增量/简短确认 |

---

## 5. 经验教训

1. **不要假设 LLM 输出完整**：凡是生成 Markdown/JSON/列表，都要做完整性校验。
2. **thinking 模式下的截断是“隐形”的**：日志里没有错误，只是输出少了尾巴；必须用结构校验发现。
3. **best-effort 子任务必须可观测**：失败要进响应、进弹窗、进日志。
4. **大文件重构要渐进**：拆出独立模块后立即跑测试，不要等全部拆完再验证。
5. **测试要防止“假完整”**：旧测试用最小 fake 输出会误触发新的完整性重试逻辑，导致真实网络调用；测试数据要符合真实输出形态。
6. **收尾消息默认最短**：同一轮已完整汇报时，目标 closing 只写增量，不重复整份报告。
7. **异步 LLM 调用默认无超时**：OpenAI SDK 默认超时很长（约 10 分钟），用户侧表现为“卡死”；关键用户路径必须显式 `asyncio.wait_for`。

---

## 6. 自我改进清单

- [x] 长文本生成增加“完整性检测 + 降级重试”模式。
- [x] 前端所有异步任务失败都要透出用户可读信息。
- [x] 收尾/总结类输出默认“只补增量”。
- [x] 修改测试 fake 数据时，确保其结构符合生产输出。
- [x] 异步 LLM 调用必须设置超时，防止“正在生成评估”无限卡死（`ASSESSMENT_TIMEOUT_SECONDS=120`）。
- [x] 所有 LLM 调用增加总超时（`LLM_CALL_TIMEOUT_SECONDS=300`），生成求职材料等长任务不再无限等待。
- [x] 长任务必须有进度反馈：`/api/materials/progress` + 前端轮询，避免“静默假死”。
- [x] 批量任务必须校验输入 ID 全部命中：缺失 ID 显式进 `failed`，不能静默少生成。
- [ ] 后续可做：把“完整性检测 + 重试”抽成公共工具，供 tailor/cover_letter/interview_prep 共用。

---

## 7. 验证结果

- 全量 pytest：**816 collected / 810 passed / 6 skipped / 0 failed**（exit 0）。
- 覆盖率：**59.0%**（最近实测，门槛 54）。
- black / ruff / mypy / bandit / check_llm_naming：通过。
- 相关专项测试：mock 相关 44 passed、serve/materials 52 passed、tailor 8 passed。

---

## 8. 后续建议

- 继续补 `serve.py` / `realtime_proxy.py` handler 级测试。
- 把三套浏览器单例进一步合并为 `BrowserManager`。
- 建立“长文本生成完整性”公共工具，统一 resume/cover/prep 的截断重试策略。
- 若 DeepSeek API 不接受 `max_tokens=384000`，按官方输出上限回调并记录。

---

**维护者**：AI Assistant
**日期**：2026-08-17
