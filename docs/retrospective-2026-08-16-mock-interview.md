# 模拟面试专项复盘（2026-08-16）

> 本文是模拟面试 TAB 全链路测试与查漏补缺的复盘记录，也是后续工作的长期记忆。
> 范围：文字面试、实时语音、prep 题库/focus、评估与产物、前端交互、测试覆盖。
> 最终状态：697 passed / 6 skipped；ruff/mypy/bandit/LLM 命名检查通过。
> 职位搜索专项请见姊妹复盘：`docs/retrospective-2026-08-16-search-audit.md`。
> AI 助手长期记忆铁律见根目录 `AGENTS.md`。

---

## 1. 本次做了什么

1. 梳理模拟面试 TAB 功能清单（前端控件 + HTTP/WS 接口 + 服务端守卫）。
2. 用真实浏览器分别验证文字面试与实时语音，候选人回答严格来自 prep 题库。
3. 修复了测试中发现的全部 bug，并对模拟面试代码做了全量审计、查漏补缺。
4. 补充单元测试、HTTP 集成测试和前端 JS 语法测试。

### 1.1 测试环境与方法

| 项 | 做法 |
|---|---|
| 文字面试 | 真实 Google Chrome（`chrome.exe` + CDP 9222），prep 题库、focus 过滤、13 题与 3 题两种规模均完整跑通 |
| 实时语音 | 真实 Chrome + 真实火山 SC2.0；候选人语音用 Windows SAPI（Huihui）合成 16kHz PCM，通过页面内 `rtWs.send()` 注入，模拟麦克风采集 |
| 真人节奏 | 等 SSE 流结束 + 文本稳定 + TTS 播完，再加阅读延迟，最后逐字输入 |
| 视觉验证 | Playwright 截图 + 视觉模型复核关键状态（开始前、结束态、禁用按钮等） |
| 产物保护 | 任何会覆盖 `output/` 和 `generated_files` 的测试，先备份文件与 DB 行，测后清理新行并精确恢复旧行 |

---

## 2. 发现并修复的问题（按阶段）

### 2.1 文字面试

| # | 问题 | 修复 |
|---|---|---|
| T1 | LLM 空回复导致候选人无法继续 | 空流重试 2 次，仍空则 SSE `error` 事件 |
| T2 | prep 模式下面试官追问/自创题库外问题 | `_BANK_ABSOLUTE_RULE` 双保险，禁止追问和“如果/假设”场景 |
| T3 | focus 过滤后为 0 题时仍注入空题库段和绝对规则 | `_prep_bank_items/_lines/_question_texts` 统一过滤；空结果不注入题库段 |
| T4 | focus 未命中时静默降级为自由面试 | 改为**拒绝开始**（文字+实时），弹窗提示修改或清空 focus |
| T5 | `_asked_so_far` 把“我想一下”等中间输入算成已答题 | 题库模式改为按“面试官回复命中题库哪一题”去重计数（精确包含 + 最长公共子串兜底） |
| T6 | focus 面试的评估拿全题库当评分依据 | `generate_assessment_from_transcript(..., focus=...)` 只给本次范围内的题 |
| T7 | 评估生成失败仍登记/返回不存在的 `_assessment.txt` | 只写/登记存在的文件；`end` 返回 `assessment=None`；前端只在文件存在时显示“查看评估报告” |
| T8 | 手动结束永远标记“中途结束” | 只有 `asked < total` 才标 interrupted |
| T9 | 清空不结束服务端会话（内存泄漏风险） | 新增 `/api/mock-interview/abandon`；前端进行中清空先确认，确认后 abandon 且不生成文件 |
| T10 | 清空按钮注释说“恢复初始”但配置不重置 | 按 D1-A 恢复职位/prep/focus/难度/模式/TTS 到页面初始值 |
| T11 | 文字结束气泡只显示 `[面试结束]` | 保留“面试结束。”，只截断评估 JSON |
| T12 | 难度选择没有说明 | 增加 tooltip 与 README 说明：难度为软提示，prep 题量不变 |

