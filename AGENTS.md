# AGENTS.md — AI 助手长期记忆

> 本文件是我（AI 助手）在 agent-core 仓库的跨会话记忆锚点。进入本仓库处理任何任务前，先读本文件；每次重要工作完成后更新本文件与对应复盘文档。
> 给人看的操作手册是 `docs/USAGE.md`；本文件是我自己的行为规则和防错清单。

## 0. 不可违背的约束

- 只改本地工作区，**不 commit / 不 push**（用户约束）。
- 用户的人工状态数据优先级最高：`user_flag`、已抓 JD、投递记录、生成文件、Offer 等**任何自动重跑都不能覆盖或删除**；破坏性操作先备份。
- 不确定的 UX/策略问题：用 `ask_user_question` 给出“推荐项”让用户选择，确认后再改。
- 涉及视觉的验证：用系统真实 Chrome（`--remote-debugging-port=9222`）+ Playwright `connect_over_cdp` + `vision_read_image`，不接受只查 DOM 字符串。
- 测试产物：每轮真实测试后清理 output/DB 中的测试残留，证据保留到 `data/log_archive/`；不要污染真实数据。
- 用户候选人答案不得编造；模拟面试只能使用 prep 题库 `self_intro + a` bullets。
- 用户说“继续”时，默认把剩余可选小项做完，不要反复确认；只有真正需要方向选择时才提问。
- 视觉模型可能误读按钮禁用态等状态，关键 UI 状态要用 DOM/计算样式二次确认。

## 1. 项目快照（2026-08-18）

- Python ≥3.12；SQLite schema v12；Dashboard HTTP `127.0.0.1:8765`；实时语音 WS `127.0.0.1:8766`（随 serve 启动）。
- 2026-08-17 重构：`serve.py` 前端资源拆到 `server/dashboard_html.py`、HTTP 工具到 `server/http_utils.py`、守护进程到 `server/daemon.py`；平台适配器统一注册表 `platforms/registry.py`、浏览器锁清理 `platforms/browser_utils.py`。
- 服务运维：`job-agent serve --daemon` / `--stop`；PID 文件 `data/dashboard.pid`；日志 `data/dashboard.log`。
- 测试基线：**1306 passed / 6 skipped / 0 failed**（普通全量）；含 Windows Toast 集成 **1311 passed / 1 skipped / 0 failed**；覆盖率 84.4%（门槛 70）。
- 2026-08-18 新增功能/UI：清除匹配历史反馈（`DELETE /api/match/feedback`）、手动新增投递（`POST /api/application`）、投递状态统计/筛选/搜索/排序、已生成文件搜索/排序/加载更多、流水线 9 阶段漏斗与卡片统一、10 Tab UI 全面视觉优化。
- 数据备份：`data/backups/agent.db.bak-20260816-pre-clean`（342 jobs 等清空前快照）；旧实时记录 DB 行 392/393 必须保留。
- 权威文档：`README.md`、`docs/USAGE.md`、`docs/ARCHITECTURE.md`、`docs/job-agent-test-flow.md`、`docs/README.md`。
- 复盘记忆：`docs/retrospective-2026-08-16-mock-interview.md`、`docs/retrospective-2026-08-16-search-audit.md`、`docs/retrospective-2026-08-17-phase0-3-and-bugfixes.md`、`docs/retrospective-2026-08-18-coverage-boost.md`、`docs/retrospective-2026-08-18-full-delivery.md`。

## 2. 改代码前必须做的检查

1. 先读 `AGENTS.md` + 对应复盘文档。
2. 用 `ask_user_question` 确认任何语义不清/会改变用户流程的改动。
3. 涉及数据表/文件覆盖前，先备份 DB 行与文件内容到 `data/backups/` 或 `data/log_archive/`。

## 3. Dashboard HTML/JS 铁律（本次血泪教训）

修改内嵌 HTML/JS 后，按顺序做三件事：

1. **JS 语法**：提取 `<script>` 跑 `node --check`（已有测试 `test_dashboard_embedded_js_syntax`）。
2. **DOM 层级断言**：关键元素（每个 `tbody`、空状态容器、分页容器）的 `parentElement` 链必须归属预期 panel。历史事故：`#jobs-panel` 内多余 `</div>` 让职位表格被浏览器解析到面板外，空状态文字出现到所有 Tab。
3. **逐 Tab 可见性 + 视觉复核**：真实 Chrome 逐 Tab 断言 `getComputedStyle(panel).display`、`getBoundingClientRect()`；截图给 `vision_read_image` 复核，重点检查“跨 Tab 串台 / 重复文案 / 越界元素”。

