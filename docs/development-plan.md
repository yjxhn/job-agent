# 求职 AI Agent - 开发计划文档

> **项目基线**: 2026-06-20 | **版本**: 1.0.0
> **状态**: 生产就绪（v1） | **文档目的**: 作为项目复盘/审计基线，记录从需求收敛到架构落地的完整演进

---

> ⚠️ **本文档已归档（2026-07-24）**
>
> 本文档为 **2026-06-25 历史基线快照**，多处内容与代码现状严重漂移。以下为最关键漂移项，权威状态以仓库内 `README.md`、`docs/ARCHITECTURE.md` 及实际代码为准：
>
> | 项目 | 文档记录 (2026-06-25) | 现状 (2026-07-24) |
> |------|----------------------|-------------------|
> | DB Schema | v2，6 张业务表 | **v12**，**12 张业务表**（v11 offer_evaluations / v12 material_drafts 面试准备列） |
> | CLI 命令 | 14 条 | **17 条** |
> | 生产可用平台 | 2-5 个 | **8 个 live**（boss_zhipin/liepin/zhilian/tencent/netease/byd/naura/yofc） |
> | Web Server | Flask | **Python stdlib `http.server.ThreadingHTTPServer`**（端口 8765） |
> | Dashboard Tab | 7 个 | **10 个** |
> | LLM Module | `deepseek.py` | **`llm/providers.py`**（deepseek-v4-flash 经 api.deepseek.com） |


## 1. 项目愿景与目标

### 1.1 核心愿景
构建一个**端到端自动化求职助手**，通过 AI 辅助从职位搜索、筛选匹配、简历定制到投递追踪的全流程，帮助求职者高效获取目标岗位 Offer。

### 1.2 成功标准

**核心指标**
- **覆盖率**: 核心模块测试覆盖 ≥ 80%
- **可用性**: 多平台并发搜索响应时间 < 30 秒（10 页结果）
- **稳定性**: 系统可用性 ≥ 95%（定期运行不崩溃）
- **成本控制**: 人工筛选阶段省 100+ LLM 调用（用户标记 > LLM 精排）

**用户价值**
- 自动化 80% 求职流程，减少人工筛选 90%
- 跨平台去重（模糊匹配 75%）避免重复投递
- 精排匹配（match_min_score 阈值过滤低质量岗位）
- 简历定制化（.docx + .md 自动生成）

---

## 2. 需求规格 (PRD)

### 2.1 功能需求

#### 2.1.1 核心工作流（7 阶段 Pipeline）

| 阶段 | 输入 | 处理 | 输出 | 成本控制 |
|------|------|------|------|----------|
| **Search** | 关键词 + 平台配置 | 多平台 HTTP API 并发搜索（Boss/猎聘） | 职位列表 | 无 |
| **Filter** | Search 结果 | 薪资/地点/排除词过滤 | 筛选后列表 | 无 |
| **Match** | 用户标记的岗位 | LLM 精排（并发 5） | 匹配度排序 | 按需 LLM |
| **Tailor** | Top 匹配岗位 | 简历定制（.docx + .md） | 定制简历 | 按需 LLM |
| **Apply** | 定制简历 | （用户手动投递） | 外部投递记录 | 无 |
| **Track** | 投递记录 | 7 阶段状态机 + 时间线 | 追踪看板 | 无 |

#### 2.1.2 功能特性

**搜索与发现**
- 多平台并发搜索（Boss 直聘/猎聘/前程无忧/智联/前程无忧）
- 跨平台去重（fuzzy 75% 模糊匹配）
- 按方向筛选（industrial_ai_agent / equipment_amr）
- 按平台筛选

**筛与精排**
- 人工筛选（用户在 Dashboard 标记 🌟想投递 / ❌不合适）
- LLM 精排（match_min_score 阈值过滤）
- 匹配度打分（0-100 分）

**简历与HR打招呼消息**
- 定制简历生成（.docx + .md）
- HR打招呼消息生成（基于岗位描述）
- 岗位链接自动打开

**投递追踪**
- 7 阶段状态机（已投递 → HR已读 → 约面 → 一面 → 二面 → Offer → 入职）
- 时间线审计表
- 手动补录外部投递

**面试准备**
- 技术题预测
- 行为题预测
- 项目深挖预测
- 模拟面试（终端交互式）

**Offer 评估**
- 薪资对比建议
- 公司对比分析
- Offer 打分卡

