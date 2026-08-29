# Job Agent 完整测试流程

> 基于 agent-core 架构(17 CLI / 10 tab dashboard / schema v12 / 8 live 平台 + 2 存根)梳理的可执行测试 SOP。
> 每阶段含:**测试点 / 步骤(CLI+dashboard) / 验收标准 / 已知坑**。
> 以代码为准(docs/ARCHITECTURE.md 等文档有漂移,见 codebase-map §11)。

---

## 前置准备

| 项 | 要求 | 验证 |
|---|---|---|
| Python | ≥3.12 | `python --version` |
| 依赖 | 已装 | `python -c "import agent_core"` |
| `.env` | `DEEPSEEK_API_KEY` (api.deepseek.com,deepseek-v4-flash) | `job-agent check-cookies` 不报缺 key |
| `config.yaml` | 方向/匹配配置 | `job-agent chat` 能起 |
| DB | `data/agent.db` schema v12 | `job-agent cleanup --dry-run` |
| Cookie | 8 平台(boss/liepin/zhilian 需浏览器导出) | `job-agent check-cookies --probe` |
| serve | 8765 端口 | `curl http://127.0.0.1:8765/` |

**启动 dashboard**:`job-agent serve` 或 `python -m agent_core.server.serve`(后台跑建议独立终端,background task 会被清理)

---

## 阶段 0:环境自检

**测试点**:cookie 健康 / LLM 可用 / 测试套件 / DB 迁移

**步骤**:
```bash
job-agent check-cookies --probe              # 8 平台 cookie + 真实搜索探测
python -m pytest -q                           # 自动化测试(2026-08-18 实测 1306 passed / 6 skipped / 0 failed)
python -m pytest tests/test_serve.py tests/test_cli.py -q   # 核心非平台测试
```

**验收**:
- check-cookies 各平台 ✅(boss/liepin/zhilian 需有效 cookie)
- pytest 非平台测试全过(平台测试 7 failed 多为 Playwright profile 占用,非功能 bug)

**坑**:
- Boss `code:37`=反爬(120s backoff),其他非 0=cookie 过期
- 智联需浏览器模式( Akamai),HTTP 回退禁用
- Windows GBK 终端乱码非数据损坏,脚本加 `sys.stdout.reconfigure(utf-8)`

---

## 阶段 1:搜索(search)

**测试点**:多平台并发 / 跨平台去重 / 0 结果 diagnose / 反爬 backoff

**步骤**:
```bash
job-agent search --keyword Python --platforms boss_zhipin,liepin,tencent   # --keyword 必填
job-agent search --keyword Python --platforms boss,zl --max-pages 2        # 平台别名 + 分页
```
dashboard: 📋人工初筛 tab 可见新岗位

**验收**:
- `jobs` 表有数据(`SELECT COUNT(*) FROM jobs`)
- 人工初筛 tab 显示岗位列表,`is_new` 标记(仅首次入库为 1)
- 跨平台去重(dedup_key=company_normalized|_norm_title 精确匹配)
- 关键词相关性过滤生效(完整命中或中文重合率 ≥ 2/3,无关推广岗不入库)
- Pipeline tab 显示最近搜索各平台结果数(search_status)

**坑**:
- Boss Bot Manager:headed 持久 profile 是唯一靠谱方案(headless/静态 cookie 都被检测)
- 智联只发 at/rt cookie,排除 Akamai sensor(FSSBBIl1UgzbN7NS)
- BYD 分页 80-95% 重叠,按 positionType 抓
- 0 结果自动 `diagnose_empty_results` 给排查指引

---

## 阶段 2:人工初筛(filter)

**测试点**:🌟感兴趣 / ❌不合适 标记 / 批量标记

**步骤**(dashboard 📋人工初筛 tab):
- 单条:点 🌟 或 ❌
- 批量:勾选 → 批量标记
- 后端:`POST /api/flag/{id}` / `POST /api/flag/batch`

**验收**:
- `jobs.user_flag='interested'` / `'rejected'` 入库
- 🌟 岗位进入 match 候选

**坑**:批量操作用主键 `id` 非 `job_id`(否则同名行串台)

---

## 阶段 3:精排(match + enrich)

**测试点**:enrich 按需抓 JD / match v4-gap-grading / 二次意见仲裁 / feedback 校准

**步骤**:
```bash
job-agent pipeline --stages search,filter,enrich,match --keyword Python
job-agent rematch <job_id>          # 单岗位重跑
job-agent rematch --all-since 2026-07-01   # 批量重跑
```
dashboard: 🎯Agent智能匹配结果 tab → 点"运行匹配"

**验收**:
- `match_results` 表有 `raw_score` / `gaps` / `severity` / `reasoning`
- raw_score≥85 触发二次意见(差>10 跑第三次取中位数)
- dashboard 匹配 tab 显示分数+缺口(🔴🟡🟢)

**坑**:
- `match_flagged_only` 默认只 enrich user_flag='interested' 的
- match.py 返回 `raw_score` 键(非 `score`,cli.rematch 已修)
- CONCURRENCY=5,JD_MAX_CHARS=3000