### 2.2 实时语音

| # | 问题 | 修复 |
|---|---|---|
| R1 | 候选人说“没有了”后面试官说“面试结束。”但会话不收尾 | 自然结束短语整句匹配触发评估 + `TTS_ENDED` 兜底（不依赖火山 status_code）+ 状态码日志 |
| R2 | focus 过滤后总题数仍按全题库计算，反问阶段被计成题目 | `total_questions` 按 focus 过滤后传入；`_count_questions_asked` 到反问入口为止 |
| R3 | “没有了”作为子串误伤正常回答（“暂时没有了”） | 自然结束短语只允许整句匹配；`面试结束/再见` 保持包含匹配 |
| R4 | manifest 规则 4 与规则 9 冲突（禁止追问 vs 适当追问） | 题库非空时禁止追问，题库为空才允许深入 |
| R5 | 清空面板不关闭 `rtWs`，后续消息会写回已清空页面 | 前端发送 `{type:"abandon"}`；服务端 `_abandon()` 关闭连接且不保存 |
| R6 | `ended` 消息处理后 `onclose` 可能把 ✅ 状态覆盖回“正在生成” | `_rtEnded` 标志保护；评估卡片渲染包 try/catch；`_send_browser` 失败打日志 |
| R7 | 自定义 db_path 时实时语音查询/登记仍写默认 `data/agent.db` | `start_proxy_in_thread` 接受 db_path，贯穿岗位查询、prep 加载、产物登记 |

### 2.3 前端与 UX

| # | 问题 | 修复 |
|---|---|---|
| U1 | 未开始面试时麦克风可点击 | 初始 disabled + `toggleMockMic` 统一拦截“请先开始面试” |
| U2 | 禁用按钮视觉上像可点击 | 统一中性灰 `button:disabled`（视觉模型复核通过） |
| U3 | focus 拦截后状态栏残留“连接中...” | 启动失败清空状态栏 |
| U4 | realtime 未启用时自动切文字，但下拉框仍显示实时语音 | 同步把下拉框/rtModeOverride/hint 切回文字模式 |
| U5 | 清空/结束弹窗中的“查看评估报告”按钮在无评估时仍出现 | `updateEndProgress` 按 `names.assessment/md` 条件显示 |

### 2.4 流水线统计

| # | 问题 | 修复 |
|---|---|---|
| P1 | 实时语音文件 `*_realtime_mock*` 不被模拟面试卡片计数 | 改为按“面试场次”统计：`file_type=mock_interview` 或文件名含 `_mock`，并把 transcript/assessment 归并成 1 次 |
| P2 | 文字面试一场生成两个文件会显示“已练习 2 次” | 同上归并逻辑 |

### 2.5 测试覆盖

- 新增 **19 个测试**：
  - `tests/test_mock_end.py`：focus 未命中/拦截、asked_indices 计数、题目模糊匹配、只登记存在文件、评估失败无文件名、完整结束不标中断、focus 评估过滤、abandon
  - `tests/test_realtime_proxy.py`：自然结束词防误判、abandon 关闭连接
  - `tests/test_mock_api.py`：start/reply 生命周期、abandon、end 可选 assessment、latest-transcript 下载、assessment preview、OpenAPI 路径
  - `tests/test_serve_features.py`：内嵌 Dashboard JS `node --check` 语法校验

---

## 3. 最终验证

| 检查 | 结果 |
|---|---|
| pytest 全量 | **697 passed / 6 skipped / 0 failed** |
| ruff（agent_core） | 通过 |
| mypy | 通过 |
| bandit | 0 high / 0 medium（2 low 既有提示） |
| `scripts/check_llm_naming.py` | 通过 |
| Dashboard JS `node --check` | 通过 |
| 真实 Chrome 视觉验证 | 初始态/结束态/禁用态/focus 拦截/清空确认 全部通过 |
| 实时语音最终复测 | 真实火山：自我介绍 → 3 题 → 反问 → 没有了 → 评估生成 ✅ |

