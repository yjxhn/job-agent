# 跨平台去重算法效果评估操作手册

> 版本：1.0 | 最后更新：2026-06-25 | 关联代码：`agent_core/pipeline/search.py`

---

## 目录

1. [算法真实实现](#1-算法真实实现)
2. [评估目标](#2-评估目标)
3. [前置准备：获取样本数据](#3-前置准备获取样本数据)
4. [标注流程](#4-标注流程)
5. [计算评估指标](#5-计算评估指标)
6. [结果解读与阈值调优](#6-结果解读与阈值调优)
7. [附录：样本量参考](#7-附录样本量参考)

---

## 1. 算法真实实现

在动手评估之前，必须精确理解代码实际做了什么。以下基于 `agent-core` 仓库 `master` 分支代码。

### 1.1 dedup_key 构成

去重判断的 key 由 `Job.dedup_key()` 生成（`agent_core/platforms/base.py:32-33`）：

```python
def dedup_key(self) -> str:
    return f"{self.company_normalized}|{_norm_title(self.title)}"
```

即：**标准化后的公司名** + 分隔符 `|` + **标准化后的岗位名**。

### 1.2 `_norm_title()` 做了什么

位置：`agent_core/platforms/base.py:103-107`

```python
# Pure-decoration words stripped from titles before dedup. Kept deliberately
# conservative: terms that change job identity (应届/实习/兼职/外包) are NOT
# listed — removing them would wrongly merge distinct roles.
_TITLE_NOISE_WORDS = (
    "急招", "急聘", "诚聘", "高薪", "双休", "周末双休", "五险一金",
    "包吃住", "包食宿", "包吃", "包住", "朝九晚六", "弹性工作",
    "福利好", "待遇优厚", "待遇好", "直招", "直聘",
)

def _norm_title(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r"[（(][^)）]*[)）]", "", t)
    for w in _TITLE_NOISE_WORDS:
        t = t.replace(w, "")
    t = re.sub(r"招聘$", "", t)  # trailing "招聘" is decoration, but "招聘专员" is a role
    t = re.sub(r"[，。、！？!?·•:：;；/|\\\-_~]+", "", t)
    t = re.sub(r"\s+", "", t)
    return t
```

**归一化步骤：**
1. 转小写
2. 删除中文/英文括号及其内部内容。例如 `"Python开发工程师(应届)"` -> `"python开发工程师"`；`"产品经理（AI方向）"` -> `"产品经理"`
3. 删除纯装饰性营销词（急招/高薪/双休/五险一金/包吃住/弹性工作/直聘等）。**刻意保守**：改变岗位身份的词汇（应届/实习/兼职/外包）不删——删了会误并不同岗位
4. 删除末尾的 `招聘`（仅当它是后缀；`招聘专员` 中的 `招聘` 是岗位名保留）
5. 删除常见标点/分隔符（，。、！？·•:：;；/|\-_~）
6. 删除所有空格、换行等空白字符

**重要：`_norm_title` 本身不做 fuzzy 匹配**（fuzzy 合并发生在 `_dedup`，见 1.4）。

### 1.3 `_normalize_company()` 做了什么

位置：`agent_core/pipeline/search.py:19-42`

```python
def _normalize_company(name: str, aliases: dict) -> str:
    from difflib import SequenceMatcher

    name_lower = name.strip().lower()
    # 1) Exact match in alias table
    for canonical, variants in aliases.items():
        for v in variants:
            if name_lower == v.lower() or name_lower in v.lower() or v.lower() in name_lower:
                return canonical
    # 2) Fuzzy match against all known names
    all_known = [...]
    best_score: float = 0.0
    best_canonical = name.strip()
    for canonical, v_lower in all_known:
        score = SequenceMatcher(None, name_lower, v_lower).ratio()
        if score > best_score:
            best_score = score
            best_canonical = canonical
    if best_score >= 0.75:
        return best_canonical
    return name.strip()
```

**两步归一化：**

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1 | 精确 + 子串匹配 | 公司名与 `config.yaml` 的 `company_aliases` 中任意 variant 精确匹配或互为子串，返回 canonical 名 |
| 2 | Fuzzy 匹配（阈值 0.75） | 若步骤 1 未命中，用 `difflib.SequenceMatcher().ratio()` 与所有已知 variant 比较，最高分 >= 0.75 则映射到对应 canonical；否则保留原名 |

**`company_aliases` 示例**（`config.yaml:52-62`）：

```yaml
company_aliases:
  catl: ["宁德时代", "CATL", "宁德时代新能源科技股份有限公司"]
  byd: ["比亚迪", "BYD", "比亚迪股份有限公司"]
  tencent: ["腾讯", "Tencent", "腾讯科技", "深圳市腾讯计算机系统有限公司"]
  # ...
```

### 1.4 `_dedup()` 的合并逻辑

位置：`agent_core/pipeline/search.py:216-244`

```python
_TITLE_FUZZ_THRESHOLD = 0.85  # titles within this similarity merge when company matches

def _dedup(jobs: list[Job], aliases: dict) -> list[Job]:
    for j in jobs:
        j.company_normalized = _normalize_company(j.company, aliases)

    seen: dict[str, Job] = {}
    seen_norm: list[tuple[str, Job]] = []  # (dedup_key, job) for fuzzy matching
    for j in jobs:
        key = j.dedup_key()
        existing = seen.get(key)
        if existing is None:
            # Same company, fuzzy title match — e.g. "AMR工程师" vs "AMR调度工程师"
            existing = _fuzzy_title_match(j, seen_norm)
        if existing is not None:
            existing.platforms = list(set(existing.platforms + j.platforms))
            existing.urls.update(j.urls)
            if j.last_seen and (not existing.last_seen or j.last_seen > existing.last_seen):
                existing.last_seen = j.last_seen
            existing.is_new = existing.is_new or j.is_new
        else:
            seen[key] = j
            seen_norm.append((key, j))
    return list(seen.values())


def _fuzzy_title_match(job: Job, seen_norm: list[tuple[str, Job]]) -> Job | None:
    """Return the job in seen whose dedup_key matches job's fuzzily (same company).

    Only compares against keys with the same company_normalized; title similarity
    must be >= _TITLE_FUZZ_THRESHOLD. Long titles are compared on a shared
    substring window to avoid one huge role shadowing a short one.
    """
    from difflib import SequenceMatcher

    key = job.dedup_key()
    if not key:
        return None
    company, _, title = key.partition("|")
    if not title:
        return None
    for k, existing in seen_norm:
        ec, _, etitle = k.partition("|")
        if ec != company or not etitle:
            continue
        ratio = SequenceMatcher(None, title, etitle).ratio()
        if ratio >= _TITLE_FUZZ_THRESHOLD:
            return existing
    return None
```

**合并规则：**
- 精确合并：同一个 `dedup_key` 的多条记录合并为一条
- **模糊合并（新增）**：`dedup_key` 精确匹配不到时，同一 `company_normalized` 下 title 相似度 ≥ 0.85（`SequenceMatcher`）合并。例如 `"AMR工程师"` vs `"AMR调度工程师"`（同公司）会合并
- `platforms` 合并去重（list set union）
- `urls` 合并（dict update）
- `last_seen` 取最新
- `is_new` 取 OR（任一平台标记为新即为新）
- **不会比较 salary、description、location 等字段**（合并时第一个见到的为准）

### 1.5 关键结论

| 问题 | 答案 |
|------|------|
| 用了哪个 fuzzy 库？ | **没用第三方 fuzzy 库**。`_normalize_company` 和 `_fuzzy_title_match` 都用标准库 `difflib.SequenceMatcher` |
| dedup key 比较是 fuzzy 还是 exact？ | 两步：**先 exact**（`dedup_key` 字符串 `==`），**exact 不中时同公司 title 走 fuzzy ≥ 0.85** |
| 75% 阈值用在什么地方？ | 仅在 `_normalize_company` 中将公司名映射到别名表 canonical，**不参与 title 或 dedup key 的比较** |
| 85% 阈值用在什么地方？ | `_fuzzy_title_match`：同一 `company_normalized` 下 title 相似度 ≥ 0.85 才合并 |
| 两个标题略有不同的同岗位会被合并吗？ | **会**（同公司、相似度 ≥ 0.85）。如 `"AMR工程师"` 与 `"AMR调度工程师"` 合并 |
| 两个不同公司、同 title 的岗位会被合并吗？ | **不会**。fuzzy 合并要求 company_normalized 相同（dedup key 也包含公司） |
| 不同角色的同公司岗位会被误并吗？ | **基本不会**。`_TITLE_NOISE_WORDS` 刻意保守（不删 应届/实习/兼职/外包），相似度阈值 0.85 较高。极端情况如 "AI产品经理" vs "AI产品经理（B端）" 括号删除后 exact 相同仍会并（既有行为，见 §2.2 误杀风险） |

---

## 2. 评估目标

### 2.1 测什么

| 指标 | 含义 | 通俗解释 |
|------|------|----------|
| **Precision（精确率）** | TP / (TP + FP) | 算法判为"重复"的岗位对中，有多少**真的是重复**？（误杀率 = 1 - Precision） |
| **Recall（召回率）** | TP / (TP + FN) | 所有真实重复的岗位对中，算法找出了多少？（漏杀率 = 1 - Recall） |
| **F1 Score** | 2 * P * R / (P + R) | Precision 和 Recall 的调和平均，综合衡量去重效果 |

其中：
- **TP（True Positive）**：算法合并了，人工也判定是重复
- **FP（False Positive）**：算法合并了，但人工判定不是重复（**误杀**）
- **FN（False Negative）**：算法没合并，但人工判定是重复（**漏杀**）
- **TN（True Negative）**：算法没合并，人工也判定不是重复

### 2.2 为什么重要

当前算法有两大未知风险：

1. **误杀风险**：不同岗位因标题标准化后完全相同被错误合并。例如某公司同时招 "AI产品经理" 和 "AI产品经理（B端）"，括号被删后 dedup_key 相同，但实际是不同的 HC。
2. **漏杀风险**：同一岗位在不同平台用略有不同的标题发布，因 exact match 无法合并。例如 BOSS 上叫 "大模型算法工程师"，猎聘上叫 "LLM算法工程师"，不会被合并。

---

## 3. 前置准备：获取样本数据

### 3.1 运行一次全平台搜索

```bash
# 在 agent-core 项目根目录下
cd C:\Users\29366\projects\agent-core

# 全量搜索（所有启用的方向和平台）
python -m agent_core.cli search

# 或者指定关键词和平台
python -m agent_core.cli search --keyword AMR --platforms boss_zhipin,liepin,zhilian
```

**搜索前确认**（`config.yaml` 中）：

- 所有目标平台的 `enabled: true`
- 至少 2 个方向（direction）启用以增加样本多样性
- `exclude_keywords` 不含过于宽泛的排除词，避免样本过少

### 3.2 导出搜索结果为可标注格式

搜索结果存储在 SQLite 数据库中。运行以下命令导出：

```bash
# 导出最近一次搜索结果到 JSON
python -c "
import json
from agent_core.storage import get_db

db = get_db()
# 获取最近一次搜索的全部 jobs
rows = db.execute('SELECT * FROM jobs ORDER BY first_seen DESC').fetchall()
print(f'共 {len(rows)} 条记录')
# 检查是否有足够的多平台交叉数据
from collections import Counter
platforms_per_title = Counter()
for r in rows:
    platforms_per_title[r['title']] += 1
multi = sum(1 for c in platforms_per_title.values() if c > 1)
print(f'出现在多个平台上的岗位名数量: {multi}')
"
```

如果多平台岗位数量 < 20，建议多运行几次不同方向的搜索以积累样本。

### 3.3 生成标注 CSV

用以下脚本从 SQLite 导出标注用 CSV：

```bash
python -c "
import csv, json
from agent_core.storage import get_db

db = get_db()
rows = db.execute('SELECT * FROM jobs ORDER BY first_seen DESC').fetchall()

with open('dedup_labeling_input.csv', 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow([
        'job_id', 'platform', 'title', 'company', 'company_normalized',
        'location', 'salary_min', 'salary_max', 'url', 'direction'
    ])
    for r in rows:
        urls = json.loads(r['urls'] or '{}')
        first_url = list(urls.values())[0] if urls else ''
        writer.writerow([
            r['id'], r['platforms'], r['title'], r['company'],
            r['company_normalized'], r['location'],
            r['salary_min'], r['salary_max'], first_url, r['direction']
        ])

print(f'导出完成: dedup_labeling_input.csv ({len(rows)} 行)')
"
```

### 3.4 构造待标注的"岗位对"（Pair Candidates）

去重评估的核心不是标注单条记录，而是标注**岗位对**——判断两条不同平台的记录是否代表同一个真实岗位。

```bash
python -c "
import csv, json, re
from collections import defaultdict
from agent_core.storage import get_db

# 从 DB 读取所有 jobs
db = get_db()
rows = db.execute('SELECT * FROM jobs ORDER BY first_seen DESC').fetchall()

# 按 title 分组
def norm_title(t):
    t = t.strip().lower()
    t = re.sub(r'[（(][^)）]*[)）]', '', t)
    t = re.sub(r'\s+', '', t)
    return t

# 构建 dedup_key 分组
groups = defaultdict(list)
for r in rows:
    cn = r['company_normalized'] or r['company']
    key = f'{cn}|{norm_title(r[\"title\"])}'
    groups[key].append(r)

# 找出有多平台记录的组（这些是算法可能合并的）
pairs = []
for key, recs in groups.items():
    platforms = set()
    for rec in recs:
        for p in json.loads(rec['platforms'] or '[]'):
            platforms.add(p)
    if len(platforms) > 1:
        # 生成该组内的所有跨平台对
        for i in range(len(recs)):
            for j in range(i+1, len(recs)):
                pi = recs[i]['platforms']
                pj = recs[j]['platforms']
                if pi != pj:
                    pairs.append((recs[i], recs[j]))

print(f'跨平台候选对数量: {len(pairs)}')
# 还需要找漏杀的：同一岗位出现不同 title 的候选
# （手动在标注表中添加）

# 导出候选对
with open('dedup_pair_candidates.csv', 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow([
        'pair_id', 'job_a_id', 'job_a_platform', 'job_a_title', 'job_a_company',
        'job_a_location', 'job_a_salary', 'job_a_url',
        'job_b_id', 'job_b_platform', 'job_b_title', 'job_b_company',
        'job_b_location', 'job_b_salary', 'job_b_url',
        'will_be_merged_by_algo', 'human_label', 'notes'
    ])
    for idx, (a, b) in enumerate(pairs):
        urls_a = json.loads(a['urls'] or '{}')
        urls_b = json.loads(b['urls'] or '{}')
        writer.writerow([
            f'pair_{idx:04d}',
            a['id'], a['platforms'], a['title'], a['company'],
            a['location'], f\"{a['salary_min']}-{a['salary_max']}\",
            list(urls_a.values())[0] if urls_a else '',
            b['id'], b['platforms'], b['title'], b['company'],
            b['location'], f\"{b['salary_min']}-{b['salary_max']}\",
            list(urls_b.values())[0] if urls_b else '',
            'YES',  # 这些对算法会合并（dedup_key 相同），待验
            '',     # 人工判定：DUPLICATE / DIFFERENT / UNCERTAIN
            ''
        ])

print(f'导出完成: dedup_pair_candidates.csv ({len(pairs)} 对)')
"
```

---

## 4. 标注流程

### 4.1 标注 CSV 模板

文件：`dedup_pair_candidates.csv`

| 列名 | 说明 | 谁填 |
|------|------|------|
| `pair_id` | 对编号 | 自动生成 |
| `job_a_id` | 岗位 A 的 DB ID | 自动生成 |
| `job_a_platform` | A 来源平台（boss_zhipin/liepin/zhilian 等） | 自动生成 |
| `job_a_title` | A 原始标题 | 自动生成 |
| `job_a_company` | A 公司名（原始） | 自动生成 |
| `job_a_location` | A 工作地点 | 自动生成 |
| `job_a_salary` | A 薪资范围 | 自动生成 |
| `job_a_url` | A 岗位链接 | 自动生成 |
| `job_b_*` | 同上，岗位 B | 自动生成 |
| `will_be_merged_by_algo` | 算法是否会合并这对（YES/NO） | **自动生成** |
| `human_label` | **人工判定**：DUPLICATE / DIFFERENT / UNCERTAIN | **人工填写** |
| `notes` | 判定理由（如"同部门不同级别"） | 人工填写 |

### 4.2 怎么填 `human_label`

对每一对候选记录，打开两个链接，对比以下维度：

| 维度 | 怎么看 |
|------|--------|
| **公司** | 是不是同一家公司（包括母子公司、收购关系） |
| **岗位名称** | 标题含义是否指向同一个职位 |
| **部门/BU** | 描述中是否提到不同事业部或团队 |
| **地点** | 城市、园区是否相同 |
| **薪资范围** | 差异是否在合理范围内（同岗位不同平台薪资标注可能不同） |
| **HC 数量** | 描述中是否暗示招多个人（同 title 多个 HC 不算重复） |
| **职级** | 标注的级别（初级/高级/资深）是否相同 |

### 4.3 标注规则详解

#### 规则 1：同一公司 + 同一岗位 + 同一城市 = DUPLICATE

```
例：
  BOSS: "高级Java开发工程师" @ 字节跳动 - 北京
  猎聘: "高级Java开发工程师" @ 字节跳动 - 北京
  → DUPLICATE（同一职位跨平台发布）
```

#### 规则 2：同一公司 + 同一岗位 + 不同城市 = 看情况

```
例 A：
  BOSS: "嵌入式软件工程师" @ 比亚迪 - 深圳
  猎聘: "嵌入式软件工程师" @ 比亚迪 - 西安
  → DIFFERENT（城市不同，大概率是不同的 HC）
  
例 B：
  BOSS: "嵌入式软件工程师" @ 比亚迪 - 深圳
  猎聘: "嵌入式软件工程师" @ 比亚迪 - 深圳坪山
  → DUPLICATE（同一城市，仅是行政区域写法差异）
```

#### 规则 3：外包 / 子公司 / 劳务派遣 = DIFFERENT

```
例：
  BOSS: "Java开发" @ 华为技术有限公司
  猎聘: "Java开发" @ 中软国际（外派华为）
  → DIFFERENT（用工主体不同）
```

#### 规则 4：同公司 + 标题略有差异 + 描述指向同一岗位 = DUPLICATE

```
例：
  BOSS: "LLM算法工程师" @ 腾讯
  猎聘: "大模型算法工程师" @ 腾讯
  → DUPLICATE（虽然标题不同，但描述、职责相同）
  
  此时只标 DUPLICATE——你不需要担心算法能不能检测出来，
  那是评估阶段要计算的东西。
```

#### 规则 5：同公司 + 标题相同 + 职级明显不同 = DIFFERENT

```
例：
  BOSS: "产品经理" @ 美团（薪资15-25K，要求1-3年）
  猎聘: "产品经理" @ 美团（薪资30-50K，要求5-10年）
  → DIFFERENT（一个是初级岗，一个是高级/资深岗）
```

#### 规则 6：不确定的情况 = UNCERTAIN

当两个链接的信息不足以做出判断时，标记 UNCERTAIN。这些对不参与最终指标计算。

### 4.4 除了候选对，还需要补充漏杀样本

上面导出的候选对 CSV 只包含算法**会**合并的对（`will_be_merged_by_algo = YES`）。要测量 Recall，还需要算法**不会**合并但实际上是重复的对。

**手动补充步骤：**

1. 浏览导出的 `dedup_labeling_input.csv`，找出以下模式的岗位：
   - 同一公司、不同标题但看起来是同一岗位的记录（如 "Python后端开发" vs "Python开发工程师"）
   - 标题略有差异但描述高度重叠的记录
2. 将这样的对追加到 `dedup_pair_candidates.csv` 末尾，`will_be_merged_by_algo` 填 `NO`
3. 人工判定 `human_label` 填 `DUPLICATE`

这种做法会产生 FN（算法判否，人工判是），用于计算 Recall。

### 4.5 标注工作量估算

| 场景 | 样本特征 | 建议标注对数 |
|------|----------|-------------|
| 最小可行 | 快速摸底 | 50-100 对 |
| 可靠估计 | 可做决策 | 200-500 对 |
| 精确测量 | 论文级 | 1000+ 对 |

每人每小时大约可标注 60-100 对（取决于岗位相似度）。

---

## 5. 计算评估指标

### 5.1 公式

```
                          TP
Precision = ──────────────────────────
              TP + FP     (算法判为重复的总数)

                          TP
Recall    = ──────────────────────────
              TP + FN     (真实重复的总数)

              2 × Precision × Recall
F1        = ─────────────────────────
               Precision + Recall
```

其中：
- **TP**：`will_be_merged_by_algo = YES` 且 `human_label = DUPLICATE`
- **FP**：`will_be_merged_by_algo = YES` 且 `human_label = DIFFERENT`
- **FN**：`will_be_merged_by_algo = NO` 且 `human_label = DUPLICATE`
- **TN**：`will_be_merged_by_algo = NO` 且 `human_label = DIFFERENT`

### 5.2 Python 计算脚本（参考骨架）

以下脚本读取标注 CSV 和数据库，计算上述指标。你可以保存为独立脚本运行。

```python
"""
dedup_eval.py -- 读取标注 CSV，计算去重算法的 Precision / Recall / F1

用法：
    python dedup_eval.py dedup_pair_candidates.csv

依赖：
    pip install thefuzz  # 可选：用于事后分析漏杀对相似度
"""

import csv
import json
import re
import sys
from collections import defaultdict

# ============================================================
# 1. 复现算法的核心函数（与 agent_core 保持一致）
# ============================================================

def _norm_title(title: str) -> str:
    """复现 agent_core/platforms/base.py:103-107"""
    t = title.strip().lower()
    t = re.sub(r"[（(][^)）]*[)）]", "", t)
    t = re.sub(r"\s+", "", t)
    return t


def _normalize_company(name: str, aliases: dict) -> str:
    """复现 agent_core/pipeline/search.py:19-42"""
    from difflib import SequenceMatcher

    name_lower = name.strip().lower()
    # 1) 精确/子串匹配
    for canonical, variants in aliases.items():
        for v in variants:
            if name_lower == v.lower() or name_lower in v.lower() or v.lower() in name_lower:
                return canonical
    # 2) Fuzzy 匹配
    all_known = [
        (canonical, v.lower()) for canonical, variants in aliases.items() for v in variants
    ]
    best_score = 0.0
    best_canonical = name.strip()
    for canonical, v_lower in all_known:
        score = SequenceMatcher(None, name_lower, v_lower).ratio()
        if score > best_score:
            best_score = score
            best_canonical = canonical
    if best_score >= 0.75:
        return best_canonical
    return name.strip()


def dedup_key(title: str, company: str, aliases: dict) -> str:
    """复现 agent_core/platforms/base.py:32-33"""
    c = _normalize_company(company, aliases)
    return f"{c}|{_norm_title(title)}"


# ============================================================
# 2. 从 config.yaml 加载 alias 表
# ============================================================

def load_aliases(config_path: str = "config.yaml") -> dict:
    """从 config.yaml 读取 company_aliases"""
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return raw.get("company_aliases", {})
    except Exception:
        print("[WARN] 无法读取 config.yaml，alias 表为空")
        return {}


# ============================================================
# 3. 主评估逻辑
# ============================================================

def evaluate(csv_path: str) -> dict:
    aliases = load_aliases()

    tp = fp = fn = tn = 0
    details = {"fp_cases": [], "fn_cases": []}

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        required_cols = {
            "will_be_merged_by_algo", "human_label",
            "job_a_title", "job_a_company",
            "job_b_title", "job_b_company",
        }
        if not required_cols.issubset(set(reader.fieldnames or [])):
            missing = required_cols - set(reader.fieldnames or [])
            print(f"[ERROR] CSV 缺少列: {missing}")
            sys.exit(1)

        for row in reader:
            label = row["human_label"].strip().upper()

            # 跳过未标注和不确定的行
            if label == "UNCERTAIN" or label == "":
                continue
            if label not in ("DUPLICATE", "DIFFERENT"):
                print(f"[WARN] 未知标签 '{label}'，跳过 pair_id={row['pair_id']}")
                continue

            algo_says_dup = row["will_be_merged_by_algo"].strip().upper() == "YES"
            human_says_dup = label == "DUPLICATE"

            if algo_says_dup and human_says_dup:
                tp += 1
            elif algo_says_dup and not human_says_dup:
                fp += 1
                details["fp_cases"].append({
                    "pair_id": row["pair_id"],
                    "title_a": row["job_a_title"],
                    "title_b": row["job_b_title"],
                    "company_a": row["job_a_company"],
                    "company_b": row["job_b_company"],
                    "notes": row.get("notes", ""),
                })
            elif not algo_says_dup and human_says_dup:
                fn += 1
                details["fn_cases"].append({
                    "pair_id": row["pair_id"],
                    "title_a": row["job_a_title"],
                    "title_b": row["job_b_title"],
                    "company_a": row["job_a_company"],
                    "company_b": row["job_b_company"],
                    "notes": row.get("notes", ""),
                })
            else:
                tn += 1

    # 计算指标
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "total_pairs": total,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "details": details,
    }


# ============================================================
# 4. 打印报告
# ============================================================

def print_report(result: dict):
    print("=" * 60)
    print("  去重算法效果评估报告")
    print("=" * 60)
    print()
    print(f"  评估对数:      {result['total_pairs']}")
    print(f"  TP (正确合并):  {result['tp']}")
    print(f"  FP (误合并):    {result['fp']}")
    print(f"  FN (漏合并):    {result['fn']}")
    print(f"  TN (正确未合并): {result['tn']}")
    print()
    print(f"  Precision (精确率):  {result['precision']:.1%}")
    print(f"  Recall    (召回率):  {result['recall']:.1%}")
    print(f"  F1 Score   (F1值):   {result['f1']:.1%}")
    print()

    # 误杀详情
    if result["details"]["fp_cases"]:
        print(f"  --- 误杀案例 ({len(result['details']['fp_cases'])} 个) ---")
        for case in result["details"]["fp_cases"][:5]:
            print(f"  [{case['pair_id']}] {case['title_a']} vs {case['title_b']}")
            print(f"       公司: {case['company_a']} vs {case['company_b']}")
            if case["notes"]:
                print(f"       备注: {case['notes']}")
        if len(result["details"]["fp_cases"]) > 5:
            print(f"  ... 还有 {len(result['details']['fp_cases']) - 5} 个")
        print()

    # 漏杀详情
    if result["details"]["fn_cases"]:
        print(f"  --- 漏杀案例 ({len(result['details']['fn_cases'])} 个) ---")
        for case in result["details"]["fn_cases"][:5]:
            print(f"  [{case['pair_id']}] {case['title_a']} vs {case['title_b']}")
            print(f"       公司: {case['company_a']} vs {case['company_b']}")
            if case["notes"]:
                print(f"       备注: {case['notes']}")
        if len(result["details"]["fn_cases"]) > 5:
            print(f"  ... 还有 {len(result['details']['fn_cases']) - 5} 个")
        print()

    # 诊断建议
    print("  --- 诊断建议 ---")
    if result["precision"] < 0.85:
        print(f"  !! Precision {result['precision']:.1%} 偏低（误杀多）")
        print(f"  建议：检查 _norm_title 是否过于激进（去掉括号丢失关键信息）")
        print(f"        或在 dedup_key 中加入 location 字段")
    if result["recall"] < 0.80:
        print(f"  !! Recall {result['recall']:.1%} 偏低（漏杀多）")
        print(f"  建议：考虑对 title 引入 fuzzy 匹配（如 token_sort_ratio）")
        print(f"        或扩充 company_aliases 覆盖更多变体")
    if result["precision"] >= 0.85 and result["recall"] >= 0.80:
        print(f"  ✓ Precision 和 Recall 均在可接受范围")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python dedup_eval.py dedup_pair_candidates.csv")
        sys.exit(1)
    result = evaluate(sys.argv[1])
    print_report(result)
```

### 5.3 运行评估

```bash
# 1. 先完成标注（修改 dedup_pair_candidates.csv 的 human_label 列）
# 2. 运行评估
python dedup_eval.py dedup_pair_candidates.csv
```

---

## 6. 结果解读与阈值调优

### 6.1 指标解读

| Precision | Recall | 诊断 | 行动 |
|-----------|--------|------|------|
| >= 90% | >= 85% | 健康 | 维持现状，定期复查 |
| >= 90% | < 80% | 保守过高（漏杀多） | 见 6.3 |
| < 85% | >= 90% | 激进过高（误杀多） | 见 6.2 |
| < 80% | < 80% | 两面都差 | 优先提升 Precision（见 6.2），再提升 Recall（见 6.3） |

### 6.2 Precision 低（误杀多）怎么办

**典型误杀场景**（两个不同岗位被错误合并）：

| 场景 | 原因 | 修复方向 |
|------|------|----------|
| 不同部门的同 title 岗位 | `_norm_title` 只用了 title，没区分部门 | 在 `dedup_key` 中加入 `location` 或提取 description 中的部门信息 |
| 不同职级的同 title 岗位 | "Python开发" 既可以是初级也可以是高级 | 用 salary 或 description 中的年限要求做二次分桶 |
| 括号内是区分信息而非修饰 | "产品经理(数据)" vs "产品经理(增长)"，括号被删 | 修改 `_norm_title` 的括号删除规则，只删除修饰性后缀（如"应届"、"实习"），保留有语义的内容 |
| 公司别名映射错误 | Fuzzy 0.75 把不相关的公司映射到同一个 canonical | 降低 `_normalize_company` 中 `best_score >= 0.75` 的阈值（如提高到 0.85），或检查 alias 表是否有误 |

### 6.3 Recall 低（漏杀多）怎么办

**典型漏杀场景**（同一岗位跨平台未被合并）：

| 场景 | 原因 | 修复方向 |
|------|------|----------|
| 同岗位不同命名习惯 | BOSS 叫 "Golang开发"，猎聘叫 "Go开发工程师" | 对 `_norm_title` 后的 title 引入同义词映射（如 `{"golang": "go", "nodejs": "node"}`） |
| 中英文混杂 | "Java工程师" vs "Java开发工程师" | 引入岗位核心词提取（如只保留 "java" + "工程师"） |
| 公司名无别名 | 小公司不在 `company_aliases`，不同平台写法不同 | 扩充 alias 表；或对不在 alias 表中的公司启用更宽松的 fuzzy 匹配 |
| 同一职位名称有修饰词差异 | "高级前端工程师" vs "资深前端工程师" | 引入职级归一化表（高级=资深=senior），在 title 标准化时统一 |

### 6.4 阈值调优实验框架

如果你的标注集足够大（>300 对），可以用以下方式系统化寻找最佳参数：

```python
# 伪代码：网格搜索最佳 fuzzy 阈值
# 当前 _normalize_company 使用 0.75 固定阈值
# 假设将来对 title 也引入 fuzzy 匹配，可按此框架调参

thresholds = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
results = []

for th in thresholds:
    # 用阈值 th 跑一遍 dedup
    merged = run_dedup_with_threshold(all_jobs, threshold=th)
    # 和标注集比对
    precision, recall, f1 = compute_metrics(merged, ground_truth)
    results.append((th, precision, recall, f1))

# 选 F1 最高的阈值
best = max(results, key=lambda x: x[3])
print(f"最优阈值: {best[0]}, F1: {best[3]:.2%}")
```

---

## 7. 附录：样本量参考

### 7.1 需要多少标注对

基于 Wilson 置信区间估算 95% 置信度下的误差范围：

| 样本量 | Precision/Recall 观测值 | 95% CI 误差 |
|--------|------------------------|-------------|
| 50 | 90% | +/- 8.3% |
| 100 | 90% | +/- 5.9% |
| 200 | 90% | +/- 4.2% |
| 500 | 90% | +/- 2.6% |
| 1000 | 90% | +/- 1.9% |

**建议**：至少 100 对起步快速摸底，200-300 对足够做阈值调优决策。

### 7.2 常见陷阱

1. **类不平衡**：如果 90% 的候选对都是真重复（或都不是），指标会虚高。理想情况下 DUPLICATE 和 DIFFERENT 的比例应在 30:70 到 70:30 之间。
2. **标注者偏差**：单人标注不可靠。如果条件允许，找另一人独立标注 20% 的样本，计算 Cohen's Kappa 验证一致性。Kappa < 0.6 说明标注规则不够清晰。
3. **时间漂移**：招聘平台的岗位标题风格会变。建议每季度重新标注一次小样本（50 对）验证算法仍然有效。
4. **只标注算法会合并的对**：这会漏掉 FN 的计算。必须手动补充算法不会合并但实际重复的对（见 4.4 节）。

---

> **维护备忘**：本手册关联的代码位置为 `agent_core/pipeline/search.py:216-232`（`_dedup`）、`agent_core/platforms/base.py:103-107`（`_norm_title`）、`agent_core/platforms/base.py:32-33`（`dedup_key`）。当这些函数修改时需同步更新本手册。
