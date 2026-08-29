"""Tool definitions (OpenAI function-calling schema) + dispatcher for the chat agent.

Each tool wraps an existing pipeline/tracking/cookie-health function.
The dispatcher is a stateful class that holds config/db/provider so tools
can call the underlying async functions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC
from typing import Any

from agent_core.storage.models import VALID_STATUSES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date parser for platform-reported publish dates
# ---------------------------------------------------------------------------


def _parse_platform_date(raw: str):
    """Parse a platform-reported date string into a UTC-aware datetime, or None.

    Handles the diverse formats returned by different job platforms:
    - ISO 8601: "2026-07-15T10:30:00" / "2026-07-15T10:30:00+08:00"
    - Space-separated: "2026-07-15 10:30:00"
    - Date-only: "2026-07-15"
    - Unix timestamp (seconds or milliseconds)
    - Beisen ChangeDate format

    Returns a timezone-aware datetime or None if parsing fails.
    """
    from datetime import datetime

    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    # 1) Unix timestamp (seconds or milliseconds)
    try:
        ts = float(text)
        if ts > 0:
            if ts > 1e12:  # milliseconds
                ts /= 1000
            if ts < 2e10:  # plausible Unix timestamp range
                return datetime.fromtimestamp(ts, tz=UTC)
    except (ValueError, OverflowError, OSError):
        pass

    # 2) ISO 8601 variants + Chinese date format
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling JSON Schema)
# ---------------------------------------------------------------------------

# Single source of truth: agent_core.storage.models.VALID_STATUSES
STATUS_VALUES = VALID_STATUSES

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": (
                "搜索职位。按关键词和地点搜索各大招聘平台，支持多维度过滤。"
                "可通过 platform 限定公司官网平台（如 byd/比亚迪、naura/北方华创），"
                "也可通过 company 按公司名过滤结果（如 '大疆'）。"
                "\n\n"
                "【重要】每次对话最多调用 7 次。调用前请先思考："
                "哪些关键词组合能覆盖用户需求的不同维度？"
                "建议从产品名、技术栈、岗位职能、目标公司等角度拆分。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索关键词列表，如 ['设备工程师', 'AMR 调度']。用户输入什么关键词就搜什么，不要用配置中的方向名。",
                    },
                    "location": {
                        "type": "string",
                        "description": "工作地点，如 '苏州'、'全国'、'上海'。传 '全国' 或不传则不限制地点。",
                    },
                    "platform": {
                        "type": "string",
                        "description": (
                            "限定搜索平台，可逗号分隔多个。"
                            "公司官网平台：byd=比亚迪, naura=北方华创, yofc=长飞光纤, "
                            "tencent=腾讯, netease=网易。"
                            "通用平台：boss_zhipin=BOSS直聘, liepin=猎聘, zhilian=智联。"
                            "不传则搜所有 enabled 平台。"
                        ),
                    },
                    "company": {
                        "type": "string",
                        "description": (
                            "按公司名过滤结果（大小写不敏感，子串匹配）。"
                            "如 '大疆'、'华为'。在搜索完成后原地过滤。"
                        ),
                    },
                    "min_salary": {
                        "type": "integer",
                        "description": "薪资下限（月薪，单位 K）。如用户期望月薪 9K 则传 9。只显示薪资 >= 此值的岗位。",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认 15。用户要求更多结果时调大此值。",
                    },
                    "education": {
                        "type": "string",
                        "description": "学历要求。可传 '不限'、'本科'、'硕士'、'博士'。不传则不限制。",
                    },
                    "days_old": {
                        "type": "integer",
                        "description": "发布时间限制（近 N 天内发布的岗位）。如传 7 表示近 7 天。不传则不限制。",
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tracked_applications",
            "description": "列出已投递的职位申请，可按状态筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": STATUS_VALUES,
                        "description": "按状态筛选，如 '约面'、'Offer'。不传则显示全部。",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_application",
            "description": "记录一个新投递申请。传入职位 ID（job_id）开始跟踪这个职位的投递进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "职位唯一 ID",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_application_status",
            "description": "更新投递申请的状态（如已投递→约面→一面→Offer）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_id": {
                        "type": "integer",
                        "description": "申请编号（#N），从 list_tracked_applications 获取",
                    },
                    "status": {
                        "type": "string",
                        "enum": STATUS_VALUES,
                        "description": "新状态",
                    },
                },
                "required": ["app_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tailor_resume",
            "description": "根据职位要求定制简历，生成 .docx 和 .md 文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "职位唯一 ID",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cover_letter",
            "description": "为职位生成HR打招呼消息（招聘软件发给HR，150-200字）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "职位唯一 ID",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "interview_prep",
            "description": "为职位生成面试准备问题（技术+行为+项目深挖）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "职位唯一 ID",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_offer",
            "description": "综合评估一个 Offer：竞争力、成长性、风险、薪资分析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称",
                    },
                    "title": {
                        "type": "string",
                        "description": "职位名称",
                    },
                    "salary": {
                        "type": "string",
                        "description": "薪资，如 '25K*15'",
                    },
                    "location": {
                        "type": "string",
                        "description": "工作地点",
                    },
                    "bonus": {
                        "type": "string",
                        "description": "奖金/股票",
                    },
                    "benefits": {
                        "type": "string",
                        "description": "福利",
                    },
                    "level": {
                        "type": "string",
                        "description": "职级",
                    },
                    "notes": {
                        "type": "string",
                        "description": "备注",
                    },
                },
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "salary_advice",
            "description": "薪资谈判策略建议：锚点、筹码、让步方案、话术。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称",
                    },
                    "title": {
                        "type": "string",
                        "description": "职位名称",
                    },
                    "salary": {
                        "type": "string",
                        "description": "当前薪资/Offer薪资",
                    },
                    "target": {
                        "type": "string",
                        "description": "期望薪资，如 '30K' 或 '涨幅30%'",
                    },
                    "strengths": {
                        "type": "string",
                        "description": "个人优势",
                    },
                    "context": {
                        "type": "string",
                        "description": "补充背景信息",
                    },
                },
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_cookies",
            "description": "检查各招聘平台 cookie 健康状态（是否过期、需要重抓）。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_detail",
            "description": "获取单个职位的详细信息（JD、薪资、地点等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "职位唯一 ID",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class ToolDispatcher:
    """Routes tool calls to the corresponding pipeline/tracking functions.

    Holds references to config, db, and provider — initialized once at REPL
    startup and reused across all tool invocations.
    """

    _MAX_SEARCH_ROUNDS = 7  # cap on search_jobs calls per conversation turn

    def __init__(self, config: Any, db: sqlite3.Connection, provider: Any) -> None:
        self.config = config
        self.db = db
        self.provider = provider
        self._search_rounds = 0

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return a text result for the LLM.

        Async tool methods are awaited directly (no asyncio.run wrapping).
        Exceptions are caught and returned as error text (never crash the REPL loop).
        """
        try:
            if name == "search_jobs":
                return await self._search_jobs(arguments)
            elif name == "list_tracked_applications":
                return self._list_tracked_applications(arguments)
            elif name == "add_application":
                return self._add_application(arguments)
            elif name == "update_application_status":
                return self._update_application_status(arguments)
            elif name == "tailor_resume":
                return await self._tailor_resume(arguments)
            elif name == "generate_cover_letter":
                return await self._generate_cover_letter(arguments)
            elif name == "interview_prep":
                return await self._interview_prep(arguments)
            elif name == "evaluate_offer":
                return await self._evaluate_offer(arguments)
            elif name == "salary_advice":
                return await self._salary_advice(arguments)
            elif name == "check_cookies":
                return await self._check_cookies()
            elif name == "get_job_detail":
                return self._get_job_detail(arguments)
            else:
                return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return json.dumps({"error": f"工具 {name} 执行失败: {e}"}, ensure_ascii=False)

    # -- tool implementations ------------------------------------------------

    async def _search_jobs(self, args: dict[str, Any]) -> str:
        self._search_rounds += 1
        if self._search_rounds > self._MAX_SEARCH_ROUNDS:
            return (
                f"已达到搜索上限（{self._MAX_SEARCH_ROUNDS} 轮），"
                f"这是最后一次搜索机会，请充分利用。"
            )
        keywords: list[str] = args.get("keywords", [])
        location: str = args.get("location", "") or self.config.search_location
        platform_raw: str = (args.get("platform") or "").strip()
        company_filter: str = (args.get("company") or "").strip()
        min_salary: int = args.get("min_salary", 0) or 0
        max_results: int = args.get("max_results", 15) or 15
        education: str = args.get("education", "") or ""
        days_old: int = args.get("days_old", 0) or 0

        # Parse platform string into list
        if platform_raw:
            platform_names = [p.strip() for p in platform_raw.split(",") if p.strip()]
        else:
            platform_names = None

        from agent_core.pipeline.search import filter_by_company, search_all

        jobs = await search_all(
            self.config,
            platform_names=platform_names,
            directions=None,
            keywords=keywords if keywords else None,
        )
        # Filter by location (fuzzy)
        if location and location != "全国":
            loc_lower = location.lower()
            jobs = [j for j in jobs if loc_lower in (j.location or "").lower()]

        # Filter by min salary (monthly, in K). A job qualifies when EITHER
        # bound reaches the expectation — single-sided salaries (only min or
        # only max) must not be dropped, only fully unknown salaries are.
        if min_salary > 0:
            min_k = min_salary * 1000
            jobs = [
                j
                for j in jobs
                if (j.salary_max is not None and j.salary_max >= min_k)
                or (j.salary_min is not None and j.salary_min >= min_k)
            ]

        # Filter by company name (case-insensitive substring)
        before_company = len(jobs)
        if company_filter:
            jobs = filter_by_company(jobs, company_filter)

        # Filter by education requirement (if platform provides it — best-effort)
        if education and education != "不限":
            edu_lower = education.lower()
            jobs = [j for j in jobs if not j.education or edu_lower in j.education.lower()]

        # Filter by days_old (published within N days).
        # Prefer platform-reported published_at; fall back to first_seen
        # (agent discovery time) when the platform provides no publish date.
        # Jobs with an unknown date are KEPT (conservative: never silently
        # drop a job just because no publish date was reported).
        if days_old > 0:
            from datetime import datetime, timedelta

            cutoff = datetime.now(UTC) - timedelta(days=days_old)
            filtered_jobs: list = []
            for j in jobs:
                ref_time = _parse_platform_date(getattr(j, "published_at", "") or "")
                if ref_time is None:
                    fs = getattr(j, "first_seen", "")
                    ref_time = _parse_platform_date(fs) if isinstance(fs, str) else fs
                if ref_time is None or ref_time >= cutoff:
                    filtered_jobs.append(j)
            jobs = filtered_jobs

        # Keyword relevance is guarded centrally by search.search_all().

        # Save to DB so dashboard sees cumulative results
        if jobs:
            try:
                from agent_core.pipeline.orchestrator import _save_jobs_to_db

                _save_jobs_to_db(jobs)
            except Exception as e:
                logger.warning(f"Failed to save jobs to DB: {e}")

        # Sort by salary descending, limit to max_results
        jobs.sort(key=lambda j: j.salary_max or 0, reverse=True)
        top = jobs[:max_results]

        # Close Zhilian browser after search to avoid leaving Chrome windows open
        try:
            from agent_core.platforms.zhilian_browser import close_browser

            await close_browser()
        except Exception:
            pass

        results = []
        for j in top:
            salary_str = ""
            if j.salary_min and j.salary_max:
                salary_str = f"{j.salary_min // 1000}K-{j.salary_max // 1000}K"
            elif j.salary_min:
                salary_str = f"{j.salary_min // 1000}K+"
            results.append(
                {
                    "id": j.id,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "salary": salary_str,
                    "direction": j.direction,
                }
            )
        total = len(jobs)
        payload: dict[str, Any] = {
            "total": total,
            "shown": len(results),
            "jobs": results,
        }
        if min_salary > 0:
            payload["min_salary_K"] = min_salary
        if education:
            payload["education"] = education
        if days_old > 0:
            payload["days_old"] = days_old
        if company_filter:
            payload["company_filter"] = company_filter
            payload["company_filter_before"] = before_company
        return json.dumps(payload, ensure_ascii=False)

    def _list_tracked_applications(self, args: dict[str, Any]) -> str:
        from agent_core.tracking.tracker import list_applications

        status_filter: str | None = args.get("status_filter")
        apps = list_applications(self.db, status_filter)
        if not apps:
            label = f" (筛选: {status_filter})" if status_filter else ""
            return f"暂无投递记录{label}。"
        results = []
        for a in apps[:20]:
            results.append(
                {
                    "id": a["id"],
                    "status": a["status"],
                    "job_title": a.get("job_title", "?"),
                    "company": a.get("job_company", "?"),
                    "applied_at": a.get("applied_at", ""),
                }
            )
        return json.dumps(
            {"total": len(apps), "shown": len(results), "applications": results},
            ensure_ascii=False,
        )

    def _add_application(self, args: dict[str, Any]) -> str:
        from agent_core.tracking.tracker import add_application

        job_id: str = args.get("job_id", "")
        if not job_id:
            return json.dumps({"error": "job_id 不能为空"}, ensure_ascii=False)
        aid = add_application(self.db, job_id)
        return json.dumps(
            {"ok": True, "application_id": aid, "message": f"已记录投递 #{aid}，状态：已投递"},
            ensure_ascii=False,
        )

    def _update_application_status(self, args: dict[str, Any]) -> str:
        from agent_core.tracking.tracker import update_status

        app_id: int = int(args.get("app_id", 0))
        status: str = args.get("status", "")
        if not app_id or not status:
            return json.dumps({"error": "app_id 和 status 不能为空"}, ensure_ascii=False)
        try:
            result = update_status(self.db, app_id, status)
            return json.dumps(
                {
                    "ok": True,
                    "application_id": app_id,
                    "new_status": result["status"],
                    "job_title": result.get("job_title", ""),
                    "company": result.get("job_company", ""),
                },
                ensure_ascii=False,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def _tailor_resume(self, args: dict[str, Any]) -> str:
        job_id: str = args.get("job_id", "")
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return json.dumps({"error": f"职位不存在: {job_id}"}, ensure_ascii=False)
        from agent_core.platforms.base import Job

        job = Job.from_storage(row)

        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.pipeline.file_catalog import TYPE_TAILORED_RESUME, catalog_file
        from agent_core.pipeline.tailor import save_resume, tailor_resume

        enriched = await enrich_job_jd(job, self.config)
        text = await tailor_resume(enriched, self.config, self.provider)
        paths = save_resume(text, enriched)
        # Catalog both files (.md + .docx) so the dashboard can show
        # "this resume belongs to {job_title} @ {company}" without guessing
        # from the filename. Without this the dashboard scan mislabels any
        # stray .md in output/ as a tailored resume.
        for p in (paths["md"], paths["docx"]):
            catalog_file(
                self.db,
                job_id,
                TYPE_TAILORED_RESUME,
                p,
                direction=enriched.direction,
                company=enriched.company,
                job_title=enriched.title,
            )
        preview = text[:500] + ("..." if len(text) > 500 else "")
        return json.dumps(
            {
                "ok": True,
                "job_title": enriched.title,
                "company": enriched.company,
                "docx_path": paths["docx"],
                "md_path": paths["md"],
                "preview": preview,
            },
            ensure_ascii=False,
        )

    async def _generate_cover_letter(self, args: dict[str, Any]) -> str:
        job_id: str = args.get("job_id", "")
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return json.dumps({"error": f"职位不存在: {job_id}"}, ensure_ascii=False)
        from agent_core.platforms.base import Job

        job = Job.from_storage(row)

        from agent_core.pipeline.cover_letter import generate_cover_letter, save_cover_letter
        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.pipeline.file_catalog import TYPE_COVER_LETTER, catalog_file

        enriched = await enrich_job_jd(job, self.config)
        text = await generate_cover_letter(enriched, self.config, self.provider)
        path = save_cover_letter(text, enriched)
        catalog_file(
            self.db,
            job_id,
            TYPE_COVER_LETTER,
            path,
            direction=enriched.direction,
            company=enriched.company,
            job_title=enriched.title,
        )
        return json.dumps(
            {
                "ok": True,
                "job_title": enriched.title,
                "company": enriched.company,
                "path": path,
                "preview": text[:500],
            },
            ensure_ascii=False,
        )

    async def _interview_prep(self, args: dict[str, Any]) -> str:
        job_id: str = args.get("job_id", "")
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return json.dumps({"error": f"职位不存在: {job_id}"}, ensure_ascii=False)
        from agent_core.platforms.base import Job

        job = Job.from_storage(row)

        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.pipeline.file_catalog import TYPE_INTERVIEW_PREP, catalog_file
        from agent_core.pipeline.interview_prep import predict_questions, save_interview_prep

        enriched = await enrich_job_jd(job, self.config)
        qs = await predict_questions(enriched, self.config, self.provider)
        path = save_interview_prep(qs, enriched)
        catalog_file(
            self.db,
            job_id,
            TYPE_INTERVIEW_PREP,
            path,
            direction=enriched.direction,
            company=enriched.company,
            job_title=enriched.title,
        )
        categories = ("technical", "behavioral", "project")
        total_q = sum(len(qs.get(c, [])) for c in categories)
        return json.dumps(
            {
                "ok": True,
                "job_title": enriched.title,
                "company": enriched.company,
                "total_questions": total_q,
                "path": path,
                "questions": qs,
            },
            ensure_ascii=False,
        )

    async def _evaluate_offer(self, args: dict[str, Any]) -> str:
        company: str = args.get("company", "")
        title: str = args.get("title", "")
        location: str = args.get("location", "")
        salary: str = args.get("salary", "")
        bonus: str = args.get("bonus", "")
        benefits: str = args.get("benefits", "")
        level: str = args.get("level", "")
        notes: str = args.get("notes", "")

        from agent_core.pipeline.offer_eval import evaluate

        r = await evaluate(
            self.config,
            self.provider,
            company,
            title,
            location,
            salary,
            bonus,
            benefits,
            level,
            notes,
        )
        return json.dumps(r, ensure_ascii=False)

    async def _salary_advice(self, args: dict[str, Any]) -> str:
        company: str = args.get("company", "")
        title: str = args.get("title", "")
        salary: str = args.get("salary", "")
        target: str = args.get("target", "")
        strengths: str = args.get("strengths", "")
        context: str = args.get("context", "")

        from agent_core.pipeline.salary_advice import get_advice

        r = await get_advice(
            self.config, self.provider, company, title, salary, target, strengths, context
        )
        return json.dumps(r, ensure_ascii=False)

    async def _check_cookies(self) -> str:
        from agent_core.cookie_health import check_cookies as _check_cookies_async

        results = await _check_cookies_async(self.config, probe=False)
        out = []
        for r in results:
            out.append(
                {
                    "platform": r.display_name,
                    "status": r.status_label,
                    "details": r.details[:5],
                }
            )
        return json.dumps({"platforms": out}, ensure_ascii=False)

    def _get_job_detail(self, args: dict[str, Any]) -> str:
        job_id: str = args.get("job_id", "")
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return json.dumps({"error": f"职位不存在: {job_id}"}, ensure_ascii=False)
        j = dict(row)
        # Truncate long description
        desc = j.get("description", "") or ""
        if len(desc) > 2000:
            desc = desc[:2000] + "..."
        return json.dumps(
            {
                "id": j["id"],
                "title": j["title"],
                "company": j["company"],
                "location": j.get("location", ""),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "description": desc,
                "direction": j.get("direction", ""),
                "first_seen": j.get("first_seen", ""),
                "last_seen": j.get("last_seen", ""),
            },
            ensure_ascii=False,
        )