---

## 阶段 4:简历定制(tailor)

**测试点**:反幻觉双通道 / extract_hard_facts / verify_facts

**步骤**:
```bash
job-agent tailor <job_id>            # -y 跳确认
```
dashboard: 📝材料审核台 → 生成 → 确认

**验收**:
- `output/{公司}_{职位}.md` + `.docx` 落盘(confirm 时)
- `generated_files` 表 catalog(TYPE_TAILORED_RESUME)
- 硬事实(日期/数字)校验通过

**坑**:
- TAILOR_TEMPERATURE=0.1
- 材料审核台 generate 只存 `material_drafts` 草稿不落盘,confirm 才写文件
- confirm 自动建 application(待投递)

---

## 阶段 5:HR 消息(cover_letter)

**测试点**:150-200 字 / 复用 tailor 硬事实

**步骤**:
```bash
job-agent cover-letter <job_id>
```
dashboard: 材料审核台 → 生成 HR 消息

**验收**:
- `output/{公司}_{职位}_hrmsg.md`,150-200 字
- catalog(TYPE_COVER_LETTER)

---

## 阶段 6:面试准备 + 模拟面试

**测试点**:题库预测(11 轮+项目深挖+反问) / 模拟面试 SSE / 5 维评估 / 实时语音 WS

**步骤**:
```bash
job-agent interview-prep <job_id> --refresh      # 生成面试题(有缓存)
job-agent mock-interview <job_id> --from-prep --difficulty medium
```
dashboard: 🎤模拟面试 tab → 选岗位 → 开始面试(文字/实时语音)

**验收**:
- `output/{公司}_{职位}_interview.md` + `.json`(generate 时落盘)
- 模拟面试结束(Dashboard 文字):`_mock_interview.md` + `_assessment.txt`(5 维评分);终端路径为 `_assessment.json`
- SSE 流式回复(`/api/mock-interview/reply`,Fetch body reader 非 EventSource)

**坑**:
- `_mock_sessions` 内存 LRU cap 50
- 只有唯一结束语「以下是您的表现评估」才判结束;题库未问完时即使 LLM 提前结束也会强制继续
- `focus` 是题库过滤器,命中 0 题时 `/api/mock-interview/start` 返回 `ok:false`
- 实时语音模式需 Chrome + 麦克风权限;WS 代理在 8766,随 Dashboard 启动
- 「清空」按钮在有活动会话时先确认,确认后调 `/api/mock-interview/abandon`(文字) 或 WS `{type:abandon}`(语音),不落盘

---

## 阶段 7:Offer 评估

**测试点**:文件驱动 / 17 字段解析 / 8 维评分 / 对比 / 缓存预览

**步骤**:
- dashboard 📄文件上传 tab → 下载 Offer导入模板 → 填写 → 📤文件上传(自动识别含"公司:"+"职位:"的 .txt 为 Offer)
- 💼Offer评估 tab → 评估 / 预览评估结果 / 勾选≥2对比 / 批量评估 / 批量删除
- CLI:`job-agent offer-eval --company 字节 --title 后端 --salary 25k*16`

**验收**:
- `offer_evaluations` 表缓存(parsed_fields/eval_input/result)
- `output/{公司}_offer_eval.md` + 对比报告
- 预览免 LLM(读缓存)
- 表格内容居中,刷新按钮↻旋转动画

**坑**:
- evaluate() 零改动策略:17 字段 fold 进 notes
- preview 读 offer_evaluations 缓存,免重跑 LLM

---

## 阶段 8:薪资谈判

**测试点**:结构化 Offer / 底线 / 谈判对象 / 锚定可视化 / 导入已评估 Offer

**步骤**:
- dashboard 💰薪资谈判 tab → 填公司/职位/月薪base/月数(自动算年包)/目标/底线/谈判对象
- 或"📥导入已评估Offer"选一个 → 自动填字段
- 点"生成建议" → 锚点/杠杆/让步/话术(📋一键复制)
- 保存策略 → `output/{公司}_salary_advice.md`
- CLI:`job-agent salary-advice --company 字节 --salary 25k*16`

**验收**:
- `output/{公司}_salary_advice.md`,含底线/谈判对象
- catalog(TYPE_SALARY_ADVICE)
- 历史记录(localStorage)显示"公司·职位"(非"未命名")
- 锚定薪资对比条(底线/当前/目标,填了结构化才显示)

**坑**:
- thinking 模式 reasoning+content 共享 max_tokens,太小致 content 空(加大优于关 thinking)
- 生成时结果区半透明遮罩 + 按钮spinner

---

## 阶段 9:投递追踪(tracking)

**测试点**:7 阶段状态机 / timeline / 提醒

**步骤**:
```bash
job-agent track add <url>           # URL -> md5[:16] job_id
job-agent track list
job-agent track show <id>
job-agent track update <id> --status 一面
```
dashboard: 📅投递追踪 tab → 更新状态

**验收**:
- `applications` 表 + `timelines` 表
- 状态流:待投递 → 已投递 → HR已读 → 约面 → 一面 → 二面 → Offer → 入职(已终止=终态)