额外防错：

- 空状态文案先确认 `tbody` 归属再写 `innerHTML`。
- JS 单引号字符串里嵌 `onclick="switchTab('jobs')"` 会断语法；抽成无参 helper（`goToJobsTab()`）。
- bandit `# nosec` 写在调用行本身，避免被 black 重排后失效。
- 长 Python heredoc 含反斜杠/emoji/单引号时优先用 `str_replace_editor`，或只替换不含特殊字符的锚点子串。
- UI 按钮状态要与数据/勾选状态联动：无数据/无勾选时禁用，操作后刷新状态。
- 表格“选择”表头加 `th.select-col{white-space:nowrap}`，宽度不要低于 72px；行内操作按钮统一放 `.row-actions`，固定 `72×30px`、`inline-flex` 居中、不换行（禁用态也保持同尺寸，只降透明度）。
- `#filesTable` 不要写死像素列宽（用户明确要求自适应）：`table-layout:fixed` + 百分比列宽（选择 6 / 文件名 33 / 类型 9 / 岗位 17 / 大小 7 / 时间 10 / 操作 18）；≤900px 隐藏“大小/生成时间”并让 `.file-actions` 换行；≤700px 再隐藏“所属岗位”并缩小按钮。只给操作列固定窄列宽会导致按钮从 cell 溢出，外层 `.table-wrap` 不会产生横向滚动条、按钮被视口截断。另给 `.table-wrap` 配 WebKit 12px 横向滚动条样式作兜底。
- 阶段卡片布局用 `.stage-grid{grid-template-columns:repeat(6,minmax(0,1fr))}`，窄屏 1100/640 断点降为 3/2 列，保证 6 卡宽屏单行。
- JD 导入成功后要原位刷新「查看JD」弹窗：`viewJDForFlagged` 给卡片/文本/反爬徽标挂 `jdCard_{id}` / `jdText_{id}` / `jdAnti_{id}`；`saveManualJd` 成功分支更新 `jdText_{id}` 文本并隐藏 `jdAnti_{id}`，避免关闭导入窗后弹窗里还是旧 JD。
- “表格不能下滑”先分清是功能问题还是滚动条可见性问题：程序化 `window.scrollTo/wheel` 验证能否滚动、检查 `scrollHeight`；主 Dashboard 已加 `html{overflow-y:scroll}` + WebKit 滚动条样式。若 Chrome 使用覆盖式滚动条仍不常驻显示，向用户说明并提议重启 Chrome 加 `--disable-features=OverlayScrollbar`，或改表格内部滚动容器，不要反复盲改 CSS。
- 空状态统一用 `.empty-state` 组件（白卡片+图标+短标题+小提示），且无数据时**隐藏分页区**；禁止同一 Tab 出现两条“暂无数据”。材料审核台/投递追踪/Offer 等空状态已统一。
- 表格文本列（岗位/公司/地点/文件名/所属岗位）左对齐；编号/薪资/时间/勾选/操作居中。操作列要 `white-space:nowrap` 且 ≥90px；“选择”表头用 inline-flex 横排，不要 `<br>`。
- 投递提醒由 Dashboard 后台线程每 60 分钟调用 `check_application_reminders`（读取用户在投递追踪页保存的 `scheduler_state.reminder_days`），同一提醒 24h 内只弹一次 Windows Toast；scheduler 关闭也有效。
- CDP 复现“wheel 事件到达但页面不滚”时，可能是标签页激活态异常：`bring_to_front` + 新建一个页面再切回并关闭新页面，可恢复 wheel 默认滚动；真实用户同理建议点击页面或重启该标签页。

## 4. 搜索链路权威实现

- `agent_core/pipeline/search.py`：
  - `resolve_platform_names`（别名 boss/zhipin/zl/51）
  - `filter_by_keywords`（完整命中或中文字面重合率 ≥2/3）
  - `_dedup` 合并更完整字段；`status_sink` 收集 per-platform 结果
- `agent_core/pipeline/orchestrator.py`：
  - `_save_jobs_to_db` 是 **UPSERT**：保留 `user_flag`、JD 不回退、新行 `is_new=1`
  - `_save_search_statuses` 写 per-platform `search_status`
