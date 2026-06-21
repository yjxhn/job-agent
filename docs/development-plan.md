# 求职 AI Agent - 开发计划文档

> **项目基线**: 2026-06-20 | **版本**: 1.0.0
> **状态**: 生产就绪（v1） | **文档目的**: 作为项目复盘/审计基线，记录从需求收敛到架构落地的完整演进

---

## 1. 项目愿景与目标

### 1.1 核心愿景
构建一个**端到端自动化求职助手**，通过 AI 辅助从职位搜索、筛选匹配、简历定制到投递追踪的全流程，帮助求职者高效获取目标岗位 Offer。

### 1.2 成功标准

**核心指标**
- **覆盖率**: 核心模块测试覆盖 ≥ 80%
- **可用性**: 多平台并发搜索响应时间 < 30 秒（10 页结果）
- **稳定性**: 系统可用性 ≥ 95%（定期运行不崩溃）
- **成本控制**: Prescreen 阶段省 100+ LLM 调用（规则初筛 > LLM 精排）

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
| **Prescreen** | Filter 后列表 | 规则打分 + 方向选择 | Top 30 | **省 100+ LLM** |
| **Match** | Top 30 | LLM 精排（并发 5） | 匹配度排序 | 按需 LLM |
| **Tailor** | Top 匹配岗位 | 简历定制（.docx + .md） | 定制简历 | 按需 LLM |
| **Apply** | 定制简历 | （用户手动投递） | 外部投递记录 | 无 |
| **Track** | 投递记录 | 7 阶段状态机 + 时间线 | 追踪看板 | 无 |

#### 2.1.2 功能特性

**搜索与发现**
- 多平台并发搜索（Boss 直聘/猎聘/前程无忧/智联/前程无忧）
- 跨平台去重（fuzzy 75% 模糊匹配）
- 按方向筛选（industrial_ai_agent / equipment_amr）
- 按平台筛选

**初筛与精排**
- 规则初筛（薪资下限、排除词、方向匹配）
- LLM 精排（match_min_score 阈值过滤）
- 匹配度打分（0-100 分）

**简历与求职信**
- 定制简历生成（.docx + .md）
- 求职信生成（基于岗位描述）
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
- 支持断点续跑（prescreen/match 阶段可中断后恢复）
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
pipeline --stages search,filter,prescreen,match
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
│   ├── prescreen.py         # 规则初筛（成本控制）
│   ├── match.py             # LLM 精排
│   ├── tailor.py            # 简历定制
│   ├── cover_letter.py      # 求职信
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
Prescreen 初筛（规则打分）
    ↓（取 Top 30）
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
1. **Prescreen**: 方向匹配规则打分（无 LLM，规则引擎）
2. **Match**: LLM 精排（并发 5，JSON 强制 + 重试）
3. **Tailor**: 简历定制（.docx + .md 生成）
4. **Cover Letter**: 求职信生成
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
- ✅ Search + Filter + Prescreen + Match Pipeline
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
- 🔄 Prescreen 规则配置化
- 🔄 DB 迁移脚本优化
- 🔄 rate_limit_seconds 实际生效

**验收标准**
- [ ] 测试覆盖率 > 75%
- [ ] login 不依赖 Playwright
- [ ] Prescreen 规则可配置

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

## 6. 当前状态 (Actual)

| 模块/功能 | 状态 | 说明 |
|----------|------|------|
| **7 阶段 Pipeline** | | |
| Search | ⚠️ | Boss/猎聘 HTTP API 可用,但 job51/zhilian/maimai 三平台存根未实现 |
| Filter | ✅ | 薪资/地点/排除词过滤完整 |
| Prescreen | ✅ | 规则初筛 + Top 30,但规则硬编码未配置化 |
| Match | ✅ | LLM 精排 + 并发5 + JSON强制重试 + min_score |
| Tailor | ✅ | 简历定制(.docx + .md) |
| Cover Letter | ✅ | 求职信生成 |
| Interview Prep | ✅ | 技术题预测 |
| Offer Eval | ✅ | Offer 打分卡 |
| Salary Advice | ✅ | 薪资对比建议 |
| Track | ✅ | 7阶段状态机 + timelines + 手动补录 |
| Apply | ❌ | 依赖用户手动投递,无自动投递接口 |
| **平台适配器** | | |
| boss_zhipin | ⚠️ | HTTP API 可用,但有 code-37 反爬隐患 |
| liepin | ✅ | HTTP API 稳定无反爬 |
| job51 | ❌ | NotImplementedError 存根 |
| zhilian | ❌ | NotImplementedError 存根 |
| maimai | ❌ | NotImplementedError 存根 |
| **基础设施** | | |
| CLI 命令 | ⚠️ | 14 个命令完整,但 login 仍依赖 Playwright |
| 测试 | ⚠️ | 115 pytest,但缺 .coveragerc,75% 覆盖率无佐证 |
| DB | ⚠️ | 6 表可用,但 schema 迁移用 try-except,脆弱 |
| Dashboard (serve.py) | ⚠️ | Flask 可用,但缺 API 文档/错误处理 |
| Scheduler | ✅ | cron 调度完整 |
| CI/CD | ❌ | 无 |
| **数据模型** | | |
| JobRecord | ✅ | Pydantic 模型完整 |
| ApplicationRecord | ✅ | 7阶段状态机完整 |
| 数据库表 | ✅ | 6张表设计完整 |
| **调度与监控** | | |
| 定时搜岗 | ✅ | Scheduler daemon 循环完整 |
| 安静时段 | ✅ | quiet_hours 配置完整 |
| Toast 通知 | ✅ | Windows Toast 通知完整 |
| Dashboard | ⚠️ | Flask 可用,但功能简陋 |
| **文档与配置** | | |
| CLI 帮助 | ✅ | 14条命令帮助文档完整 |
| 配置文件 | ⚠️ | config.yaml 存在,但部分参数未使用 |
| .coveragerc | ❌ | 不存在,覆盖率无佐证 |
| CI/CD | ❌ | 无 |

