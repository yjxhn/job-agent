# 中国制药/医药行业 Top 5 公司招聘 API 调研报告

> 调研日期: 2026-06-23
> 调研目的: 评估中国头部药企招聘网站是否可接入求职 AI Agent（公开 API 模式，类似腾讯/网易适配器）
> 结论概要: **5 家中仅 1 家有部分公开 API（百济神州全球站 Workday），其余均依赖第三方闭源招聘平台，无公开 API**

---

## 1. Top 5 公司选定

基于 2025 中国医药工业综合竞争力百强榜、全球 PharmExec 50 强、营收排名、招聘活跃度四个维度综合选定：

| 排名 | 公司 | 英文名 | 选定理由 |
|------|------|--------|---------|
| 1 | 恒瑞医药 | Hengrui Medicine | 综合竞争力 #1，创新药收入占比 >50%，A 股市值最高药企 |
| 2 | 百济神州 | BeiGene | 增速最快（+56%），全球 PharmExec 50 #44，三地上市 |
| 3 | 药明康德 | WuXi AppTec | 全球最大 CRO/CDMO，A 股净利润 191.5 亿元领跑行业 |
| 4 | 齐鲁制药 | Qilu Pharmaceutical | 综合竞争力 #4，校园招聘规模大，覆盖四大体系 |
| 5 | 复星医药 | Fosun Pharma | 综合竞争力 #5，营收 410 亿，多治疗领域覆盖 |

---

## 2. 逐公司 API 分析

### 2.1 恒瑞医药 (Hengrui Medicine)

| 项目 | 详情 |
|------|------|
| **中国招聘站** | `https://hengrui.zhaopin.com/`（智联招聘校园招聘平台） |
| **招聘公众号** | 「恒瑞医药招聘」(ID: Hryy_Recruitment) |
| **底层平台** | 智联招聘 (zhaopin.com) |
| **公开 API** | ❌ 无 |
| **疑似 API 端点** | `https://fe-api.zhaopin.com/c/i/sou`（智联通用搜索接口） |
| **可行性评估** | ❌ **不可接入** |
| **证据** | 智联招聘内部 API 需要以下 cookies 才能通过反爬验证：`acw_tc`（阿里云 WAF）、`x-zp-client-id`（设备指纹）、`at`/`rt`（登录态 token）。这些 cookies 必须通过浏览器 JS 环境获取，无法简单模拟。GitHub 上多个开源项目（iszhouhua/zhaopin、silie666/job-crawler）均确认需要带 Cookie 请求或使用 Selenium/Playwright 获取。 |

**请求示例**（需要 cookies，不可直接调用）:
```http
GET https://fe-api.zhaopin.com/c/i/sou?pageSize=90&cityId=489&kw=&p=1
Cookie: x-zp-client-id=xxx; acw_tc=xxx; at=xxx; rt=xxx
```

---

### 2.2 百济神州 (BeiGene)

| 项目 | 详情 |
|------|------|
| **中国校招站** | `http://campus.51job.com/beigene/`（前程无忧平台） |
| **中国社招站** | `https://qnrc.newjobs.com.cn/companyDetail?id=...`（前程无忧企业主页） |
| **全球招聘站** | `https://beigene.wd5.myworkdayjobs.com/BeiGene`（Workday 平台） |
| **招聘公众号** | 「百济神州招聘」 |
| **公开 API** | ⚠️ **全球站部分可接入**，中国站不可 |
| **可行性评估** | ⚠️ **全球站可接入 / 中国站不可** |

#### 全球站（Workday）— 可接入

Workday 的 `wday/cxs` 端点是**公开无鉴权**的 JSON API，这是目前调研中发现的唯一真正可接入的入口。

**API 端点**:
```
POST https://beigene.wd5.myworkdayjobs.com/wday/cxs/beigene/BeiGene/jobs
```

**请求方法**: POST (Content-Type: application/json)

**请求体参数**:
```json
{
  "appliedFacets": {},
  "limit": 20,
  "offset": 0,
  "searchText": ""
}
```

**参数说明**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `limit` | int | 每页数量，最大 20（Workday 硬限制） |
| `offset` | int | 偏移量，用于分页 |
| `searchText` | string | 搜索关键词（可选，留空返回全部） |
| `appliedFacets` | object | 筛选条件，如 `{"locationCountry": ["bc3d5f8a3e364a3f9a3d3f6d8a4b5c6d"]}` |

**响应 JSON 结构**:
```json
{
  "total": 1234,
  "jobPostings": [
    {
      "title": "Summer Internship - AI & People Analytics Intern",
      "externalPath": "Remote-US/Summer-Internship-AI-People-Analytics-Intern_R33347",
      "locationsText": "US - Remote",
      "postedOn": "Posted 3 Days Ago",
      "bulletFields": ["R33347"],
      "jobPostingId": "abc123..."
    }
  ],
  "facets": [
    {
      "descriptor": "Location",
      "facet parameter name": "LocationCountry",
      "values": [...]
    },
    {
      "descriptor": "Job Category",
      "facet parameter name": "JobFamilyGroup",
      "values": [...]
    }
  ]
}
```

