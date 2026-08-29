# 职位搜索专项排查与修复复盘（2026-08-16）

> 触发：用户要求“全面细致排查职位搜索代码，查漏补缺；不确认处给最优方案并询问意见；涉及视觉用工具”。
> 结果：搜索链路 11 项明确缺陷 + 7 项策略全部落地；Dashboard 空状态补齐；全量 703 collected / 697 passed / 6 skipped。
> 本文件是搜索链路的长期记忆锚点；模拟面试相关记忆仍以 `retrospective-2026-08-16-mock-interview.md` 为准。
> 给 AI 助手的跨会话行为铁律已固化在根目录 `AGENTS.md`，进入仓库先读它。

---

## 1. 工作范围与结论

| 项目 | 结果 |
|---|---|
| 通读文件 | `search.py` / `filter.py` / `orchestrator.py` / `cli.py` / 17 个平台适配器 / `cookie_health.py` / `agent/tools.py` |
| 明确缺陷 | 11 项全部按推荐方案修复 |
| 策略项 | B1–B7 全部按用户确认的推荐方案执行 |
| 视觉项 | 人工初筛 6 项、Pipeline 2 项全部修复 |
| 后续补做 | 匹配结果 / 已生成文件 Tab 空状态（用户再确认后实现） |
| 最终质量 | 703 collected / **697 passed / 6 skipped / 0 failed**；black / ruff / mypy / bandit / naming 全通过 |

## 2. 决策记录（用户拍板）

- 明确缺陷 1–11：**全部按推荐修**
- B1 去重合并更完整字段：**按推荐**
- B2 关键词相关性过滤（完整命中或中文字面重合率 ≥ 2/3）：**按推荐**
- B3 `search --keyword` 必填、平台别名、direction 作为方向标签、应用 config 过滤：**按推荐**
- B4 分页 `search_max_pages`：**按推荐**（反爬平台 1 页，公开 API 2 页）
- B5 删除智联 HTTP fallback 死代码：**按推荐**
- B6 统一薪资解析器：**按推荐**
- B7 `search_status` 按平台计数并在 Pipeline 展示：**按推荐**
- 匹配/文件空状态：**提示文案 + 快捷跳转按钮；空态禁用无意义按钮**（用户全选推荐项）

## 3. 明确缺陷修复清单

1. `_save_jobs_to_db` 从 `INSERT OR REPLACE` 改为更新式 UPSERT：
   - 保留 `user_flag`（人工筛选标记不再被重跑搜索清空）
   - 已抓 JD 不被短描述覆盖
   - 新行 `is_new=1`，更新行 `is_new=0`
2. `PlatformConfig` 增加 `search_max_pages` / `browser_profile_dir`，智联 profile 配置不再被丢弃
3. 智联 Cookie 体检特殊化：浏览器持久化登录不再误报 `data/cookies/zhilian.json` 缺失；`--probe` 对智联实测浏览器搜索
4. `Job.education` 在 Boss / 猎聘 / 智联 / 网易 / NAURA / YOFC 中实际写入
5. NAURA / YOFC 解析 `Salary`
6. 网易 / BYD / NAURA / YOFC 主键缺失时按 `标题|地点` 兜底，不再全员同 ID
7. `search_status` 按平台计数；scheduler 不再写全局总数
8. 智联浏览器搜索 URL 用 `urllib.parse.quote` 编码
9. 腾讯地点 `"中国 深圳"` → `"深圳"`
10. Boss 会话校验要求 `wt2 + __zp_stoken__`；限速 sleep 只在下一请求前，末尾不空等
11. `job-agent search` 语义修正（见 B3）

## 4. 策略项落地

- **B1**：`_dedup` 合并 salary / description / location / education / published_at / security_id / lid 中更完整的一方
- **B2**：新增 `filter_by_keywords`，search_all 统一应用；chat 删除本地重复过滤
- **B3**：`--keyword` 必填；平台别名 `boss/zhipin/zl/51`；`--direction` 作为显式搜索入库方向；CLI 应用 config 排除词/最低薪/地点
- **B4**：8 个适配器分页；`search_max_pages` 配置；CLI `--max-pages`
- **B5**：删除智联 `_search_keyword_api/_build_headers/_session_cookie_valid/_notify_*` 死代码，测试同步重写
- **B6**：`base.parse_salary_text` 统一 K/千/万/纯数字；日薪/时薪/年薪保守 None
- **B7**：`run_pipeline` 收集 per-platform status 并持久化；`/api/pipeline` 返回 `search_status`；Pipeline tab 显示“最近搜索：✅ BOSS直聘 3 条 · 🔹 腾讯 0 条”

## 5. Dashboard 视觉修复

### 人工初筛
- 空表：`📭 暂无职位数据 + CLI 指引`
- 0 条分页不再显示 `第 1/1 页 共 0 条`
- `每页` 下拉前加标签
- 无数据/无勾选时禁用 抓取JD/查看JD/精排/批量应用
- 清空数据移入独立“危险操作”区
- `LIVE` → `当前时间`