### 6.2 代码规模

- **文件数**: 39 个 Python 文件
- **代码行数**: ~2355 行
- **函数数量**: 55 个函数
- **测试数量**: 115 个 pytest 测试

### 6.3 技术债务

**🔴 高优先级**
1. ❌ **login 命令依赖 Playwright**（应改 import-cookies）
2. ❌ **3 个平台存根未实现**（job51/zhilian/maimai）
3. ❌ **Prescreen 规则硬编码**（应配置化）

**🟡 中优先级**
4. ⚠️ **.coveragerc 不存在**（覆盖率无佐证）
5. ⚠️ **DB 迁移用 try-except**（脆弱，应规范迁移脚本）
6. ⚠️ **rate_limit_seconds 配置未实际使用**

**🟢 低优先级**
7. ℹ️ **无 CI/CD**（可选，非核心需求）
8. ℹ️ **日志可更规范**（使用 logging 模块替代部分 print）

---

## 7. 待办与风险

### 7.1 Backlog

**P0 - 阻塞上线**
1. **login 命令重构**（移除 Playwright 依赖）
   - 实现 `import-cookies` CLI 命令
   - 兼容旧登录方式（向后兼容）
   - 验证时间：2 天

2. **Prescreen 规则配置化**
   - 将硬编码规则迁移到 config.yaml
   - 支持动态调整权重
   - 验证时间：1 天

**P1 - 核心功能**
3. **实现 3 个平台适配器**
   - job51：HTTP API 研究与实现
   - zhilian：HTTP API 研究与实现
   - maimai：HTTP API 研究与实现
   - 验证时间：5 天（每个平台 1-2 天）

**P2 - 质量保障**
4. **添加 .coveragerc**
   - 配置 75% 覆盖率基准
   - CI 集成覆盖率检查
   - 验证时间：0.5 天

5. **优化 DB 迁移脚本**
   - 使用 Alembic 或类似工具
   - 提供迁移历史追踪
   - 验证时间：1 天

6. **修复 rate_limit_seconds 实际生效**
   - 在 HTTP API 调用间添加延时
   - 支持动态限流
   - 验证时间：1 天

**P3 - 体验优化**
7. **添加 CI/CD**
   - GitHub Actions（lint + test + coverage）
   - Pre-commit hooks（black/ruff）
   - 验证时间：2 天

8. **规范日志系统**
   - 使用 logging 模块替代 print
   - 日志分级（DEBUG/INFO/WARNING/ERROR）
   - 验证时间：1 天

### 7.2 已知风险

**🔴 高风险**
1. **Boss 直聘 code-37 反爬**
   - **问题**: `__zp_stoken__` 短效 Cookie，频繁调用触发反爬
   - **影响**: 搜索中断，需重新导出 Cookie
   - **缓解**: 降低搜索频率，监控 Toast 通知
   - **长期方案**: 研究 API 签名机制

2. **DeepSeek API 限流**
   - **问题**: 并发 5 LLM 调用可能触发限流
   - **影响**: Match 阶段失败率上升
   - **缓解**: 实现指数退避重试

**🟡 中风险**
3. **Cookie 过期未检测**
   - **问题**: Cookie 过期后静默失败
   - **影响**: 用户无感知，搜索无结果
   - **缓解**: 实现登录状态自动检测

4. **并发安全**
   - **问题**: 多进程同时访问数据库可能冲突
   - **影响**: 数据不一致
   - **缓解**: 使用 SQLite WAL 模式

**🟢 低风险**
5. **测试覆盖率波动**
   - **问题**: 代码重构可能导致覆盖率下降
   - **影响**: 无法准确量化质量
   - **缓解**: 每次提交前运行 pytest --cov

---

## 8. 验收标准

### 8.1 核心功能验收

**Search + Filter + Prescreen + Match**
- [ ] 运行 `pipeline --stages search,filter,prescreen,match` 成功
- [ ] 生成 30 个匹配岗位（prescreen_top_n）
- [ ] Match 阶段返回 0-100 匹配度
- [ ] 匹配度 < match_min_score（默认 50）的岗位被过滤

**Tailor + Cover Letter**
- [ ] 运行 `tailor <job-id>` 生成 .docx 文件
- [ ] 运行 `cover-letter <job-id>` 生成求职信
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
- [ ] Prescreen 阶段 LLM 调用 < 5 次（Top 30 精排）

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
job-agent search                     # 搜索所有方向
job-agent pipeline --stages all      # 完整 Pipeline
job-agent pipeline --stages search,filter  # 仅搜索+筛选
job-agent match <job-id>             # 单个岗位匹配度
```

**简历与求职信**
```bash
job-agent tailor <job-id>            # 定制简历
job-agent cover-letter <job-id>      # 求职信
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
- `prescreen_top_n`: 初筛后保留数量（默认 30）
- `match_min_score`: 精排阈值（默认 50）

**llm**（LLM 配置）
- `provider`: 提供商（deepseek）
- `model`: 模型名称（deepseek-v4-pro）
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

---

**文档结束**

**最后更新**: 2026-06-20
**维护者**: AI Assistant
**反馈渠道**: 提交 Issue 到项目仓库