---

## 4. 经验与自我改进

### 4.1 做对的事

1. **“像真人一样测试”**：用户不接受无头自动化浏览器。改用系统真实 `chrome.exe` + CDP，窗口持续可见；候选人回答等待完整播报后逐字输入。
2. **外部服务降级时留证据并等待**：火山额度耗尽时没有反复硬试，而是先做单元验证、备份环境、等额度恢复后重试。
3. **破坏性测试先备份**：每次覆盖 `output/` 与 DB 前，备份文件内容和 DB 整行，结束后按原 id 精确恢复。
4. **修复前给选项、修复后补回归**：bug 都先给推荐方案让用户拍板；修完立即加测试，避免下次复发。
5. **视觉验证闭环**：截图后让视觉模型复核，发现“45% 透明度仍不够像禁用”，升级为中性灰并再次复核。

### 4.2 踩过的坑（以后避免）

1. Playwright Python 的 `page.press_sequentially` 不存在，应使用 `page.locator(...).press_sequentially` 或 `page.type`。
2. 长聊天的 `full_page` 截图可能 30s 超时；结束态截图要设更长超时或退回 viewport 截图。
3. Git Bash 里 `nohup ... &` 启动的进程可能随 shell 退出被回收；Windows 上用 PowerShell `Start-Process` 才可靠。
4. 用 heredoc 生成含 `\n` 转义的 Python 源码时，多层转义容易变成真实换行；最稳的是运行时 `chr(10)`，或先写文件再用 `repr` 校验。
5. 实时语音测试不能用真人麦克风时，Windows SAPI 合成 16k PCM + `rtWs.send` 注入是可行路径，但 ASR 会有口误和重复（“麦维/司印/HVT”），评估解读时要说明这是输入噪声。
6. `wait_ai_finished` 的基线容易取晚（把已到达的 AI 气泡当成未来气泡），导致干等 3 分钟；等待新消息前必须**先取 count 再触发动作**。

### 4.3 沟通与流程

- 用户关心“任务状态为什么不实时”：说明 todo 是手动清单，且长命令执行期间无法中途更新；后续承诺小步骤执行前/后立即更新 todo。
- 用户对测试产物敏感：文字/实时产物每次测完都清理，DB 记录按 id 删除，证据保留在 `data/log_archive/`。
- 不确认的 UX 决策（清空语义、focus 未命中行为、难度含义等）全部列表给选项，用户选择后执行，避免自作主张。

### 4.4 还存在的已知限制（后续可做，不阻塞）

1. 实时语音复测用的是合成语音，真实人声的 ASR 准确率和打断体验仍需真人验证。
2. 刷新页面不会恢复未结束会话；服务端会话只能靠结束/abandon 或 50 上限淘汰。
3. 难度仍是软提示；如果未来要做真实难度，需要设计题量/追问策略。
4. 前端 JS 目前只有语法测试，没有 DOM 行为测试；可引入 Playwright 测试（需要评估 CI 成本）。
5. 火山 `tokens_lifetime` 额度会周期性耗尽，测试排期建议避开或准备备用账号。

---

## 5. 长期记忆更新点

- 模拟面试文字/实时收尾逻辑的权威实现：
  - 文字：`agent_core/pipeline/interview_prep.py`（`_BANK_ABSOLUTE_RULE`、`_asked_so_far`、`_match_bank_question`、`abandon_mock_session`）
  - 实时：`agent_core/server/realtime_proxy.py`（`_NATURAL_END_PHRASES`、`TTS_ENDED` 兜底、`_rtEnded` 前端保护）
- 题库过滤唯一口径：`_prep_bank_items/_lines/_question_texts`，不要再各自实现。
- 测试数量与覆盖以 `README.md` 当前数字为准（697 passed / 6 skipped）。
- 真实 Chrome 测试入口：`chrome.exe --remote-debugging-port=9222` + Playwright `connect_over_cdp`。