### 流水线
- 后置卡片空态 `-` → `暂无数据`
- 清空数据同步清理 `pipeline_runs`
- 新增“最近搜索”各平台状态行

### Agent智能匹配结果 / 已生成文件（用户追加确认）
- 居中空状态 + 下一步引导按钮（去人工初筛 / 去Agent匹配结果）
- 类型/筛选无命中时显示差异文案 + 清空筛选/查看全部类型按钮
- 空态隐藏匹配分页、禁用批量与生成按钮、禁用全选框
- 勾选数据后按钮自动恢复

## 6. 本次最严重的教训：DOM 结构回归

**事故**：给人工初筛加空状态后，用户发现其他 Tab 也出现职位表格和“暂无职位数据”。

**根因**：`#jobs-panel` 内原本就存在一个多余的 `</div>`，职位表格被浏览器解析到面板外，成为全局元素。此前表体为空，全局表头不明显；空状态文字加入后立即暴露。

**为什么我没发现**：
- 我只做了 `node --check`（JS 语法），没有验证浏览器解析后的 **DOM 层级**
- 视觉复核时只截了目标 Tab，没有逐 Tab 检查隐藏面板
- 测试套件没有“每个面板的表格必须在自己的 panel 内”的结构性断言

**修复**：
- 删除多余 `</div>`，确认 DOM 链为 `#tb → TABLE → DIV → #jobs-panel → BODY`
- 真实 Chrome 逐 Tab 验证 jobs 表格 visibility
- 视觉模型复核 mock / files 等 Tab 不再出现职位表格

**沉淀为铁律**：改 Dashboard HTML/JS 后，必须同时做三件事：
1. `node --check`（语法）
2. DOM 层级断言（关键 `tbody` 的祖先链必须含预期 panel）
3. 真实 Chrome 逐 Tab 可见性 + 视觉模型截图复核

## 7. 测试与回归

- 新增 `tests/test_search_fixes.py`：15 项（UPSERT 保标记、dedup 合并、相关性过滤、分页、配置透传、Cookie 特判、统一薪资、ID 兜底、腾讯地点、平台别名等）
- 更新 `test_zhilian.py`（删除死代码测试，保留浏览器模式）
- 更新 `test_boss.py`（双 cookie 校验、分页间 sleep 语义）
- 更新 `test_cli.py`（`--keyword` 必填）
- 更新 `test_advanced.py`（fake signature、search_status 持久化）
- 最终：**703 collected / 697 passed / 6 skipped / 0 failed**

## 8. 工具与工程经验