**调度与监控**
- 定时搜岗（interval_hours 可配）
- 安静时段（quiet_hours 避免 0-7 点打扰）
- Windows Toast 通知
- Dashboard 本地看板

#### 2.1.3 非功能需求

**性能**
- Search 阶段并发搜索 2 平台 < 30 秒
- Match 阶段并发 5 LLM 调用 < 10 秒
- 简历定制生成 < 5 秒

**稳定性**
- 系统可用性 ≥ 95%
- 支持断点续跑（match 阶段可中断后恢复）
- 错误重试机制（LLM 调用失败重试 3 次）

**可维护性**
- 模块化 Pipeline（每阶段独立，支持组合）
- 统一 Job 模型（Pydantic + 别名表）
- 日志完整（data/agent.log）

**安全性**
- Cookie 加密存储（data/cookies/*.json）
- API Key 环境变量隔离
- 不暴露真实 Cookie 到日志

**可扩展性**
- 平台适配器抽象（BaseAdapter）
- 新平台接入 < 2 小时（实现 get_jobs 方法）
- 新方向接入 < 30 分钟（配置 + 简历模板）

### 2.2 用户场景

**场景 1: 全流程自动求职**
1. 配置 Cookie（首次）
2. 运行 `pipeline --stages all`
3. 查看匹配结果，选择高匹配岗位
4. 定制简历，手动投递
5. 运行 `track add` 记录投递
6. 定时搜岗（`schedule on`）

**场景 2: 仅搜索与匹配**
```bash
pipeline --stages search,filter,match
```
不生成简历，仅发现高匹配岗位。

**场景 3: 简历更新后重新匹配**
```bash
rematch --all-since 2026-06-01
```

**场景 4: 外部投递补录**
```bash
track add https://www.zhipin.com/job_detail/xxx.html
```

---

## 3. 系统架构

### 3.1 模块划分

```
agent_core/
├── cli.py                    # Typer CLI 入口（14 条命令）
├── config.py                 # 配置加载
├── llm/                      # LLM 抽象层
│   ├── __init__.py
│   └── deepseek.py          # DeepSeek 集成
├── pipeline/                 # 核心 Pipeline（7 阶段）
│   ├── __init__.py
│   ├── search.py            # 多平台并发搜索
│   ├── filter.py            # 薪资/地点/排除词过滤
│   ├── match.py              # LLM 精排
│   ├── match.py             # LLM 精排
│   ├── tailor.py            # 简历定制
│   ├── cover_letter.py      # HR打招呼消息
│   ├── interview_prep.py    # 面试准备
│   ├── offer_eval.py        # Offer 评估
│   └── salary_advice.py     # 薪资建议
├── platforms/                # 平台适配器（5 个平台）
│   ├── __init__.py
│   ├── base.py              # 平台抽象
│   ├── boss_zhipin.py       # Boss 直聘（HTTP API）
│   ├── liepin.py            # 猎聘（HTTP API）
│   ├── job51.py             # 前程无忧（存根）
│   ├── zhilian.py           # 智联招聘（存根）
│   ├── maimai.py            # 猎聘存根
│   ├── company_site.py      # 企业官网（存根）
│   ├── enrichment.py        # 职位 enrich
│   └── cookie_utils.py      # Cookie 导入工具
├── storage/                  # 数据存储层
│   ├── __init__.py
│   ├── db.py                # SQLite 封装
│   └── models.py            # 数据模型
├── tracking/                 # 投递追踪
│   ├── __init__.py
│   └── tracker.py           # 7 阶段状态机
├── scheduler/                # 定时调度
│   ├── __init__.py
│   └── scheduler.py         # daemon 循环
└── server/                   # Dashboard
    ├── __init__.py
    └── server.py            # Flask 本地看板
```

### 3.2 数据流

```
配置加载（config.yaml）
    ↓
搜索阶段（search.py）
    ↓（并发 2 平台）
Filter 过滤
    ↓
用户标记 🌟（Dashboard 人工筛选）
    ↓
Match 精排（LLM 并发 5）
    ↓（匹配度过滤）
存入数据库
    ↓
用户选择岗位
    ↓
Tailor 定制简历（LLM）
    ↓
手动投递 → Track 记录
```

### 3.3 数据模型

**统一 Job 模型**（Pydantic）
```python
class Job(BaseModel):
    id: str                     # 唯一 ID（跨平台去重）
    title: str                  # 岗位标题
    company: str                # 公司名称
    company_normalized: str      # 标准化公司名（别名匹配）
    location: str               # 工作地点
    salary_min: int | None      # 最低薪资
    salary_max: int | None      # 最高薪资
    description: str            # 岗位描述（JD）
    platforms: list[str]        # 来源平台列表
    urls: dict[str, str]        # 各平台详情 URL
    direction: str              # 匹配方向
    first_seen: str             # 首次发现时间
    last_seen: str              # 最后更新时间
    is_new: bool                # 是否新岗位
    security_id: str            # 去重指纹
    lid: str                    # 平台原始 ID
```

**数据库表结构（6 表）**

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| jobs | 职位主表 | id, title, company, direction, is_new, first_seen, last_seen |
| applications | 投递记录表 | id, job_id, status, applied_at, updated_at, notes |
| user_preferences | 用户配置 | direction, exclude_keywords, min_salary |
| platform_cookies | Cookie 管理 | platform, cookie_json, expires_at |
| tracking_timelines | 时间线审计 | application_id, event_type, timestamp, description |
| application_scores | 匹配度记录 | application_id, match_score, match_reasons |

### 3.4 LLM 集成

**提供商**: DeepSeek（通过 DEEPSEEK_API_KEY 环境变量）

**调用场景**
1. **Match**: LLM 精排（并发 5，JSON 强制 + 重试）
2. **Tailor**: 简历定制（.docx + .md 生成）
4. **Cover Letter**: HR打招呼消息生成
5. **Interview Prep**: 技术题预测
6. **Offer Eval**: Offer 打分卡
7. **Salary Advice**: 薪资建议

**Prompt 模板**
```python
MATCHING_PROMPT = """
你是一个专业的职业匹配助手。请评估以下岗位与我的简历的匹配度（0-100分）：
- 岗位：{title} @ {company}
- 地点：{location}
- 薪资：{salary_range}
- 描述：{description}

简历方向：{direction}
关键词：{keywords}
特色词：{feature_words}

请以 JSON 格式返回：
{{
  "score": 0-100,
  "reasons": ["理由1", "理由2", ...],
  "missing_skills": ["缺失技能", ...]
}}
"""
```

### 3.5 平台适配器抽象

**接口定义**（BaseAdapter）
```python
class PlatformAdapter(ABC):
    @abstractmethod
    def get_jobs(self, keywords: list[str], location: str) -> list[Job]:
        """获取职位列表"""
        pass

    @abstractmethod
    def login(self) -> bool:
        """登录验证"""
        pass

    @abstractmethod
    def refresh_cookies(self) -> bool:
        """刷新 Cookie"""
        pass
```

**实现现状**
- ✅ **Boss 直聘**: HTTP API + Cookie，可用（有 code-37 反爬隐患）
- ✅ **猎聘**: HTTP API + Cookie，可用（最稳定，无反爬）
- ❌ **前程无忧**: 存根（NotImplementedError）
- ❌ **智联招聘**: 存根（NotImplementedError）
- ❌ **猎聘企业版**: 存根（NotImplementedError）

---

## 4. 技术选型

### 4.1 核心技术栈

| 类别 | 技术 | 选择理由 |
|------|------|----------|
| **语言** | Python 3.10+ | 生态丰富，LLM 工具库多，开发效率高 |
| **数据模型** | Pydantic v2 | 类型安全，验证便利，JSON 序列化内置 |
| **CLI** | Typer | 现代化 CLI 框架，类型提示友好 |
| **测试** | pytest + pytest-cov | 业界标准，覆盖报告直观 |
| **数据库** | SQLite | 零配置，轻量级，适合单机应用 |
| **Web** | Flask | 简单快速，Dashboard 需求小 |
| **LLM** | DeepSeek | 成本低，API 稳定，适合批量调用 |
| **文档生成** | python-docx | .docx 格式支持完善 |

### 4.2 不选其他方案的原因

**为什么不迁移到 FastAPI/Next.js?**
- 当前是本地 CLI 工具，无需分布式
- Flask 足够轻量，启动快（< 1 秒）
- 避免过度工程化

**为什么不迁移到 TypeScript?**
- Python LLM 生态更成熟（LangChain, LlamaIndex）
- 需求不涉及前端复杂交互
- 避免维护双语言代码

**为什么不迁移到 PostgreSQL?**
- 单机应用，SQLite 性能足够
- 零运维成本
- 数据文件易于迁移和备份

---

## 5. 实施路线图

### 5.1 阶段划分（按时间反推）

#### **Phase 1: MVP 基础架构**（已完成）
**目标**: 实现 7 阶段 Pipeline 核心流程

**交付物**
- ✅ Pydantic Job 模型
- ✅ SQLite 数据库封装
- ✅ CLI 入口（14 条命令）
- ✅ Search + Filter + Match Pipeline
- ✅ Tailor + Cover Letter（基础版）

**验收标准**
- [ ] 7 阶段 Pipeline 正常运行
- [ ] 数据模型完整存储到数据库
- [ ] CLI 命令可执行无报错

**时间**: 2 周

---

#### **Phase 2: 多平台集成**（已完成）
**目标**: 集成 Boss 直聘和猎聘（HTTP API 替代 Playwright）

**交付物**
- ✅ BossZhipinAdapter（HTTP API + Cookie）
- ✅ LiepinAdapter（HTTP API + Cookie）
- ✅ Cross-platform deduplication（fuzzy 75%）
- ✅ Playwright 登录迁移到 import-cookies

**验收标准**
- [ ] Boss 直聘可搜索（无 Playwright）
- [ ] 猎聘可搜索（无 Playwright）
- [ ] 跨平台去重生效

**时间**: 1.5 周

---

#### **Phase 3: 测试与审计**（已完成）
**目标**: 达到 80% 覆盖率，通过安全审计

**交付物**
- ✅ pytest 测试套件（115 个测试）
- ✅ .coveragerc 配置
- ✅ 安全扫描（bandit）
- ✅ 四轮审计修复（详见 JOB_AGENT_RETROSPECTIVE.md）

**验收标准**
- [ ] 测试覆盖率 ≥ 80%
- [ ] 所有审计问题已修复
- [ ] bandit 无高危漏洞

**时间**: 2 周

---

#### **Phase 4: 追踪与调度**（已完成）
**目标**: 实现投递追踪和定时搜岗

**交付物**
- ✅ 7 阶段状态机（applications 表）
- ✅ Timeline 审计表
- ✅ Scheduler daemon 循环
- ✅ Windows Toast 通知
- ✅ Flask Dashboard

**验收标准**
- [ ] track add/update 命令可用
- [ ] schedule on/off/run/status 可用
- [ ] Dashboard 可实时刷新

**时间**: 1.5 周

---

#### **Phase 5: 进阶功能**（部分完成）
**目标**: 面试准备、Offer 评估、薪资建议

**交付物**
- ✅ interview_prep.py
- ✅ offer_eval.py
- ✅ salary_advice.py

**验收标准**
- [ ] interview_prep 命令可用
- [ ] offer_eval 命令可用
- [ ] salary_advice 命令可用

**时间**: 1 周

---

#### **Phase 6: 优化与维护**（进行中）
**目标**: 性能优化、错误处理、文档完善

**交付物**
- 🔄 .coveragerc（覆盖率佐证）
- 🔄 login 命令重构（移除 Playwright 依赖）
- 🔄 DB 迁移脚本优化
- 🔄 rate_limit_seconds 实际生效

**验收标准**
- [ ] 测试覆盖率 > 75%
- [ ] login 不依赖 Playwright
**时间**: 1 周

---

### 5.2 里程碑

| 里程碑 | 日期 | 交付物 | 状态 |
|--------|------|--------|------|
| MVP 架构完成 | v0.1 | 7 阶段 Pipeline 基础版 | ✅ 已完成 |
| 多平台集成 | v0.5 | Boss + 猎聘 HTTP API | ✅ 已完成 |
| 测试审计通过 | v0.8 | 80% 覆盖率 + 四轮审计 | ✅ 已完成 |
| 追踪调度上线 | v1.0 | Dashboard + 定时搜岗 | ✅ 已完成 |
| 生产就绪 | v1.1 | 完整文档 + 性能优化 | 🔄 进行中 |

---

## 6. 最终状态 (Final)

> 最后更新: 2026-06-25 | **状态: 全部完成，未 commit（用户禁止 push + GitHub 仓库已删）**

### 6.1 功能完成度

| 模块/功能 | 状态 | 说明 |
|----------|------|------|
| **7 阶段 Pipeline** | | |
| Search | ✅ | **8 个平台适配器全部启用**（BOSS/猎聘/智联/腾讯/网易/比亚迪/北方华创/长飞） |
| Filter | ✅ | 薪资/地点/排除词过滤完整 |
| Review | ✅ | 用户在 Dashboard 标记 🌟想投递 / ❌不合适 |
| Match | ✅ | LLM 精排 + 并发5 + JSON强制重试 + min_score + LLM 指数退避重试 |
| Tailor | ✅ | 简历定制(.docx + .md) |
| Cover Letter | ✅ | HR打招呼消息生成 |
| Interview Prep | ✅ | 技术题/行为题/项目深挖预测 + 模拟面试 |
| Offer Eval | ✅ | Offer 打分卡 |
| Salary Advice | ✅ | 薪资对比建议 |
| Track | ✅ | 7阶段状态机 + timelines + 手动补录 |
| Apply | ❌ | 依赖用户手动投递，无自动投递接口 |
| **平台适配器** | | |
| boss_zhipin | ✅ | HTTP API + Cookie，__zp_stoken__ 需定期重抓（SOP 已写） |
| liepin | ✅ | HTTP API 稳定无反爬 |
| zhilian | ✅ | **Playwright headed 浏览器**（persistent profile，登录一次长期可用），根治 Akamai 反爬 |
| tencent | ✅ | 公开 API，careers.tencent.com |
| netease | ✅ | 公开 API，hr.163.com |
| byd | ✅ | 公开 API，job.byd.com |
| naura | ✅ | 公开 API（Beisen），北方华创 |
| yofc | ✅ | 公开 API（Beisen/zhiye.com），长飞光纤 |
| job51 | ❌ | NotImplementedError 存根，用户决定不碰 |
| maimai | ❌ | NotImplementedError 存根，用户决定不碰 |
| **对话模式** | | |
| job-agent chat | ✅ | DeepSeek function-calling，自然语言→11工具自动调用→中文回复 |
| **基础设施** | | |
| CLI 命令 | ✅ | 14 命令 + `job-agent chat` 对话 REPL |
| 测试 | ✅ | **429 passed / 6 skipped / 0 fail**，覆盖率 **85.5%**（门槛 79） |
| DB | ✅ | SQLite WAL 模式，schema 版本化迁移（v2） |
| Dashboard | ✅ | Flask + Timeline + OpenAPI + 认证 + 分页 完整 |
| Scheduler | ✅ | cron 调度 + quiet_hours 完整 |
| CI/CD | ✅ | ruff/mypy/bandit 全 0，GitHub Actions 就绪（历史记录“已删远程仓库”；2026-08-15 检查 origin 已重新存在，但仍不 push） |
| **数据模型** | | |
| JobRecord | ✅ | Pydantic 模型完整 |
| ApplicationRecord | ✅ | 7阶段状态机完整 |
| 数据库表 | ✅ | 6 张表 + schema_version 迁移追踪 |
| **调度与监控** | | |
| 定时搜岗 | ✅ | Scheduler daemon 循环完整 |
| 安静时段 | ✅ | quiet_hours 配置完整 |
| Toast 通知 | ✅ | Windows Toast 通知完整 |
| Cookie 健康检查 | ✅ | `check-cookies` 命令 + 重抓 SOP |
| **代码质量** | | |
| ruff | ✅ | 0 问题 |
| mypy | ✅ | 0 错误（63 文件） |
| bandit | ✅ | 0 issues（0H/0M/0L） |

### 6.2 代码规模

- **文件数**: 46 个 Python 文件（含 zhilian_browser.py、chat 模块、agent/ tools.py+repl.py）
- **测试数量**: **429 个 pytest 测试**（6 skipped 为需 --run-integration 的集成测试）
- **覆盖率**: **85.5%**（fail_under=79，超阈值 6.5%）
- **LLM**: DeepSeek v4-pro，openai SDK + function-calling，指数退避重试
- **数据库**: SQLite WAL 模式，6 表 + schema 版本化迁移（v2）

### 6.3 平台维护负担分级

| 等级 | 平台 | 维护方式 |
|------|------|----------|
| 零维护 | tencent, netease, byd, naura, yofc | 公开 API，无认证 |
| 零维护（浏览器） | zhilian | Playwright headed + persistent profile，登录一次长期可用 |
| 低维护 | liepin | Cookie 稳定，长期有效 |
| 需定期重抓 | boss_zhipin | `__zp_stoken__` 短效（几小时~天），SOP 已写 |

### 6.4 技术债务

**🟡 中优先级**
1. ⚠️ **BOSS `__zp_stoken__` 定期过期**（SOP 已写，需用户手动重抓）
2. ⚠️ **行业适配器 backlog**：半导体/新能源/制药 12 家需 JS 逆向或无 API（已调研，见 `docs/research/`）

**🟢 低优先级**
3. ℹ️ **job51/maimai 存根**（用户决定当前不实现）

---

## 7. 已完成清单

> 以下所有 P0-P3 项在 2026-06-25 前全部落地。不再区分"待办/风险"，改为"已完成"记录。

**P0 - 全部完成**
1. ✅ login 命令重构（移除 Playwright 依赖，改为 import-cookies）
2. ✅ 人工筛选（Dashboard 用户标记）
3. ✅ 覆盖率配置（fail_under=79，实测 85.5%）
4. ✅ DB 迁移脚本优化（schema 版本化迁移）
5. ✅ rate_limit_seconds 实际生效（所有 adapter 已用）
6. ✅ CI/CD（Pre-commit + ruff/mypy/bandit + GitHub Actions；2026-08-15 订正：origin 当前存在，仍不 push）
7. ✅ 日志系统（logging 模块替代 print）
8. ✅ LLM 指数退避重试（call_llm_with_retry）
9. ✅ SQLite WAL 模式

**P1 - 全部完成**
10. ✅ 平台适配器：8 源全通（含 BYD/NAURA/YOFC）+ 5 公开 API 零维护
11. ✅ 智联反爬根治：Playwright headed 浏览器，登录一次长期可用
12. ✅ 对话模式：`job-agent chat`，DeepSeek function-calling

**P2 - 全部完成**
13. ✅ CI 就绪（GitHub Actions workflow，用户禁止 push 故未推送远程）
14. ✅ Cookie 健康检查（check-cookies + 重抓 SOP）
15. ✅ 覆盖率 85.5%（超阈值 6.5%）

**P3 - 按计划不实现**
16. ℹ️ job51/maimai 存根（用户决定不碰）

### 7.2 已缓解风险

| 风险 | 缓解措施 | 状态 |
|------|----------|------|
| BOSS code-37 反爬 | SOP 已写，Toast 通知，rate_limit_seconds | ✅ 已缓解 |
| DeepSeek API 限流 | 指数退避重试 | ✅ 已解决 |
| Cookie 过期未检测 | cookie_health.py + check-cookies 命令 | ✅ 已解决 |
| 并发安全 | SQLite WAL 模式 | ✅ 已解决 |
| 智联 Akamai 反爬 | Playwright headed 浏览器 | ✅ 已根治 |

---

## 8. 验收标准

### 8.1 核心功能验收

**Search + Filter + Match**
- [ ] 运行 `pipeline --stages search,filter,match` 成功
- [ ] Match 阶段返回 0-100 匹配度
- [ ] 匹配度 < match_min_score（默认 50）的岗位被过滤

**Tailor + Cover Letter**
- [ ] 运行 `tailor <job-id>` 生成 .docx 文件
- [ ] 运行 `cover-letter <job-id>` 生成HR打招呼消息
- [ ] 岗位链接自动打开（系统默认浏览器）

**Track**
- [ ] 运行 `track add <job-id>` 成功记录
- [ ] 运行 `track list` 显示所有投递
- [ ] 运行 `track update <app-id> --status 二面` 成功推进状态
- [ ] Timeline 审计表正确记录时间线

**Scheduler**
- [ ] 运行 `schedule on` 成功启动 daemon
- [ ] 定时任务按 interval_hours 执行（默认 6 小时）
- [ ] 静止时段（0-7 点）不触发搜索
- [ ] Windows Toast 通知成功

**Dashboard**
- [ ] 运行 `serve` 成功启动 Flask 服务器
- [ ] 浏览器访问 http://localhost:8765 正常显示
- [ ] 搜索框实时过滤生效
- [ ] 点击列头排序生效
- [ ] 自动刷新功能正常

### 8.2 质量验收

**测试覆盖率**
- [ ] pytest --cov=agent_core --cov-report=term 显示覆盖率 > 75%
- [ ] 核心模块（pipeline, platforms, storage）覆盖率 > 80%
- [ ] 所有测试用例通过（无 flaky 测试）

**代码质量**
- [ ] black --check 无格式错误
- [ ] ruff 检查无警告
- [ ] mypy 类型检查通过
- [ ] bandit 安全扫描无高危漏洞

**文档完整性**
- [ ] README.md 完整（安装、配置、命令速查、FAQ）
- [ ] 代码注释覆盖关键逻辑
- [ ] CLI 帮助文档完整（--help 输出清晰）

### 8.3 性能验收

**搜索性能**
- [ ] 2 平台并发搜索 10 页结果 < 30 秒
- [ ] 跨平台去重后结果数 < 原始结果数（去重生效）

**LLM 调用性能**
- [ ] 5 并发 LLM 调用 < 10 秒

**简历生成性能**
- [ ] 简历定制生成 < 5 秒
- [ ] .docx 文件大小 < 2MB

---

## 9. 附录

### 9.1 CLI 命令速查

**登录与状态**
```bash
job-agent login --platform boss      # 手动登录（旧路径）
job-agent login --status             # 检查 Cookie 状态
```

**搜索与匹配**
```bash
job-agent search --keyword AMR      # 按关键词搜索（--keyword 必填）
job-agent pipeline --stages all      # 完整 Pipeline
job-agent pipeline --stages search,filter  # 仅搜索+筛选
job-agent match <job-id>             # 单个岗位匹配度
```

**简历与HR打招呼消息**
```bash
job-agent tailor <job-id>            # 定制简历
job-agent cover-letter <job-id>      # HR打招呼消息
job-agent rematch <job-id>           # 重新匹配
job-agent rematch --all-since <date> # 批量重新匹配
```

**投递追踪**
```bash
job-agent track add <job-id>         # 记录投递
job-agent track add <url>            # 手动补录
job-agent track list                 # 列表
job-agent track show <app-id>        # 详情+时间线
job-agent track update <app-id> --status <状态> # 推进
```

**面试准备**
```bash
job-agent interview-prep <job-id>    # 预测面试题
job-agent mock-interview <job-id>    # 模拟面试
```

**Offer 评估**
```bash
job-agent offer-eval --company <公司> --title <岗位> --salary <薪资>
job-agent salary-advice --company <公司> --title <岗位> --salary <当前薪资> --target <目标薪资>
```

**调度与看板**
```bash
job-agent schedule on                # 开启定时搜岗
job-agent schedule run               # 启动 daemon
job-agent schedule status            # 查看状态
job-agent schedule off               # 关闭
job-agent serve                      # 启动 Dashboard
```

**Cookie 导入**
```bash
job-agent import-cookies <路径> <平台> --domain <域名>
```

### 9.2 配置项说明

**platforms**（平台配置）
- `enabled`: 是否启用该平台
- `login_method`: 登录方式（playwright_cookie/import_cookies）
- `cookie_path`: Cookie 文件路径
- `rate_limit_seconds`: 请求间隔（秒）

**search**（搜索配置）
- `directions`: 搜索方向列表（key: 方向名, keywords: 关键词, resume_file: 简历模板）
- `location`: 工作地点
- `min_salary`: 最低薪资（元）
- `exclude_keywords`: 排除关键词列表

**matching**（匹配配置）
- `match_min_score`: 精排阈值（默认 50）

**llm**（LLM 配置）
- `provider`: 提供商（deepseek）
- `model`: 模型名称（deepseek-v4-flash）
- `api_key_env`: API Key 环境变量名
- `temperature`: 温度参数
- `max_tokens`: 最大 tokens

**schedule**（调度配置）
- `enabled`: 是否启用定时搜岗
- `interval_hours`: 执行间隔（小时）
- `directions`: 需要搜索的方向列表

---

## 10. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0.0 | 2026-06-20 | 项目基线，记录 MVP → 生产就绪完整演进 |
| v0.1.0 | 2026-05-XX | MVP 基础架构完成（7 阶段 Pipeline） |
| v0.5.0 | 2026-05-XX | 多平台集成（Boss + 猎聘 HTTP API） |
| v0.8.0 | 2026-06-XX | 测试审计通过（80% 覆盖率） |
| v1.0.0 | 2026-06-XX | 追踪调度上线（Dashboard + 定时搜岗） |
| v1.1.0 | 2026-06-20 | 生产就绪（优化与维护进行中） |
| v2.0.0 | 2026-06-25 | **最终版**：8 源全通 + chat 对话模式 + 智联 Playwright 根治 + 覆盖率 85.5% + 全部改动未 commit（用户禁止 push；2026-08-15 订正：origin 已重新存在，仍不 push） |

---

## 11. 最终备注

**全部改动留在工作区，未 commit。** 用户于 2026-06-24 禁止 git push 并删除 GitHub 远程仓库（yjxhn/job-agent-resume.git）。当前所有代码、测试、文档修改仅存在于本地工作区。

- **git remote**: 历史记录为已删除（原 `https://github.com/yjxhn/job-agent-resume.git`）；**2026-08-15 现状订正**：`git remote -v` 显示该 origin 当前存在，但继续遵守不 push 约束
- **未 commit 改动**: Batch W 全部内容（LLM 配置、CI 修复、tencent/naura bug 修复、yofc 适配器、智联 Playwright 浏览器、覆盖率补到 85.5%、chat 模式）
- **可运行状态**: 8 源全通 + 429 tests pass + 覆盖率 85.5% + LLM 可用

**文档结束**

**最后更新**: 2026-06-25
**维护者**: AI Assistant


---

## 12. 2026-07-24 订正附录

> 以下为 2026-07-24 全量读码确认的权威现状，供读者快速对齐。

### 12.1 CLI 命令（17 条）

login, rematch, search, pipeline, tailor, serve, track, cover-letter, interview-prep, mock-interview, offer-eval, salary-advice, import-cookies, check-cookies, schedule, chat, cleanup

### 12.2 平台适配器（8 live + 2 存根）

| 状态 | 平台 | 接入方式 |
|------|------|----------|
| ✅ Live | boss_zhipin | HTTP API + Cookie，`__zp_stoken__` 需定期重抓 |
| ✅ Live | liepin | HTTP API，Cookie 稳定 |
| ✅ Live | zhilian | Playwright headed 浏览器（persistent profile） |
| ✅ Live | tencent | 公开 API（careers.tencent.com） |
| ✅ Live | netease | 公开 API（hr.163.com） |
| ✅ Live | byd | 公开 API（job.byd.com） |
| ✅ Live | naura | 公开 API（Beisen），北方华创 |
| ✅ Live | yofc | 公开 API（Beisen/zhiye.com），长飞光纤 |
| ❌ 存根 | job51 | NotImplementedError |
| ❌ 存根 | maimai | NotImplementedError |

### 12.3 数据库（Schema v12，12 张业务表）

| 表名 | 用途 | 关键变更 |
|------|------|----------|
| jobs | 职位主表 | |
| applications | 投递记录 | v10 加 `job_id` UNIQUE 约束 |
| timelines | 投递时间线 | |
| match_results | 匹配结果 | |
| pipeline_runs | Pipeline 运行记录 | |
| platform_sessions | 平台会话 | |
| schedules | 定时调度 | |
| search_status | 搜索状态 | |
| generated_files | 已生成文件 | |
| match_feedback | 匹配反馈 | |
| material_drafts | 材料草稿 | |
| offer_evaluations | Offer 评估 | **v11 新增** |

（+ `schema_version` 迁移追踪表）

### 12.4 Web Server

- **`server/serve.py`**（非 `server.py`，非 Flask）
- Python stdlib `http.server.ThreadingHTTPServer`
- 端口 8765
- 含 `server/realtime_proxy.py`（豆包 SC2.0 实时语音）

### 12.5 Dashboard（10 个 Tab）

📄文件上传 | 📋人工初筛 | 🎯Agent智能匹配结果 | 📝材料审核台 | 📅投递追踪 | 🎤模拟面试 | 💼Offer评估 | 💰薪资谈判 | 📁已生成文件 | ⚙️Pipeline

### 12.6 LLM

- **Provider**: deepseek-v4-flash，经 `api.deepseek.com` openai 兼容端点（非 glm/claude）
- **模块**: `llm/providers.py`（非 `deepseek.py`），通过 `create_provider()` 初始化
- **Thinking 模式**: 开启（`ANTHROPIC_THINKING_EFFORT=max`），reasoning+content 共享 max_tokens

### 12.7 测试

- **703 个测试收集，实测 697 passed / 6 skipped / 0 failed**（2026-08-16 模拟面试 + 职位搜索专项后；历史 672/666/6 已过期）
- 覆盖率 **52.0%**（2026-08-16 实测；历史 85.5% 已过期，低覆盖集中在 server/browser 模块）

### 12.8 模块结构关键差异

| 文档引用 | 实际路径 |
|----------|----------|
| `llm/deepseek.py` | `llm/providers.py` |
| `platforms/enrichment.py` | `pipeline/enrichment.py` |
| `server/server.py` | `server/serve.py` |
| 无 | `server/realtime_proxy.py`（豆包 SC2.0 实时语音） |
| 无 | `agent/tools.py` + `agent/repl.py`（chat 模式 11 工具） |

### 12.9 配置变更

- `config.yaml` 的 `search.directions` 现仅 `default`（旧的 `industrial_ai_agent` / `equipment_amr` 固定方向已移除）
- 简历改为**用户上传**（非按方向配置固定模板）
- prescreen 阶段已于 2026-07-03 移除，当前为人工标记筛选 + LLM 精排

---

**订正基于**: 2026-07-24 全量代码审查 | **订正者**: AI Assistant