---

## 6. 2026-08-16 全项目整理增量（复盘后追加）

复盘完成后又做了一次全项目整理，更新本文件作为后续记忆：

1. **测试隔离修复**（防止测试污染真实 `output/`）：
   - `tests/test_advanced.py` 的 `save_interview_prep` / `save_resume` 从 `output_dir="output"` 改为 `tmp_path`。
   - `tests/test_mock_api.py` 两个落盘测试加 `monkeypatch.chdir(tmp_path)`。
   - `tests/test_mock_end.py` 两个真正走到“面试结束”的用例补 `_save_mock_transcript` no-op 补丁。
   - 根因：结束路径用例未 mock 落盘函数，pytest 会把 `测试公司_..._mock_interview.md` 重新写回真实 `output/`。
2. **UI 视觉复核又发现并修复**：focus 输入框 130px 太窄导致占位符截断 → 170px；`textarea/input/select:disabled` 增加统一灰色禁用样式。后续按用户确认又应用 4 项默认状态优化：未选职位时「开始面试」禁用、「朗读面试官」默认关闭、全默认且无记录时「清空」禁用、未开始面试时输入框占位为「开始面试后可输入...」。全部用真实 Chrome + 视觉模型复核通过。
3. **数据整理**：测试残留 output 文件归档到 `data/log_archive/output_test_artifacts_20260816/`；`generated_files` 中 4 条指向已不存在文件的僵尸行删除；DB 清理前备份到 `data/backups/agent.db.bak-20260816-pre-clean`；旧 realtime 记录（392/393）保持原样。
4. **代码整理**：`black` 全量格式化（88 文件）、`ruff check agent_core scripts tests` 0 告警、mypy/bandit/check_llm_naming 通过；删除了 `_ensure_dashboard` 里的死表达式并给 subprocess 加 nosec；CI 覆盖率门槛从 79 对齐到 pyproject 的 48。
5. **最终基线**：697 passed / 6 skipped / 0 failed（4 项 UX 应用后再次全量复跑通过），覆盖率 52.0%（serve.py 18.5% / realtime_proxy.py 38.0%）；服务已用 `job-agent serve --daemon` 重启，8765/8766 健康。
6. **文档**：`docs/USAGE.md` 新增服务运维、实时语音配置与 FAQ；`docs/ARCHITECTURE.md` 重写为完整文件清单；`data/log_archive/README.md` 建立归档索引。

---

## 7. 2026-08-16 职位搜索专项排查（追加）

按用户确认的推荐方案完成搜索链路整改：