**坑**:
- 批量更新用自增 `id` 做 WHERE 非 `job_id`(v10 给 job_id 加 UNIQUE 修复)
- `待投递` 是 dashboard-only 初始态,CLI track update 已支持(2026-07-21 修)

---

## 阶段 10:定时搜索(scheduler)

**测试点**:PID 锁 daemon / catch-up / 提醒

**步骤**:
```bash
job-agent schedule on               # 启 daemon
job-agent schedule status
job-agent schedule run              # 立即跑一次
job-agent schedule off
```

**验收**:
- `data/scheduler.lock` PID 锁,dashboard 重启不死
- `data/scheduler_state.json`(reminder_days)
- catch-up(>1.5×interval 触发)

**坑(已修复)**:scheduler 实际 OFF(state 仅 `{"reminder_days":4}`) —— 2026-08-16 起投递提醒已改为 Dashboard 后台线程每 60 分钟独立检查，不依赖 scheduler

---

## Dashboard 集成测试(10 tab)

逐 tab 验证(serve 运行在 8765):

| tab | 验证点 |
|---|---|
| 📄文件上传 | 上传按钮自动分流 offer/resume;刷新↻动画;批量删除 |
| 📋人工初筛 | 🌟/❌标记;批量;排序;分页 |
| 🎯匹配结果 | 分数+缺口;min_score 过滤;feedback |
| 📝材料审核台 | generate(草稿)→ confirm(落盘);regenerate |
| 📅投递追踪 | 状态更新;timeline;提醒 |
| 🎤模拟面试 | 文字/语音;SSE流式;5维评估 |
| 💼Offer评估 | 表格居中;评估/预览/对比/批量;刷新↻ |
| 💰薪资谈判 | 字段;导入Offer;可视化;复制;加载态 |
| 📁已生成文件 | 类型过滤;下载;zip;删除 |
| ⚙️流水线 | 进度条;漏斗;下一步;后置3卡计数;卡片序号 |

**全局**:刷新按钮统一(↻图标+点击旋转0.8s,"关闭"按钮 no-spin);tabs 移动端 flex-wrap 不溢出;favicon 🎯(console 0 error)

---

## 自动化测试

```bash
python -m pytest -q                              # 全套(2026-08-18 实测 1306 passed / 6 skipped / 0 failed)
python -m pytest -q --run-integration            # 含 Windows Toast 集成(实测 1311 passed / 1 skipped)
python -m pytest tests/test_serve.py -q          # dashboard
python -m pytest tests/test_cli.py -q            # CLI
python -m pytest tests/test_advanced.py -q       # pipeline(需 interactive=False)
python -m pytest tests/test_liepin.py tests/test_zhilian.py -q   # 平台(需 Playwright profile)
```

- 覆盖率 84.4%(fail_under=70,2026-08-18 实测)
- CI: ruff + mypy + bandit + `check_llm_naming.py` + pytest-cov
- 平台测试与全套测试均在 2026-08-16 复跑通过;若个别环境出现 Playwright profile 占用/启动失败,先关闭已开的智联浏览器再重试

---

## 已知坑速查

| 坑 | 绕过 |
|---|---|
| DeepSeek 非 Claude | 看 response model;CI 禁 glm-5.2/claude/anthropic 名 |
| 批量操作用 job_id | 改用主键 id |
| Row 无 .get() | 先 dict(row) |
| 反爬(Boss/智联) | headed 持久 profile + 只发必需 cookie |
| Windows GBK 乱码 | sys.stdout.reconfigure(utf-8),先比 codepoints |
| 子 agent 产出有 bug | 集成前对照真实签名验证 |
| Edit old_string | 逐字符 verbatim,含 emoji/中点用 Python 脚本 |
| 改 Python 后 | 清 __pycache__ + 目视验证 |
| serve background task | 易被清理,用独立终端 `python -m agent_core.server.serve` |
| 排版/CSS 改动 | 改完派子agent Playwright 视觉核查(非只看 marker) |
| 成本 | 用户已授权忽略成本警告,不中断 |

---

## 测试数据状态(当前)

- 342 岗位 / 12 感兴趣 / 330 不合适 / 12 匹配 / 3 投递（均为 HR已读）
- generated_files 21 行:tailor 6 / interview_prep 6 / cover_letter 3 / offer_eval 2 / offer_compare 1 / salary_advice 1 / mock_interview 2
- output/ 仅保留正式产物；某厂商 realtime_mock(.md + _assessment.txt)为历史实时语音记录
- 测试期间产生的临时 output(测试公司/某科技公司等)已归档到 `data/log_archive/output_test_artifacts_20260816/`,生成的 DB 索引行已同步清理
- 1 份薪资策略已保存到服务端 output/，localStorage 另存历史

**禁 push**(用户约束所有改动仅本地。2026-08-15 检查：`git remote -v` 显示 origin 已重新存在为 `https://github.com/yjxhn/job-agent-resume.git`，但继续遵守不 push 约束)