- `agent_core/platforms/base.py`：`parse_salary_text`（K/千/万/纯数字；日薪/时薪/年薪返回 None）
- `agent_core/config.py`：`PlatformConfig.search_max_pages` / `browser_profile_dir`
- `agent_core/cookie_health.py`：智联按浏览器持久化登录特判，不误报 cookie 文件缺失
- CLI 语义：`job-agent search --keyword` **必填**；`--max-pages`；`--direction` 在显式关键词模式作为入库方向；search 应用 config 过滤
- 分页默认：Boss/猎聘/智联 1 页（反爬），公开官网 API 2 页

## 4.5 底层 LLM 驱动

- 当前模型：`config.yaml` → `llm.model: deepseek-v4-flash`（2026-08-16 由 `deepseek-v4-pro` 切换）。
- 代码默认值同步：`agent_core/config.py:LLMConfig.model`、`agent_core/llm/providers.py:DeepSeekProvider.model`。
- `deepseek-v4-flash` 已验证支持 `reasoning_effort=high + extra_body.thinking.enabled`；注意 max_tokens 太小会先被 reasoning_content 吃完，测试时给足 300+。
- **`max_tokens` 是输出上限，不是输入上限**；thinking 模式下 = reasoning + content 共享输出额度。
- 当前配置：`llm.max_tokens: 384000`（2026-08-17 按用户要求设置；若 API 拒绝再回调）。
- 长文本生成（tailor/cover/prep/mock）必须做完整性校验；`tailor_resume` 已实现“章节缺失 → 关闭 thinking 重试一次”。

## 4.6 材料生成与失败透出

- `/api/materials/generate` 中 resume/HR 与 interview_prep 是分离的 best-effort 步骤；`interview_prep_failed` 必须返回给前端展示，不能静默。
- `/api/materials/regenerate` 成功后清空 `feedback`，避免“意见已应用却还留在输入框/草稿里”。
- 前端生成/再生成弹窗必须展示 `interview_prep_failed`，否则用户会误以为“没生成”。
- **长任务防卡死（2026-08-17）**：`call_llm_with_retry` 默认 `LLM_CALL_TIMEOUT_SECONDS=300` 总超时（含重试），所有 LLM 调用不再无限等待；`/api/materials/progress` 提供生成/再生成进度，前端轮询显示“第几个/当前职位/当前步骤”。
- **生成材料必须校验 job_ids 全部命中**：`/api/materials/generate` 对找不到的 job_id 要加入 `failed` 并返回，`total=len(job_ids)`，不能静默少生成（2026-08-17 实测 3 选 1 漏生成的教训）。
- **生成/再生成失败自动重试一次（thinking 保持开启）**：材料生成始终按配置（thinking high）跑；若 LLM 超时/报错，用同一个 thinking provider 再重试一次，不降级到 no-thinking，保证输出质量。
- **DeepSeek HTTP 客户端加固**：`DeepSeekProvider` httpx 客户端显式 connect/read 超时并禁用 keep-alive，降低共享连接池半开连接导致的“卡住”；LLM 调用仍有 `LLM_CALL_TIMEOUT_SECONDS=300` 总超时兜底。
- **公共文本完整性工具（2026-08-18）**：`agent_core/pipeline/text_utils.py` 提供 `has_all_sections` / `retry_if_incomplete`，tailor 已接入，后续 cover/prep 可复用。

## 5. 模拟面试权威实现