1. **修改内嵌 HTML/JS 不要只信源码**：HTML 解析器会修正错误嵌套；必须用浏览器 `getBoundingClientRect()` / `parentElement` 链验证。
2. **空状态文案一定要属于面板**：先确认 `tbody` 的祖先链，再决定写 `innerHTML`。
3. **嵌套引号**：JS 单引号字符串里嵌入 `onclick="switchTab('jobs')"` 会断语法；优先抽成 `goToJobsTab()` 这类无参 helper。
4. **长 Python heredoc 易出问题**：内容含反斜杠/emoji/单引号时优先用 `str_replace_editor`，或只替换不含特殊字符的锚点子串。
5. **bandit nosec 会被 black 重排破坏**：把 `# nosec B324` 写在 `hashlib.md5(` 调用行本身，而不是链式切片的结尾。
6. **测试不能污染真实 output/DB**：结束路径用例必须 mock 落盘函数；文件型 handler 测试用 `monkeypatch.chdir(tmp_path)`；本次搜索专项补强了这条规则。
7. **视觉模型能发现 DOM 外重复元素**：即使 DOM `display` 是 none，截图/视觉复核仍能抓到“重复文案/表格越界”这类问题；每次改 UI 都要做。
8. **用户交互数据优先级最高**：`user_flag`、已抓 JD、生成文件、投递记录属于人工状态，任何自动重跑都不能覆盖。
9. **“表格不能下滑”先定位是功能还是可见性**：程序化 `window.scrollTo/mouse.wheel` 验证滚动、查 `scrollHeight`；主 Dashboard 已补 `html{overflow-y:scroll}` + WebKit 滚动条样式。Chrome 覆盖式滚动条可能仍不常驻显示，此时应说明并提议重启 Chrome 加 `--disable-features=OverlayScrollbar`，或改表格内部滚动容器，不要反复盲改 CSS。另发现 CDP 标签页会偶发“wheel 事件到达但默认滚动不生效”的激活态问题：新建页面再切回并关闭新页面后恢复；真实用户可点击页面或重开标签页。
10. **UI 布局走查修复（用户标注图）**：文件上传 Tab“选择”表头竖排 → `th.select-col` nowrap + 72px；行内「设为默认/预览/删除」统一 72×30px 并排；流水线 6 阶段卡改 `.stage-grid` 宽屏单行、窄屏 3/2 列；全量 696 passed / 6 skipped 复跑通过，视觉复核通过（`ui_fix_upload_final2.png` / `ui_fix_pipeline_final.png`）。
12. **已生成文件表格操作列被截断（用户截图标注，后要求“表格加宽/自适应”）**：根因 `#filesTable{table-layout:fixed}` 第 7 列仅 140px，而「预览/下载/删除」按钮实际约需 180px，按钮从 cell 溢出且外层 wrap 不产生横向滚动（溢出的是 cell 内容而非 table 宽度）。最终方案：百分比列宽（6/33/9/17/7/10/18），≤900px 隐藏“大小/生成时间”+ 操作按钮换行，≤700px 再隐藏“所属岗位”并缩小按钮；`.table-wrap` 增加 WebKit 12px 滚动条兜底。真实 Chrome 1524/1219/1000/900/800/700/500/420 八档验证 `删除` 右缘均未超视口（cut=0）；1219 宽屏与 800 窄屏视觉复核通过；全量 **696 passed / 6 skipped / 0 failed**（`full_pytest_files_table_adaptive.log`，截图 `files_tab_adaptive_final_1219.png` / `files_tab_adaptive_final_800.png`）。
14. **底层模型切换**：`deepseek-v4-pro` → `deepseek-v4-flash`（config.yaml、config.py、providers.py、README/USAGE/development-plan/job-agent-test-flow 同步）。API `/models` 确认 flash 存在；真实调用 `chat_with_reasoning` 验证 thinking 模式正常（返回“正常”，reasoning 119 字符）。全量 **696 passed / 6 skipped / 0 failed**（`full_pytest_model_flash.log`）。
13. **5 图 UI 走查 + 举一反三（用户截图）**：①人工初筛空状态过长且“暂无职位数据”在表格与分页区重复渲染 → 空状态统一 `.empty-state` 卡片（图标+短标题+小提示），`renderJobsPgn` 空态清空；②表格文本列全居中 → 岗位/公司/地点/文件名/所属岗位改左对齐；③投递追踪“操作”列 50px 导致表头竖排、删除按钮被挤 → `#appsTable` 固定布局+90px nowrap 操作列、删除改文字按钮、选择表头横排；④筛选框“按职位(全词匹配)”截断 → 152px；批量占位改为“请选择批量操作”；当前时间移入工具栏卡片；⑤材料审核台空态孤文 → 统一空态。⑥提醒功能缺口：原 `check_application_reminders` 只挂在定时搜索内，scheduler 未运行时设置不生效；现由 Dashboard 后台线程每 60 分钟检查，读取用户在投递追踪页保存的 `reminder_days`，并加 24h 去重。真实 Chrome 逐 Tab 视觉复核通过（`audit5_final_jobs_empty.png` 等）；门禁 black/ruff/mypy/bandit/llm_naming 全过；全量 **696 passed / 6 skipped / 0 failed**（`full_pytest_ui_audit5_fix.log`）。
11. **JD 导入后弹窗不刷新（用户复现）**：手动导入保存成功但「查看JD」弹窗仍显示旧内容。修复：`viewJDForFlagged` 渲染时给每张卡片挂稳定 id（`jdCard_{id}` / `jdText_{id}` / `jdAnti_{id}`）；`saveManualJd` 成功分支原位更新 `jdText_{id}` 文本、隐藏 `jdAnti_{id}`，再 `cancelImportJd(); loadJobs(1)`。验证：真实 Chrome 注入 fake fetch 断言文本从“旧JD内容”变“新JD内容”、反爬徽标 display:none、无 JS 异常；真实职位卡（e98a771d6c49060f）确认 id 存在。全量回归 **696 passed / 6 skipped / 0 failed**（`full_pytest_jd_modal_fix.log`）。

## 9. 数据安全记录

- 用户此前在 Dashboard 主动清空了全部职位/文件数据；我没有擅自恢复。
- `data/backups/agent.db.bak-20260816-pre-clean` 仍保留清空前的 342 jobs / 3 applications / 12 matches / 3 drafts / 25 generated_files / 2 offers（仅 DB 行，磁盘文件无法恢复）。
- 视觉验证中临时写入的 `search_status` 演示行已删除。

## 10. 长期记忆更新

- 搜索链路权威实现：
  - `agent_core/pipeline/search.py`：`resolve_platform_names` / `filter_by_keywords` / `_dedup` 字段合并 / `status_sink`
  - `agent_core/pipeline/orchestrator.py`：`_save_jobs_to_db` UPSERT / `_save_search_statuses`
  - `agent_core/platforms/base.py`：`parse_salary_text`
  - `agent_core/config.py`：`PlatformConfig.search_max_pages / browser_profile_dir`
  - `agent_core/cookie_health.py`：智联浏览器模式特判
- 测试与证据：
  - 回归测试 `tests/test_search_fixes.py`
  - 截图与日志 `data/log_archive/search_audit_20260816/`
- 后续再动 Dashboard 面板：先 DOM 层级断言 → 再 node --check → 再真实 Chrome + 视觉模型逐 Tab 复核。
- 不 commit / 不 push（用户约束）。