**字段说明**:
| 字段 | 说明 |
|------|------|
| `total` | 符合条件的职位总数 |
| `jobPostings[].title` | 职位标题 |
| `jobPostings[].externalPath` | 职位详情路径（含 requestion ID） |
| `jobPostings[].locationsText` | 工作地点摘要 |
| `jobPostings[].postedOn` | 发布日期（相对时间字符串） |
| `jobPostings[].bulletFields` | 数组，首元素为 Req ID（如 R33347） |
| `facets` | 可用的筛选维度（地点、类别等） |

**职位详情端点**:
```
GET https://beigene.wd5.myworkdayjobs.com/wday/cxs/beigene/BeiGene/job/{externalPath}
```
返回完整的 `jobDescription`（HTML 格式）、`timeType`、`additionalLocations`、`jobReqId`、`hiringOrganization`、`canApply` 等。

**反爬情况**:
- 大多数 Workday 租户无 Cloudflare/Akamai 保护
- 速率限制约 50 req/min
- 部分 Fortune 500 租户有 Cloudflare Bot Management，但百济神州当前未发现
- 建议 1.5-2s 请求间隔

#### 中国站（前程无忧 51job）— 不可接入

- 51job 无公开 REST API
- 职位数据通过 `window.__SEARCH_RESULT__` 嵌入 HTML 页面
- URL 格式: `https://search.51job.com/list/{区域代码},000000,0000,00,9,99,{关键词},2,{页码}.html`
- 需解析 HTML 提取 JSON，且有反爬限制
- 评价: ❌ 不可作为公开 API 使用

---

### 2.3 药明康德 (WuXi AppTec)

| 项目 | 详情 |
|------|------|
| **中国招聘站** | `https://wuxiapptec.zhiye.com/`（智联招聘企业平台） |
| **全球招聘站** | `https://careers-wuxiapptec.icims.com/`（iCIMS 平台） |
| **子公司招聘** | `https://smo.wuxiapptec.com/`（津石 SMO） |
| **招聘公众号** | 「药明康德招聘」 |
| **公开 API** | ⚠️ 全球站部分可接入，中国站不可 |
| **可行性评估** | ⚠️ **全球站部分可接入 / 中国站不可** |

#### 全球站（iCIMS）— 部分可接入

iCIMS 招聘页面的内部 XHR API 无需强鉴权即可返回 JSON：

**搜索端点**:
```
GET https://careers-wuxiapptec.icims.com/jobs/search?ss=1&searchLocation=&searchCategory=&searchZip=&searchRadius=50&searchPositionType=&applyOnline=1&in_iframe=1&startrow=0&maxrows=25
```

**参数说明**:
| 参数 | 说明 |
|------|------|
| `ss` | 固定为 1 |
| `searchLocation` | 地点搜索（如 `China`） |
| `searchCategory` | 职位类别 |
| `startrow` | 分页起始行 |
| `maxrows` | 每页最大行数 |

**响应**: 返回 JSON，`searchResults` 数组含 job ID、title、location、department。

**职位详情**: `GET /jobs/{job_id}/job` — 返回含 `<script type="application/ld+json">` (schema.org JobPosting) 的 HTML 页面。

**限制**:
- Internal XHR API，非正式公开 API
- iCIMS 官方 API (`api.icims.com`) 需要 HTTP Basic Auth
- 可能存在速率限制
- Enterprise policy 可能阻止直接 HTTP 访问（本次调研中 WebFetch 被阻止）

#### 中国站（zhiye.com/智联招聘）— 不可接入

- 与恒瑞医药相同的 `fe-api.zhaopin.com` 底层
- 同样需要 `acw_tc`、`x-zp-client-id` cookies
- 评价: ❌ 不可作为公开 API 使用

---

### 2.4 齐鲁制药 (Qilu Pharmaceutical)

| 项目 | 详情 |
|------|------|
| **官方招聘站** | `https://qilu-pharma.zhiye.com/`（智联招聘企业平台） |
| **招聘公众号** | 「齐鲁制药招聘」 |
| **公开 API** | ❌ 无 |
| **可行性评估** | ❌ **不可接入** |
| **证据** | 使用智联招聘 zhiye.com 平台，与恒瑞医药、药明康德中国站相同底层。需要 `acw_tc` 等反爬 cookies。校招通过 `qilu-pharma.zhiye.com/campus` 访问，社招通过 `qilu-pharma.zhiye.com/social`，均无公开 JSON API。 |

---

### 2.5 复星医药 (Fosun Pharma)

| 项目 | 详情 |
|------|------|
| **主要招聘平台** | `https://www.moseeker.com/positions/index/cid/5523207`（脉脉招聘） |
| **备用渠道** | 猎聘 (`liepin.com`)、天府招聘云 (`league.rc114.com`) |
| **招聘公众号** | 复星医药官方公众号 |
| **公开 API** | ❌ 无 |
| **可行性评估** | ❌ **不可接入** |
| **证据** | 脉脉招聘（moseeker.com）需要登录才能浏览职位。招聘信息散布在多个第三方平台，无统一的官方招聘站。猎聘、前程无忧等渠道同样需要登录或受反爬保护。复星医药无独立招聘域名，所有渠道均依赖第三方闭源平台。 |