- 文字：`agent_core/pipeline/interview_prep.py`；实时：`agent_core/server/realtime_proxy.py`
- 题库过滤唯一口径：`_prep_bank_items/_lines/_question_texts`
- 结束判定唯一短语「以下是您的表现评估」；prep 题库问完前强制继续
- 产物：终端 `_mock_interview.md + _assessment.json`；Dashboard 文字 `_assessment.txt`；实时 `_realtime_mock.md + _realtime_mock_assessment.txt`
- 前端状态机：`mockSession.active`、`rtWs`、`_rtEnded`、`_rtGenerating`；清空需确认并 abandon
- 实时语音 transcript 顺序：`RealtimeSession._interviewer_indices` + `_record_candidate_asr()`；ASR 晚到也必须回填到对应面试官轮次下，不能直接 append。
- 反问阶段 UI：检测到「我的问题问完了/你有什么想问我的吗」后给结束语引导；开麦 6 秒无 ASR 提示未听清，避免“没有了”没识别时干等。
- 结束进度弹窗 `updateEndProgress`：阶段完成时图标和文字要一起改成完成态（面试记录已保存 / LLM 评估已生成），不能只改绿勾。
- **反问列表截断修复**：文字/终端 mock 的 `max_tokens` 必须用 `config.llm.max_tokens`，不能用 1024；Prompt 强制“完整列出全部推荐反问”。
- **评估生成卡死修复（2026-08-17）**：`generate_assessment_from_transcript` 必须带超时（`asyncio.wait_for`，默认 `ASSESSMENT_TIMEOUT_SECONDS=120`）；LLM 偶发长时间不返回时降级为仅保存记录/内联解析，不能让前端“正在生成评估”无限等待。
- **反问环节不能提前结束（2026-08-17）**：文字模式只要面试官说出“我的问题问完了/你有什么想问我的吗”，该轮必须 `turn_end` 等候选人回应，即使同一轮带了“以下是您的表现评估”也不能结束；实时语音模式同样在 `TTS_ENDED` 时检查 `_reverse_phase_pending()`，候选人未回应反问前禁止触发评估。
- **实时语音结束弹窗兜底（2026-08-18）**：若后端已生成 `_realtime_mock.md/_assessment.txt` 但浏览器因 WS 断开/丢消息没收到 `ended`，前端会轮询 `/api/files` 找到文件后自动把弹窗置为完成态，避免“正在生成评估报告”永久卡住。
- **评估生成必须容错（2026-08-18）**：`generate_assessment_from_transcript` 先普通输出，解析失败自动用 `response_format={"type":"json_object"}` 再试一次；避免 DeepSeek 偶发返回空/非 JSON 导致实时语音“有记录无评估”。

## 6. 测试与质量

- 全量：`python -m pytest -q`（约 5 分钟）
- 搜索回归：`tests/test_search_fixes.py`；模拟面试：`test_mock_end.py`、`test_mock_api.py`、`test_realtime_proxy.py`
- 新增专项：`test_registry.py` / `test_browser_utils.py` / `test_http_utils.py` / `test_serve_auth.py` / `test_playwright_jd_utils.py` / `test_boss_browser_utils.py` / `test_interview_prep_prompt.py` / `test_scripts.py`
- 门禁：`black --check agent_core scripts tests`、`ruff check agent_core scripts tests`、`mypy agent_core --ignore-missing-imports`、`bandit -r agent_core -c pyproject.toml`、`python scripts/check_llm_naming.py`
- 改完代码：先跑相关测试 + 门禁，再跑全量；记录日志到 `data/log_archive/`，并同步更新所有文档中的测试数。

## 7. 真实浏览器测试工具箱

- 启动 Chrome：`chrome.exe --remote-debugging-port=9222 --user-data-dir=<profile>`（系统 Chrome，非自动化 Chromium）
- 连接：`playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")`
- 等待新 AI 气泡：**先取当前 count，再触发动作**，否则会等 180 秒超时
- 长页面截图：`full_page` 可能超时，改 viewport 截图或加大 timeout
- 候选语音模拟：Windows SAPI → 16k PCM → `window.rtWs.send(pcm.buffer)`
- Git Bash 后台进程：用 PowerShell `Start-Process` 或 `job-agent serve --daemon`，不要 `nohup &`
- **BrowserManager（2026-08-18 引入）**：`agent_core/platforms/browser_manager.py` 提供统一的浏览器实例 + 空闲关闭管理；boss/zhilian/playwright_jd 三个单例均已接入（boss/zhilian 用 manager 存实例，playwright_jd 用 manager 管 idle）。

## 8.5 输出纪律（2026-08-17 新增）

- 同一轮已给过完整汇报时，系统要求的目标收尾/总结只写**增量 + 简短确认**，不要整段重复。
- 收尾消息默认最短原则；除非用户明确要求重新总结。
- **任务列表逐项更新**：`todo_write` 每完成一个步骤就立即把该项标为 `completed`，不要攒到最后一轮统一更新；同时只把正在进行的项标 `in_progress`。

## 8. 每轮工作完成后的记忆更新流程

1. 更新/新建复盘文档（`docs/retrospective-<date>-<topic>.md`）
2. 更新本 `AGENTS.md` 中的快照、铁律和权威实现指针
3. 同步 README / ARCHITECTURE / USAGE / job-agent-test-flow 的测试数与文档链接
4. 更新 `data/log_archive/README.md` 证据索引
5. 重启服务后确认 8765/8766 健康、PID 变更
6. 清理测试残留与 `__pycache__`，但不删 `data/log_archive/`、`data/backups/`