1. **数据安全**：`_save_jobs_to_db` 从 `INSERT OR REPLACE` 改为更新式 UPSERT，保留 `user_flag`，不回退已抓 JD，新行 `is_new=1`、更新行置 0。
2. **去重质量**：跨平台合并时取薪资/描述/地点/学历等更完整字段；共享关键词相关性过滤下沉到 `search.py`（完整命中或中文重合率 ≥2/3），CLI/pipeline/chat 统一生效。
3. **配置与分页**：`PlatformConfig` 新增 `search_max_pages` 和 `browser_profile_dir`（智联 profile 配置不再被丢弃）；8 个适配器支持分页；Boss/猎聘/智联默认 1 页、公开 API 默认 2 页；CLI 增加 `--max-pages`。
4. **平台修复**：智联搜索 URL 正确编码；腾讯中国城市前缀；Boss 会话校验要求 wt2 + `__zp_stoken__`；请求间隔只放在下一请求前；删除智联已废弃的 HTTP fallback 死代码。
5. **Cookie 体检**：智联改为浏览器模式判定（不再误报 `data/cookies/zhilian.json` 缺失），`--probe` 对智联实测浏览器搜索。
6. **数据补齐**：适配器写入 `education`；NAURA/YOFC 解析 Salary；缺失主键时用标题/地点兜底 ID；统一 `base.parse_salary_text`（K/千/万/纯数字；日薪/时薪/年薪保守返回 None）。
7. **搜索审计**：`search_status` 按平台记录，Pipeline tab 显示“最近搜索”各平台结果数；scheduler 不再写入全局总数。
8. **Dashboard 视觉**：人工初筛空状态、0 条分页、每页标签、操作按钮禁用态、清空数据独立危险区、时钟文案全部修复；Pipeline 后置卡空态“暂无数据”；清空数据同步清 `pipeline_runs`。随后发现并修复一个 DOM 结构问题：`#jobs-panel` 内多余的 `</div>` 让职位表格被浏览器解析到面板外，导致其他 Tab 也渲染职位表格（空态文字加入后暴露），已将表格与分页容器正确放回 `#jobs-panel`，并用真实 Chrome + 视觉模型复核 mock/files 等 Tab 不再出现职位表格。
9. **验证**：新增 `tests/test_search_fixes.py`（15 个回归）；全量 703 collected / **697 passed / 6 skipped / 0 failed**；black/ruff/mypy/bandit/naming 全部通过；真实 Chrome + 视觉模型复核人工初筛/Pipeline。
10. **空状态补全**：按用户确认，「Agent智能匹配结果」和「已生成文件」增加居中空状态提示 + 快捷跳转按钮；0 条时隐藏匹配分页、禁用批量/生成/清空等无意义按钮，并修复匹配全选框在空态仍可点的问题。视觉模型复核通过（截图 `data/log_archive/search_audit_20260816/match_empty_final.png`、`files_empty_after_hint.png`）。


---

## 8. 2026-08-16 实时语音全题库复测（focus 空 / 简单 / 鹏辉能源设备工程师）

1. **测试范围**：实时语音模式，职位「设备工程师 @ 鹏辉能源」，prep 题库全量 21 题（18 轮面 + 3 项目深挖）+ 反问，候选人回答严格取自题库 `self_intro/sample`，未编造。面试官 21 题全部按序问完，反问与评估产物正常。
2. **发现并修复**：
   - B1 结束进度弹窗文案矛盾：`updateEndProgress('done')` 只改图标未改文字 → 完成态改为「面试记录已保存 / LLM 评估已生成 / 面试记录与评估已生成」。
   - B2 自然结束语「没有了」短音频 ASR 无结果时页面干等 → 反问阶段状态栏主动提示「没有请说没有了；说完未结束可点结束面试」，开麦后 6 秒无 ASR 再提示未听清。
   - B3 ASR 结果晚到导致 transcript 乱序、评估误判 → `RealtimeSession` 维护 `_interviewer_indices`，`_record_candidate_asr()` 把晚到文本回填到对应面试官轮次下（插到下一题之前）；新增回归测试 `test_realtime_late_asr_inserted_before_next_interviewer_turn`。
   - B4 长自我介绍 ASR 截断：本次为合成语音测试噪声，暂不改代码，待真人麦克风复测。
3. **验证**：B1 用真实 Chrome 调用 `showEndProgress/updateEndProgress` 断言完成态文案 + 视觉复核；B2 用真实 Chrome 模拟“开麦后 6 秒无 ASR”断言提示切换；B3 单元测试 10 项通过。另跑了一次 focus=PLC 的**单题真实火山链路回归**：反问阶段状态栏正确出现结束语引导，晚到 ASR 文本不再落到“面试结束”之后（`mini_final_*.md/txt` 为证据）。全量 **703 collected / 697 passed / 6 skipped / 0 failed**（`full_pytest_after_b1b2b3.log`），black/ruff/mypy/bandit/naming 全过。
4. **证据**：`data/log_archive/mock_realtime_retest_20260816/`（配置截图、过程中截图、最终聊天文本、最终 transcript/assessment 归档、PCM 合成脚本、测试脚本与时间线）。
5. **测试产物已清理**：output 下的 `鹏辉能源_设备工程师_realtime_mock*.md/_assessment.txt` 与 generated_files 442/443 已归档后删除，未污染用户数据。