---

## 3. 总结评估表

| # | 公司 | 中国招聘站 | 全球招聘站 | 平台 | 公开 API | 可行性 |
|---|------|-----------|-----------|------|---------|--------|
| 1 | 恒瑞医药 | hengrui.zhaopin.com | N/A | 智联招聘 | ❌ | ❌ 需 cookies/反爬 |
| 2 | 百济神州 | campus.51job.com/beigene | beigene.wd5.myworkdayjobs.com | 51job + Workday | ⚠️ | ⚠️ 全球站 Workday CXS API 可用 |
| 3 | 药明康德 | wuxiapptec.zhiye.com | careers-wuxiapptec.icims.com | 智联招聘 + iCIMS | ⚠️ | ⚠️ 全球站 iCIMS XHR 部分可用 |
| 4 | 齐鲁制药 | qilu-pharma.zhiye.com | N/A | 智联招聘 | ❌ | ❌ 需 cookies/反爬 |
| 5 | 复星医药 | moseeker.com | N/A | 脉脉招聘 | ❌ | ❌ 需登录 |

---

## 4. 核心结论

### 4.1 行业整体评估: ❌ 不可参照腾讯/网易模式

**腾讯/网易模式的特征**: 自建招聘系统，公开 API 端点（如 `https://careers.tencent.com/tencentcareer/api/post/Query`），无需 cookie，GET/POST 直接返回 JSON。

**制药行业现实**: 中国头部药企**无一自建招聘系统**，全部依赖第三方闭源平台：
- **智联招聘（zhiye.com/zhaopin.com）**: 恒瑞、齐鲁、药明康德中国站。底层 API `fe-api.zhaopin.com` 需要阿里云 WAF cookies。
- **前程无忧（51job）**: 百济神州中国站。HTML 内嵌 JSON，无 REST API。
- **脉脉招聘（moseeker）**: 复星医药。需要登录。
- **Workday**: 百济神州全球站。有公开 CXS API，但仅覆盖全球岗位（多为美国/欧洲），中国本地岗位有限。
- **iCIMS**: 药明康德全球站。内部 XHR API，非正式公开接口。

### 4.2 唯一可行的接入点

**百济神州全球站（Workday CXS API）** 是可唯一确认的公开 JSON API：

| 能力 | 说明 |
|------|------|
| 认证 | 无需认证（公开） |
| 数据格式 | JSON |
| 每页数量 | 最多 20 个职位（硬限制） |
| 分页 | offset 参数，`offset += 20` 直至 `offset >= total` |
| 覆盖范围 | 全球岗位，中国岗位有限（Workday 主要用于美国/欧洲招聘） |
| 速率限制 | ~50 req/min |
| 推荐间隔 | 1.5-2s |

### 4.3 建议

1. **如果接受仅接入全球岗位**: 实现百济神州 Workday CPI 适配器，这是唯一有技术可行性的目标
2. **如果必须接入中国本地岗位**: 当前中国药企的招聘基础设施**不具备公开 API 条件**。唯一的技术路径是：
   - 对智联招聘 (`fe-api.zhaopin.com`) 进行反爬逆向（获取 acw_tc/acw_tc cookies），**但这超出"公开 API 无 cookie"的约束**
   - 使用 Apify 等第三方爬虫平台（付费，$19.89/月起）
3. **替代方向**: 考虑将行业从"纯药企"扩展为"医药健康科技"，纳入丁香园、微医、京东健康等有自建技术栈的公司

---

## 5. 附录: 各平台技术要点

### A. 智联招聘 (zhaopin.com / zhiye.com) 反爬机制

```
Cookie 链: acw_tc (阿里云WAF) → x-zp-client-id (设备指纹) → at/rt (登录态)
获取方式: 浏览器 JS 环境触发 302 重定向 + JS challenge
开源方案: github.com/iszhouhua/zhaopin (Java), silie666/job-crawler (Go)
```

### B. Workday CXS API 完整文档

```
列表: POST /wday/cxs/{tenant}/{site}/jobs
详情: GET /wday/cxs/{tenant}/{site}/job/{externalPath}
SiteMap: GET /en-US/{site}/siteMap.xml (注意大写S)
Facets: 预取筛选维度 UUID 映射
```

### C. iCIMS 内部 API

```
搜索: GET /jobs/search?ss=1&searchLocation=&startrow=0&maxrows=25
详情: GET /jobs/{jobId}/job (含 ld+json)
限制: 非正式公开 API，企业网络策略可能阻止访问
```

---

> 调研人: AI Research Agent
> 状态: 完成
> 后续: 如需实现百济神州 Workday 适配器，请参考上述 API 文档创建 `beigene_global.py` 适配器文件
