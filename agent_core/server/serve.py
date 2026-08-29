"""Local HTTP dashboard for the job-seeking agent.

Features:
- /                  -- Interactive HTML dashboard (10 tabs)
- /api/results       -- GET job listings (paginated, filterable)
- /api/flag/{id}     -- POST flag a job (interested/rejected/clear)
- /api/match, /api/jd/fetch, /api/materials/* -- match + materials pipeline
- /api/offer/*       -- offer evaluation, compare, save
- /api/mock-interview/* -- mock interview (SSE) + realtime voice proxy
- /api/openapi.json  -- OpenAPI 3.0 spec (partial; full route list in do_GET/do_POST/do_DELETE)
- /docs              -- Swagger UI

Auth: Bearer token via AGENT_DASHBOARD_TOKEN env var (dev-mode off when unset).
"""

# ruff: noqa: E501  -- inline CSS/JS/HTML templates, long lines by design

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_core.server.daemon import _ensure_dashboard as _ensure_dashboard  # noqa: F401
from agent_core.server.daemon import _stop_dashboard
from agent_core.server.dashboard_html import DOCS_HTML, HTML, OPENAPI_SPEC
from agent_core.server.http_utils import (
    _authenticate,
    _AuthRequired,
    _get_int_param,
    _read_json_body,
    _send_error,
    _send_html,
    _send_json,
    _table_exists,
)

logger = logging.getLogger(__name__)

# --- Batch operation progress (JD fetch / match) -------------------------------
# Module-level progress store shared across requests. A running batch writes
# {done, total, current, status} here; /api/jd/progress and /api/match/progress
# read it so the dashboard can render a live progress modal.
_JD_PROGRESS: dict = {"running": False, "done": 0, "total": 0, "current": "", "status": ""}
_MATCH_PROGRESS: dict = {"running": False, "done": 0, "total": 0, "current": "", "status": ""}
_MATERIALS_PROGRESS: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "current": "",
    "status": "",
}
_PROGRESS_LOCK = threading.Lock()


def _set_jd_progress(**kw) -> None:
    with _PROGRESS_LOCK:
        _JD_PROGRESS.update(kw)


def _set_match_progress(**kw) -> None:
    with _PROGRESS_LOCK:
        _MATCH_PROGRESS.update(kw)


def _set_materials_progress(**kw) -> None:
    with _PROGRESS_LOCK:
        _MATERIALS_PROGRESS.update(kw)


# --- Offer import template (17 fields, .txt) ----------------------------------
# Downloaded from the 文件上传 tab. Users fill it in and upload the .txt to
# offers/; /api/offer/evaluate LLM-parses it into 17 structured fields,
# folds the extras into `notes`, and calls evaluate() unchanged.
OFFER_TEMPLATE_TXT = """# Offer 信息模板
# 填写说明: 冒号后填写内容, 未涉及的留空或写"无"。
# 文件名建议: 公司名_职位名.txt

【基本信息】
公司名:
职位名:
工作地点:
Offer类型:(正式/实习/外包/劳务)
级别:
入职日期:

【薪酬】
月薪base:
发放月数:
年总包:
年终奖月数:
签字费:
期权/RSU:(股数+归属周期)
五险一金:(缴纳基数+比例, 是否按全额)

【条款】
试用期:(时长+试用期薪资比例)
工作模式:(现场/远程/混合)+工时
加班/出差/调岗条款:
竞业协议:(范围+期限+补偿)
离职通知期:

【其他】
福利:(餐补/房补/补充商业险/年假)
HR联系方式:(姓名/电话/邮箱)
备注:
"""

# 17 canonical offer fields the parser extracts. Order matches the template.
OFFER_FIELDS = [
    "company",
    "title",
    "location",
    "offer_type",
    "level",
    "join_date",
    "monthly_base",
    "pay_months",
    "annual_total",
    "year_end_months",
    "sign_bonus",
    "equity",
    "social_insurance",
    "probation",
    "work_mode",
    "overtime_travel",
    "non_compete",
    "notice_period",
    "perks",
    "hr_contact",
    "notes",
]


def _pack_offer_eval_input(parsed: dict) -> dict:
    """Map 17 parsed offer fields -> 8 evaluate() params.

    evaluate() consumes company/title/location/salary/bonus/benefits/level/
    notes. The extra structured fields are folded into salary/bonus/benefits/
    notes so the LLM sees the full offer context without changing evaluate()'s
    signature or EVAL_PROMPT.
    """

    def g(k):
        return (parsed.get(k) or "").strip()

    salary_bits = []
    if g("monthly_base"):
        salary_bits.append("月薪base=" + g("monthly_base"))
    if g("pay_months"):
        salary_bits.append("发放" + g("pay_months") + "个月")
    if g("annual_total"):
        salary_bits.append("年总包=" + g("annual_total"))
    bonus_bits = []
    if g("year_end_months"):
        bonus_bits.append("年终奖" + g("year_end_months") + "个月")
    if g("sign_bonus"):
        bonus_bits.append("签字费=" + g("sign_bonus"))
    if g("equity"):
        bonus_bits.append("期权/RSU=" + g("equity"))
    benefit_bits = []
    if g("social_insurance"):
        benefit_bits.append("五险一金:" + g("social_insurance"))
    if g("perks"):
        benefit_bits.append("福利:" + g("perks"))
    note_bits = []
    for label, key in [
        ("Offer类型", "offer_type"),
        ("入职日期", "join_date"),
        ("试用期", "probation"),
        ("工作模式", "work_mode"),
        ("加班/出差/调岗", "overtime_travel"),
        ("竞业协议", "non_compete"),
        ("离职通知期", "notice_period"),
        ("HR联系方式", "hr_contact"),
    ]:
        if g(key):
            note_bits.append(label + ":" + g(key))
    if g("notes"):
        note_bits.append(g("notes"))
    return {
        "company": g("company"),
        "title": g("title"),
        "location": g("location"),
        "salary": ", ".join(salary_bits),
        "bonus": ", ".join(bonus_bits),
        "benefits": "; ".join(benefit_bits),
        "level": g("level"),
        "notes": " | ".join(note_bits),
    }


async def _parse_offer_fields(provider, config, txt: str) -> dict:
    """LLM-parse raw offer txt into 17 structured fields. Returns dict keyed by OFFER_FIELDS."""
    import re

    from agent_core.llm.providers import call_llm_with_retry

    prompt = (
        "从以下 Offer 通知/录用邮件/聊天记录中提取结构化字段。若某字段未提及则返回空字符串。\n\n"
        "字段：company(公司名), title(职位名), location(工作地点), "
        "offer_type(正式/实习/外包/劳务), level(级别), join_date(入职日期), "
        "monthly_base(月薪base), pay_months(发放月数), annual_total(年总包), "
        "year_end_months(年终奖月数), sign_bonus(签字费), equity(期权/RSU), "
        "social_insurance(五险一金), probation(试用期), work_mode(工作模式+工时), "
        "overtime_travel(加班/出差/调岗), non_compete(竞业协议), "
        "notice_period(离职通知期), perks(福利), hr_contact(HR联系方式), notes(备注)\n\n"
        "Offer 文本：\n"
        f"{txt}\n\n"
        '返回严格 JSON，仅含上述字段：{{"company":"...","title":"...",...}}'
    )
    r = await call_llm_with_retry(
        provider,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=config.llm.max_tokens,
    )
    t = r.strip()
    if "```json" in t:
        t = t.split("```json")[1].split("```")[0].strip()
    elif "```" in t:
        t = t.split("```")[1].split("```")[0].strip()
    data = json.loads(re.sub(r",(\s*[}\]])", r"\1", t))
    return {k: str(data.get(k, "") or "") for k in OFFER_FIELDS}


def _scan_output_dir(output_dir="output"):
    """Scan the output directory and return file metadata list.

    Source of truth is the generated_files catalog table (v5+); the directory
    scan is only a backfill fallback for files written before cataloging existed
    or for files dropped into output/ by hand. Each cataloged row already
    carries job_id/job_title/company/file_type, so the dashboard can show
    "this resume belongs to {job}" -- which the bare filename scan never could.
    """
    from pathlib import Path

    # Try the catalog table first. It is authoritative when present.
    result = []
    try:
        from agent_core.storage.db import get_db

        conn = get_db(Handler.db_path) if Handler.db_path else None
        if conn is not None:
            rows = conn.execute(
                """
                SELECT file_name, file_path, size, created_at, file_type,
                       job_id, direction, company, job_title
                FROM generated_files
                ORDER BY created_at DESC
                """
            ).fetchall()
            for r in rows:
                # Skip rows whose file vanished from disk (deleted manually).
                if not Path(r["file_path"]).exists():
                    continue
                ext = os.path.splitext(r["file_name"])[1].lower()
                result.append(
                    {
                        "name": r["file_name"],
                        "ext": ext,
                        "size": r["size"] or 0,
                        "modified": r["created_at"],
                        "type": r["file_type"],
                        "job_id": r["job_id"],
                        "job_title": r["job_title"] or "",
                        "company": r["company"] or "",
                        "direction": r["direction"] or "",
                    }
                )
            if result:
                return result
    except Exception:
        pass  # fall through to directory scan

    # Fallback: raw directory scan with filename-guessed type (legacy path).
    try:
        p = Path(output_dir)
        if not p.is_dir():
            return result
        for fname in sorted(os.listdir(output_dir), reverse=True):
            fpath = p / fname
            if fpath.is_file():
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".md", ".docx"):
                    stat = os.stat(fpath)
                    file_type = _infer_file_type(fname)
                    result.append(
                        {
                            "name": fname,
                            "ext": ext,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "type": file_type,
                            "job_id": None,
                            "job_title": "",
                            "company": "",
                            "direction": "",
                        }
                    )
    except OSError:
        pass
    return result


def _infer_file_type(fname):
    """Infer which tool generated this file from its name pattern.

    Only used as the legacy fallback when no catalog row exists. Order is
    load-bearing: _mock_interview contains _interview, so the mock check
    MUST come first.
    """
    lower = fname.lower()
    if "_mock" in lower:
        return "mock_interview"
    if "_cover" in lower:
        return "cover_letter"
    if "_interview" in lower:
        return "interview_prep"
    return "tailor_resume"


def _serve_index(handler: BaseHTTPRequestHandler) -> None:
    """Serve the dashboard HTML, injecting the auth token for the browser.

    The API layer requires ``Authorization: Bearer <token>`` when
    AGENT_DASHBOARD_TOKEN is set. The HTML page is intentionally public (it is
    just the local UI shell), so we embed the same local token into a meta tag
    and the page's fetch wrapper attaches it automatically.
    """
    token = os.environ.get("AGENT_DASHBOARD_TOKEN", "").strip()
    html = HTML
    if token:
        meta = f'<meta name="dashboard-token" content="{token}">'
        html = html.replace("</head>", meta + "</head>", 1)
    _send_html(handler, html)


# Module-level cache for all_platforms (refreshed on job add/delete)
_platforms_cache: set[str] | None = None


def _cached_all_platforms() -> set[str]:
    """Return all unique platforms in the jobs table. Cached until invalidated."""
    global _platforms_cache
    if _platforms_cache is not None:
        return _platforms_cache
    import sqlite3 as _sqlite3

    all_plat: set[str] = set()
    try:
        conn3 = _sqlite3.connect(Handler.db_path or "data/agent.db")
        conn3.row_factory = _sqlite3.Row
        for r in conn3.execute(
            "SELECT platforms FROM jobs WHERE platforms IS NOT NULL AND platforms != '' AND platforms != '[]'"
        ).fetchall():
            raw = r["platforms"]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = [raw] if raw.strip() else []
            if isinstance(parsed, list):
                for p in parsed:
                    if p and isinstance(p, str):
                        all_plat.add(p)
            elif isinstance(parsed, str) and parsed.strip():
                all_plat.add(parsed)
        conn3.close()
    except Exception:
        logger.warning("_cached_all_platforms failed, will retry next request", exc_info=True)
        return set()  # don't cache on failure — retry next request
    if not all_plat:
        # Don't cache an empty set: the jobs table may be empty at startup
        # (fresh start / just-cleared), and caching it would permanently
        # hide the platform dropdown until the process restarts.
        return set()
    _platforms_cache = all_plat
    return all_plat


class Handler(BaseHTTPRequestHandler):
    db_path = "data/agent.db"

    def do_GET(self) -> None:  # noqa: N802
        """Route GET requests with auth check and global error handling."""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query)

            if path == "/api/results":
                self._require_auth()
                self._api_results(params)
            elif path == "/api/jd/view":
                self._require_auth()
                self._api_jd_view()
            elif path == "/api/jd/progress":
                self._require_auth()
                _send_json(self, dict(_JD_PROGRESS))
            elif path == "/api/match/progress":
                self._require_auth()
                _send_json(self, dict(_MATCH_PROGRESS))
            elif path == "/api/materials/progress":
                self._require_auth()
                _send_json(self, dict(_MATERIALS_PROGRESS))
            elif path == "/api/pipeline":
                self._require_auth()
                self._api_pipeline(params)
            elif path == "/api/match":
                self._require_auth()
                self._api_match(params)
            elif path == "/api/resumes":
                self._require_auth()
                self._api_list_resumes()
            elif path == "/api/resume/preview":
                self._require_auth()
                self._api_resume_preview(params)
            elif path == "/api/files":
                self._require_auth()
                self._api_files()
            elif path == "/api/offer/template":
                self._require_auth()
                self._api_offer_template()
            elif path == "/api/offer/list":
                self._require_auth()
                self._api_offer_list()
            elif path == "/api/realtime/config":
                self._require_auth()
                self._api_realtime_config()
            elif path == "/api/offer/preview":
                self._require_auth()
                self._api_offer_preview(params)
            elif path == "/api/materials/drafts":
                self._require_auth()
                self._api_materials_drafts()
            elif path == "/api/materials/jobs":
                self._require_auth()
                self._api_materials_jobs()
            elif path == "/api/applications":
                self._require_auth()
                self._api_applications()
            elif path == "/api/file":
                self._require_auth()
                self._api_file_content(params)
            elif path == "/api/openapi.json":
                self._serve_openapi()
            elif path == "/docs":
                _send_html(self, DOCS_HTML)
            elif path == "/api/mock-interview/latest-transcript":
                self._require_auth()
                self._api_mock_latest_transcript(params)
            elif path == "/api/mock-assessment/preview":
                self._require_auth()
                self._api_mock_assessment_preview(params)
            elif path == "/":
                _serve_index(self)
            else:
                _send_error(self, 404, "Not Found", f"No route for {path}")
        except _AuthRequired:
            pass
        except Exception:
            logger.exception("Unhandled error serving %s", self.path)
            _send_error(self, 500, "Internal Server Error")

    def do_DELETE(self) -> None:  # noqa: N802
        """Route DELETE requests."""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query)
            if path == "/api/results":
                self._require_auth()
                self._api_clear_results()
            elif path == "/api/match/feedback":
                self._require_auth()
                self._api_clear_match_feedback()
            elif path == "/api/match":
                self._require_auth()
                self._api_clear_match()
            elif path == "/api/application":
                self._require_auth()
                self._api_delete_application(params)
            elif path == "/api/materials":
                self._require_auth()
                self._api_materials_delete()
            elif path == "/api/file":
                self._require_auth()
                self._api_delete_file(params)
            elif path == "/api/offer":
                self._require_auth()
                self._api_offer_delete(params)
            elif path.startswith("/api/resume"):
                self._require_auth()
                self._api_delete_resume(path, params)
            elif path.startswith("/api/flag/"):
                self._require_auth()
                self._api_flag_job(path)
            else:
                _send_error(self, 404, "Not Found", f"No DELETE route for {path}")
        except _AuthRequired:
            pass
        except Exception:
            logger.exception("Unhandled error serving %s", self.path)
            _send_error(self, 500, "Internal Server Error")

    def do_POST(self) -> None:  # noqa: N802
        """Route POST requests (job flagging, match, JD fetch, resume)."""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/flag/batch":
                self._require_auth()
                self._api_flag_batch()
            elif path.startswith("/api/flag/"):
                self._require_auth()
                self._api_flag_job(path)
            elif path == "/api/match/run":
                self._require_auth()
                self._api_match_run()
            elif path == "/api/jd/fetch":
                self._require_auth()
                self._api_jd_fetch()
            elif path == "/api/jd/manual":
                self._require_auth()
                self._api_jd_manual()
            elif path == "/api/match/feedback":
                self._require_auth()
                self._api_match_feedback()
            elif path == "/api/materials/generate":
                self._require_auth()
                self._api_materials_generate()
            elif path == "/api/materials/regenerate":
                self._require_auth()
                self._api_materials_regenerate()
            elif path == "/api/materials/confirm":
                self._require_auth()
                self._api_materials_confirm()
            elif path == "/api/application":
                self._require_auth()
                self._api_application_create()
            elif path == "/api/application/update":
                self._require_auth()
                self._api_application_update()
            elif path == "/api/application/reminder":
                self._require_auth()
                self._api_application_reminder()
            elif path == "/api/resume/upload":
                self._require_auth()
                self._api_resume_upload()
            elif path == "/api/resume/default":
                self._require_auth()
                self._api_resume_set_default()
            elif path == "/api/mock-interview/start":
                self._require_auth()
                self._api_mock_interview_start()
            elif path == "/api/mock-interview/reply":
                self._require_auth()
                self._api_mock_interview_reply()
            elif path == "/api/mock-interview/end":
                self._require_auth()
                self._api_mock_interview_end()
            elif path == "/api/mock-interview/abandon":
                self._require_auth()
                self._api_mock_interview_abandon()
            elif path == "/api/offer/upload":
                self._require_auth()
                self._api_offer_upload()
            elif path == "/api/offer/evaluate":
                self._require_auth()
                self._api_offer_evaluate()
            elif path == "/api/offer/compare":
                self._require_auth()
                self._api_offer_compare()
            elif path == "/api/offer/compare/save":
                self._require_auth()
                self._api_offer_compare_save()
            elif path == "/api/offer/save":
                self._require_auth()
                self._api_offer_save()
            elif path == "/api/salary-advice":
                self._require_auth()
                self._api_salary_advice()
            elif path == "/api/salary-advice/save":
                self._require_auth()
                self._api_salary_advice_save()
            elif path == "/api/files/zip":
                self._require_auth()
                self._api_files_zip()
            else:
                _send_error(self, 404, "Not Found", f"No POST route for {path}")
        except _AuthRequired:
            pass
        except Exception:
            logger.exception("Unhandled error serving %s", self.path)
            _send_error(self, 500, "Internal Server Error")

    def _require_auth(self) -> None:
        """Check auth; raise _AuthRequired if forbidden."""
        allowed, err = _authenticate(self)
        if not allowed:
            _send_error(self, 401, err or "Unauthorized")
            raise _AuthRequired()

    # ------------------------------------------------------------------ API ---
    def _api_results(self, params: dict[str, list[str]]) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        page = _get_int_param(params, "page", 0)
        page_size = _get_int_param(params, "page_size", 30)

        if page > 0:
            # Paginated mode
            platform_filter = params.get("platform", [""])[0]
            company_filter = params.get("company", [""])[0]
            title_filter_raw = params.get("title", [""])[0]
            location_filter = params.get("location", [""])[0]
            where_clauses: list[str] = []
            where_params: list[Any] = []
            if platform_filter:
                where_clauses.append("platforms LIKE ?")
                where_params.append(f'%"{platform_filter}"%')
            if company_filter:
                where_clauses.append("company LIKE ?")
                where_params.append(f"%{company_filter}%")
            if title_filter_raw:
                # Broad LIKE pre-filter (cheap), then refined with exact
                # full-match logic below.
                where_clauses.append("title LIKE ?")
                where_params.append(f"%{title_filter_raw}%")
            if location_filter:
                where_clauses.append("location LIKE ?")
                where_params.append(f"%{location_filter}%")
            user_flag_filter = params.get("user_flag", [""])[0]
            if user_flag_filter in ("interested", "rejected"):
                where_clauses.append("user_flag = ?")
                where_params.append(user_flag_filter)
            elif user_flag_filter == "unmarked":
                where_clauses.append("(user_flag IS NULL OR user_flag = '')")
            where_clause = ""
            if where_clauses:
                where_clause = " WHERE " + " AND ".join(where_clauses)
            # Fetch all rows matching the broad filter, then refine title in
            # Python with CJK-aware word-boundary matching, then paginate.
            all_rows = conn.execute(
                f"SELECT * FROM jobs{where_clause} ORDER BY last_seen DESC",
                where_params,
            ).fetchall()
            conn.close()
            # Build strict full-match filter: input must equal the title
            # EXACTLY (after trimming whitespace). "设备工程师" matches only
            # jobs whose title is exactly "设备工程师" -- not "涂布设备工程师",
            # not "SMT设备工程师", not "设备工程师(J10544)".
            tokens = [t for t in title_filter_raw.split() if t] if title_filter_raw else []
            if tokens:
                # If multiple tokens (space-separated), require the title to
                # equal one of them exactly (OR semantics, like a quick multi-
                # select). Single token = exact equality.
                refined = [r for r in all_rows if (r["title"] or "").strip() in tokens]
            else:
                refined = all_rows
            total = len(refined)
            if page_size <= 0:
                page_size = max(total, 1)
            pages = max(1, (total + page_size - 1) // page_size)
            offset = (page - 1) * page_size
            rows = refined[offset : offset + page_size]
            # Collect all unique platforms (cached per-request)
            all_plat = _cached_all_platforms()
            _send_json(
                self,
                {
                    "items": [dict(r) for r in rows],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "pages": pages,
                    "all_platforms": sorted(all_plat),
                },
            )
        else:
            # Legacy flat-list mode (backward compatible)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM jobs ORDER BY last_seen DESC LIMIT 200").fetchall()
            conn.close()
            _send_json(self, [dict(r) for r in rows])

    def _api_clear_results(self) -> None:
        """DELETE /api/results -- clear all jobs and search status from the dashboard."""
        global _platforms_cache
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM jobs")
            conn.execute("DELETE FROM search_status")
            # Pipeline stage history is derived from jobs/match/files; clearing
            # all job data should reset the stage cards too (no ghost timestamps).
            conn.execute("DELETE FROM pipeline_runs")
            conn.commit()
            conn.close()
            _platforms_cache = None  # invalidate platform cache
            _send_json(self, {"ok": True})
        except Exception as e:
            logger.exception("Failed to clear results")
            _send_error(self, 500, f"Clear failed: {e}")

    def _api_clear_match(self) -> None:
        """DELETE /api/match -- clear all LLM match results from the dashboard."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("DELETE FROM match_results")
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            logger.info("Cleared %d match_results rows", deleted)
            _send_json(self, {"ok": True, "deleted": deleted})
        except Exception as e:
            logger.exception("Failed to clear match results")
            _send_error(self, 500, f"Clear failed: {e}")

    def _api_list_resumes(self) -> None:
        """GET /api/resumes -- list resume files in the resumes/ directory.

        The `default` field reflects what's actually registered in
        config.yaml's search.directions.default.resume_file (not just the
        first file by name), so the dashboard star stays in sync after
        set-default / delete operations.
        """
        import os

        resumes_dir = self._resumes_dir()
        items = []
        if os.path.isdir(resumes_dir):
            for name in sorted(os.listdir(resumes_dir)):
                full = os.path.join(resumes_dir, name)
                if os.path.isfile(full) and name.lower().endswith((".txt", ".md")):
                    try:
                        size = os.path.getsize(full)
                        mtime = int(os.path.getmtime(full))
                    except OSError:
                        size, mtime = 0, 0
                    items.append({"name": name, "size": size, "mtime": mtime})
        # Read the configured default from config.yaml
        default_name = None
        try:
            default_name = self._read_default_resume_name()
        except Exception:
            pass
        # Fallback: if config has no default but files exist, pick the first
        if not default_name and items:
            default_name = items[0]["name"]
        # Verify the configured default actually exists on disk; if not, None
        if default_name and not any(i["name"] == default_name for i in items):
            default_name = items[0]["name"] if items else None
        _send_json(self, {"items": items, "default": default_name})

    def _read_default_resume_name(self):
        """Return the basename of the configured default resume, or None."""
        import os

        try:
            import yaml  # type: ignore
        except ImportError:
            return None
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg_path = os.path.join(root, "config.yaml")
        if not os.path.isfile(cfg_path):
            return None
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        dirs = (cfg.get("search") or {}).get("directions") or {}
        cur = (dirs.get("default") or {}).get("resume_file") or ""
        return os.path.basename(cur) if cur else None

    def _api_delete_resume(self, path: str, params: dict) -> None:
        """DELETE /api/resume?name=<filename> -- remove a resume file.

        Also clears the 'default' direction in config.yaml if it pointed at
        the deleted file, so load_resume() falls back to the next available
        resume instead of raising FileNotFoundError.
        """
        import os

        names = params.get("name", [])
        if not names:
            _send_error(self, 400, "Missing 'name' query param")
            return
        name = names[0]
        safe = os.path.basename(name)
        if not safe or safe in (".", ".."):
            _send_error(self, 400, "Invalid filename")
            return
        full = os.path.join(self._resumes_dir(), safe)
        deleted = False
        if os.path.isfile(full):
            os.remove(full)
            deleted = True
        # Clear default direction if it pointed at this file
        try:
            self._clear_default_resume_if_matches(safe)
        except Exception as e:
            logger.warning("Config cleanup failed: %s", e)
        _send_json(self, {"ok": True, "deleted": deleted, "name": safe})

    def _clear_default_resume_if_matches(self, filename: str) -> None:
        """Remove the 'default' direction entry if its resume_file points at
        the given filename, OR fall back to another resume if any remain."""
        import os

        try:
            import yaml  # type: ignore
        except ImportError:
            return
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg_path = os.path.join(root, "config.yaml")
        if not os.path.isfile(cfg_path):
            return
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        search = cfg.get("search") or {}
        dirs = search.get("directions") or {}
        default = dirs.get("default") or {}
        cur = default.get("resume_file", "")
        if cur.endswith(filename) or not os.path.isfile(
            os.path.join(self._resumes_dir(), os.path.basename(cur))
        ):
            # pick a replacement if other resumes exist
            try:
                remaining = [
                    f
                    for f in sorted(os.listdir(self._resumes_dir()))
                    if f.lower().endswith((".txt", ".md"))
                    and os.path.isfile(os.path.join(self._resumes_dir(), f))
                ]
            except OSError:
                remaining = []
            if remaining:
                default["resume_file"] = f"resumes/{remaining[0]}"
            else:
                dirs.pop("default", None)
            with open(cfg_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(
                    cfg, fh, allow_unicode=True, sort_keys=False, default_flow_style=False
                )

    def _api_resume_preview(self, params: dict) -> None:
        """GET /api/resume/preview?name=<filename> -- return resume text content."""
        import os

        names = params.get("name", [])
        if not names:
            _send_error(self, 400, "Missing 'name' query param")
            return
        safe = os.path.basename(names[0])
        if not safe or safe in (".", ".."):
            _send_error(self, 400, "Invalid filename")
            return
        full = os.path.join(self._resumes_dir(), safe)
        if not os.path.isfile(full):
            _send_error(self, 404, "Resume not found", safe)
            return
        try:
            content = open(full, encoding="utf-8").read()
        except Exception as e:
            _send_error(self, 500, f"Read failed: {e}")
            return
        _send_json(self, {"ok": True, "name": safe, "content": content, "size": len(content)})

    def _api_resume_set_default(self) -> None:
        """POST /api/resume/default -- set a resume as the default direction.

        Body (JSON): {"name": "<filename>.txt"}
        Updates config.yaml's search.directions.default.resume_file.
        """
        import os

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 1024 * 1024:
            _send_error(self, 400, "Invalid content length")
            return
        data = _read_json_body(self)
        if not data and length > 0:
            _send_error(self, 400, "Invalid JSON body")
            return
        name = (data.get("name") or "").strip()
        if not name:
            _send_error(self, 400, "Missing 'name'")
            return
        import re

        safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" .")
        low = safe.lower()
        if not (low.endswith(".txt") or low.endswith(".md") or low.endswith(".text")):
            safe = safe + ".txt"
        full = os.path.join(self._resumes_dir(), safe)
        if not os.path.isfile(full):
            _send_error(self, 404, "Resume not found", safe)
            return
        try:
            ok = self._register_resume_in_config(safe)
        except Exception as e:
            _send_error(self, 500, f"Config update failed: {e}")
            return
        _send_json(self, {"ok": True, "default": safe, "registered": ok})

    def _api_resume_upload(self) -> None:
        """POST /api/resume/upload -- save an uploaded resume text file.

        Body (JSON): {"name": "<filename>.txt", "content": "<resume text>"}
        Optional: "set_default": true -- register as the default direction in
        config.yaml's search.directions so load_resume() finds it.

        The fixed directions (industrial_ai_agent / equipment_amr) were
        removed per user request; resumes are now user-supplied only.
        """
        import os
        import re

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 5 * 1024 * 1024:  # 5MB cap
            _send_error(self, 400, "Invalid content length (1B-5MB allowed)")
            return
        data = _read_json_body(self)
        if not data and length > 0:
            _send_error(self, 400, "Invalid JSON body")
            return
        name = (data.get("name") or "").strip()
        content = data.get("content") or ""
        set_default = bool(data.get("set_default", False))
        if not name:
            _send_error(self, 400, "Missing 'name'")
            return
        if not content.strip():
            _send_error(self, 400, "Missing 'content'")
            return
        # Sanitize filename: keep alnum/_-/. and CJK via underscore-substitution
        # of path separators & unsafe chars. Preserve the user's original
        # extension (.txt / .md / .text) -- per user request the uploaded
        # resume must keep its original filename, not be renamed.
        safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" .")
        if not safe:
            safe = "resume.txt"
        low = safe.lower()
        if not (low.endswith(".txt") or low.endswith(".md") or low.endswith(".text")):
            # No recognized text extension -- append .txt so downstream text
            # tooling still classifies it, but otherwise keep the original name.
            safe = safe + ".txt"
        resumes_dir = self._resumes_dir()
        os.makedirs(resumes_dir, exist_ok=True)
        full = os.path.join(resumes_dir, safe)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Saved resume %s (%d bytes)", full, len(content))

        # Register in config.yaml as the default direction so load_resume()
        # can find it. We use a single canonical direction name "default".
        registered = False
        try:
            if set_default:
                registered = self._register_resume_in_config(safe)
        except Exception as e:
            logger.warning("Resume saved but config update failed: %s", e)

        _send_json(
            self,
            {
                "ok": True,
                "name": safe,
                "size": len(content),
                "path": os.path.relpath(full, os.getcwd()),
                "registered_default": registered,
            },
        )

    def _resumes_dir(self) -> str:
        """Absolute path to the resumes/ directory (project root / resumes)."""
        import os

        # project root = parent of agent_core/
        here = os.path.dirname(os.path.abspath(__file__))  # .../agent_core/server
        root = os.path.dirname(os.path.dirname(here))
        return os.path.join(root, "resumes")

    def _offers_dir(self) -> str:
        """Absolute path to the offers/ directory (project root / offers).

        Uploaded offer .txt input files live here, mirroring resumes/. They are
        NOT cataloged into generated_files (they are inputs, not artifacts) so
        they don't clutter the 已生成文件 tab; /api/offer/list scans this dir.
        """
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))
        return os.path.join(root, "offers")

    def _register_resume_in_config(self, resume_filename: str) -> bool:
        import os

        try:
            import yaml  # type: ignore
        except ImportError:
            return False
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg_path = os.path.join(root, "config.yaml")
        if not os.path.isfile(cfg_path):
            return False
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        search = cfg.setdefault("search", {})
        dirs = search.setdefault("directions", {})
        # Remove the legacy fixed directions if they still linger -- the user
        # wants resumes to be the single source of truth.
        for legacy in ("industrial_ai_agent", "equipment_amr"):
            dirs.pop(legacy, None)
        d = dirs.setdefault("default", {})
        d["resume_file"] = f"resumes/{resume_filename}"
        d.setdefault("keywords", [])
        with open(cfg_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return True

    def _api_pipeline(self, params=None):
        """GET /api/pipeline -- return pipeline stage summaries with counts and timestamps."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            matched = conn.execute("SELECT COUNT(*) FROM match_results").fetchone()[0]
            stages = {}
            for row in conn.execute(
                "SELECT stage, MAX(created_at) AS last_run, MAX(job_count) AS cnt"
                " FROM pipeline_runs GROUP BY stage ORDER BY stage"
            ).fetchall():
                stages[row["stage"]] = {
                    "last_run": row["last_run"],
                    "count": row["cnt"],
                }
            files = _scan_output_dir()
            track_count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            # materials stage: `count` shows pending-review drafts; `done` means
            # at least one draft was confirmed (审核通过), so an all-confirmed
            # board renders green instead of grey.
            materials_count = (
                conn.execute(
                    "SELECT COUNT(*) FROM material_drafts WHERE status='draft'"
                ).fetchone()[0]
                if _table_exists(conn, "material_drafts")
                else 0
            )
            materials_confirmed = (
                conn.execute(
                    "SELECT COUNT(*) FROM material_drafts WHERE status='confirmed'"
                ).fetchone()[0]
                if _table_exists(conn, "material_drafts")
                else 0
            )
            interested_count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE user_flag = 'interested'"
            ).fetchone()[0]
            rejected_count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE user_flag = 'rejected'"
            ).fetchone()[0]

            def _count_mock_sessions(items):
                """按“面试场次”统计 mock 产物，而不是按文件数。

                一场面试会生成 transcript(.md) + assessment(_assessment.txt) 两个文件；
                文字面试文件名含 mock_interview，实时语音文件名含 realtime_mock。
                这里把同一 base 的 transcript/assessment 归并成 1 次。
                """
                keys = set()
                for f in items:
                    name = f.get("name") or ""
                    lower = name.lower()
                    if f.get("type") != "mock_interview" and "_mock" not in lower:
                        continue
                    stem = os.path.splitext(lower)[0]
                    if stem.endswith("_assessment"):
                        stem = stem[: -len("_assessment")]
                    keys.add(stem)
                return len(keys)

            search_status_rows = []
            try:
                latest = conn.execute(
                    "SELECT search_id FROM search_status ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if latest:
                    for row in conn.execute(
                        "SELECT platform, status, result_count, error_message "
                        "FROM search_status WHERE search_id=? ORDER BY id",
                        (latest[0],),
                    ).fetchall():
                        search_status_rows.append(dict(row))
            except Exception:
                logger.warning("Failed to read search_status", exc_info=True)

            _send_json(
                self,
                {
                    "search_status": search_status_rows,
                    "stages": {
                        "search": {
                            "label": "🔍 搜索",
                            "count": total_jobs,
                            "done": total_jobs > 0,
                            "last_run": stages.get("search", {}).get("last_run"),
                        },
                        "filter": {
                            "label": "👤 人工筛选",
                            "count": interested_count,
                            "done": interested_count > 0,
                            "last_run": None,
                            "hint": f"{rejected_count} 个不合适",
                        },
                        "match": {
                            "label": "🧠 Agent智能匹配",
                            "count": matched,
                            "done": matched > 0,
                            "last_run": stages.get("match", {}).get("last_run"),
                        },
                        "tailor": {
                            "label": "📝 生成求职材料",
                            "count": len(files),
                            "done": len(files) > 0,
                            "last_run": None,
                            "hint": "针对精选岗位生成定制简历",
                        },
                        "materials": {
                            "label": "📋 材料审核台",
                            "count": materials_count + materials_confirmed,
                            "done": materials_confirmed > 0,
                            "last_run": None,
                            "hint": "简历+HR消息草稿（含已确认）",
                        },
                        "track": {
                            "label": "📮 投递追踪",
                            "count": track_count,
                            "done": track_count > 0,
                            "last_run": None,
                            "hint": "记录投递状态并跟进进度",
                        },
                    },
                    "post_counts": {
                        "mock": _count_mock_sessions(files),
                        "offer": sum(1 for f in files if f["type"] == "offer_eval"),
                        "salary": sum(1 for f in files if f["type"] == "salary_advice"),
                    },
                },
            )
        finally:
            conn.close()

    def _api_match_run(self):
        """POST /api/match/run -- trigger LLM matching on user-flagged (🌟) jobs.

        Loads all jobs with user_flag='interested' from the DB, runs the
        match pipeline (match.match_jobs), persists results to match_results,
        and returns a summary. Runs synchronously (may take a while for many
        jobs; concurrency is handled inside match_jobs).
        """
        import asyncio

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline import match as match_mod
        from agent_core.pipeline.orchestrator import _save_match_to_db
        from agent_core.storage.db import get_db

        # load_config() reads config.yaml and populates directions /
        # matching config; raw Config() would leave directions empty.
        config = load_config()
        # thinking enabled/effort come from config.llm.thinking -- the
        # yaml is the single source of truth for thinking mode.
        provider = create_provider(config, thinking_effort="max")

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, title, company, location, salary_min, salary_max, "
                "description, urls, platforms, direction "
                "FROM jobs WHERE user_flag = 'interested'"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            _send_json(
                self,
                {
                    "ok": True,
                    "matched": 0,
                    "skipped": 0,
                    "message": "没有标记为 🌟 的岗位，请先在岗位列表标记后再精排。",
                },
            )
            return

        if len(rows) > 30:
            _send_json(
                self,
                {
                    "ok": False,
                    "message": f"单次最多精排 30 个岗位，当前 {len(rows)} 个，请减少标记后再试",
                },
            )
            return

        # Rebuild lightweight job objects expected by match_jobs.
        # match_jobs reads: item.job (id/title/company/location/salary_min/
        # salary_max/description/urls), item.resume_file, item.direction.
        class _Job:
            pass

        class _Item:
            pass

        items = []
        for r in rows:
            d = dict(r)
            j = _Job()
            j.id = d["id"]
            j.title = d["title"] or ""
            j.company = d["company"] or ""
            j.location = d["location"] or ""
            j.salary_min = d["salary_min"]
            j.salary_max = d["salary_max"]
            j.description = d["description"] or ""
            j.urls = d["urls"] or "{}"
            j.platforms = d["platforms"] or ""
            j.direction = d["direction"] or ""
            it = _Item()
            it.job = j
            # match_jobs caches resumes by resume_file and loads via
            # load_resume(config, direction); pass empty string as the
            # cache key (all flagged jobs share the same default resume
            # unless direction changes the resume).
            it.resume_file = ""
            it.direction = d["direction"] or ""
            items.append(it)

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            # Temporarily disable min_score filtering so ALL LLM-scored jobs
            # land in the DB -- the frontend's score dropdown filters them.
            # Otherwise jobs scoring < 50 are dropped before saving and the
            # match tab appears empty even after a successful run.
            orig_min = config.matching.match_min_score
            config.matching.match_min_score = 0

            def _on_progress(done, total):
                _set_match_progress(
                    done=done, total=total, current="", status=f"已完成 {done}/{total}"
                )

            _set_match_progress(running=True, done=0, total=len(items), current="", status="")
            try:
                matched, skipped = loop.run_until_complete(
                    match_mod.match_jobs(items, config, provider, on_progress=_on_progress)
                )
            finally:
                config.matching.match_min_score = orig_min
        finally:
            loop.close()
        _set_match_progress(running=False, done=len(items), total=len(items), current="", status="")

        if matched:
            _save_match_to_db(matched)

        _send_json(
            self,
            {
                "ok": True,
                "flagged": len(items),
                "matched": len(matched),
                "skipped": skipped,
                "message": f"精排完成：{len(matched)} 个匹配（跳过 {skipped}）",
            },
        )

    def _api_jd_fetch(self):
        """POST /api/jd/fetch -- fetch full JD for user-flagged (🌟) jobs.

        Loads all jobs with user_flag='interested', calls each platform's
        fetch_full_jd method, and updates the description field in DB.
        """
        import asyncio

        from agent_core.config import load_config
        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.storage.db import get_db

        config = load_config()
        conn = get_db()

        try:
            rows = conn.execute(
                "SELECT id, title, company, location, salary_min, salary_max, "
                "description, urls, platforms, security_id, lid, direction "
                "FROM jobs WHERE user_flag = 'interested'"
            ).fetchall()
        except Exception:
            conn.close()
            _send_error(self, 500, "Failed to query jobs")
            return

        if len(rows) > 20:
            conn.close()
            _send_error(
                self, 400, f"单次最多抓取 20 个岗位的 JD，当前 {len(rows)} 个，请减少标记后再试"
            )
            return

        if not rows:
            conn.close()
            _send_json(self, {"ok": True, "fetched": 0, "failed": 0, "message": "没有标记的职位"})
            return

        from agent_core.platforms.base import Job

        fetched = 0
        failed = 0
        skipped = 0

        _set_jd_progress(running=True, done=0, total=len(rows), current="", status="")
        # Use one event loop for all enrichments (avoids per-job loop overhead
        # and event-loop conflicts with Playwright browser singletons).
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            for idx, row in enumerate(rows):
                try:
                    _set_jd_progress(
                        done=idx,
                        current=f"{row['company'] or ''} · {row['title'] or ''}",
                        status="正在抓取…",
                    )
                    # Parse platforms JSON array (stored as '["boss_zhipin"]', not CSV)
                    raw_platforms = row["platforms"] or "[]"
                    try:
                        platforms_list = json.loads(raw_platforms)
                    except Exception:
                        platforms_list = []
                    raw_urls = row["urls"] or "{}"
                    try:
                        urls_dict = json.loads(raw_urls)
                    except Exception:
                        urls_dict = {}

                    job = Job(
                        id=row["id"],
                        title=row["title"] or "",
                        company=row["company"] or "",
                        location=row["location"] or "",
                        salary_min=row["salary_min"],
                        salary_max=row["salary_max"],
                        description=row["description"] or "",
                        platforms=platforms_list,
                        urls=urls_dict,
                    )
                    job.security_id = row["security_id"] or ""
                    job.lid = row["lid"] or ""

                    # Skip if already has full JD
                    if len(job.description or "") > 200 and "JD:" in (job.description or ""):
                        skipped += 1
                        continue

                    desc_before = len(job.description or "")
                    enriched_job = loop.run_until_complete(enrich_job_jd(job, config))

                    if enriched_job.description and len(enriched_job.description) > desc_before:
                        conn.execute(
                            "UPDATE jobs SET description = ? WHERE id = ?",
                            (enriched_job.description, job.id),
                        )
                        fetched += 1
                    else:
                        skipped += 1

                except Exception as e:
                    logger.warning(f"JD fetch error for job {row['id']}: {e}")
                    failed += 1
        finally:
            loop.close()
            conn.commit()
            conn.close()
        _set_jd_progress(running=False, done=len(rows), total=len(rows), current="", status="")

        msg = f"JD抓取完成：成功 {fetched}"
        if skipped > 0:
            msg += f"，跳过 {skipped}"
        if failed > 0:
            msg += f"，失败 {failed}"
        _send_json(
            self,
            {
                "ok": True,
                "fetched": fetched,
                "skipped": skipped,
                "failed": failed,
                "message": msg,
            },
        )

    def _api_jd_view(self) -> None:
        """GET /api/jd/view -- return all user-flagged (🌟) jobs with their JD.

        Used by the 人工初筛 tab's "查看JD" button: shows the full JD of all
        wanted jobs in one modal, with anti-bot detection so the user can
        import real JD manually for jobs that hit a captcha/verification page.
        """
        from agent_core.storage.db import get_db

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, title, company, description FROM jobs " "WHERE user_flag = 'interested'"
            ).fetchall()
        except Exception:
            conn.close()
            _send_error(self, 500, "Failed to query jobs")
            return
        conn.close()
        jobs = []
        for r in rows:
            desc = r["description"] or ""
            # Strip "JD: " prefix if present
            if desc.startswith("JD: "):
                desc = desc[4:]
            jobs.append(
                {
                    "id": r["id"],
                    "title": r["title"] or "",
                    "company": r["company"] or "",
                    "jd": desc,
                }
            )
        _send_json(self, {"ok": True, "jobs": jobs})

    def _api_jd_manual(self) -> None:
        """POST /api/jd/manual -- manually import JD for a job.

        Body (JSON): {"job_id": "...", "jd": "full JD text"}
        Writes the JD into the job's description (prefixed with 'JD: '),
        overwriting any existing (e.g. anti-bot page) content.
        """

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 65536:
            _send_error(self, 400, "Invalid content length")
            return
        data = _read_json_body(self)
        if not data:
            _send_error(self, 400, "Invalid JSON")
            return
        job_id = str(data.get("job_id") or "").strip()
        jd = str(data.get("jd") or "").strip()
        if not job_id or not jd:
            _send_error(self, 400, "缺少 job_id 或 JD 内容")
            return

        from agent_core.storage.db import get_db

        conn = get_db()
        try:
            row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                conn.close()
                _send_error(self, 404, f"岗位不存在: {job_id}")
                return
            conn.execute("UPDATE jobs SET description = ? WHERE id = ?", (f"JD: {jd}", job_id))
            conn.commit()
        except Exception as e:
            conn.close()
            _send_error(self, 500, f"保存失败: {e}")
            return
        conn.close()
        _send_json(self, {"ok": True, "message": "JD 已导入"})

    def _api_match_feedback(self) -> None:
        """POST /api/match/feedback — record user calibration of a match score.

        Body (JSON): {"job_id": "...", "feedback_type": "too_high|too_low", "note": "..."}
        """

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 65536:
            _send_error(self, 400, "Invalid content length")
            return
        data = _read_json_body(self)
        if not data and length > 0:
            _send_error(self, 400, "Invalid JSON")
            return
        job_id = data.get("job_id", "")
        feedback_type = data.get("feedback_type", "")
        note = data.get("note", "")
        if feedback_type not in ("too_high", "too_low"):
            _send_error(self, 400, "feedback_type must be too_high or too_low")
            return
        if not job_id:
            _send_error(self, 400, "job_id is required")
            return

        now = datetime.now(UTC).isoformat()
        # Get direction from the job
        direction = ""
        try:
            conn2 = sqlite3.connect(self.db_path)
            row = conn2.execute("SELECT direction FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row:
                direction = row[0] or ""
            conn2.close()
        except Exception:
            pass

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO match_feedback (job_id, direction, feedback_type, note, created_at) VALUES (?,?,?,?,?)",
            (job_id, direction, feedback_type, note, now),
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM match_feedback").fetchone()[0]
        conn.close()
        _send_json(self, {"ok": True, "total_feedback": total})

    def _api_clear_match_feedback(self) -> None:
        """DELETE /api/match/feedback — clear all historical match calibration feedback."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("DELETE FROM match_feedback")
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            logger.info("Cleared %d match_feedback rows", deleted)
            _send_json(self, {"ok": True, "deleted": deleted})
        except Exception as e:
            logger.exception("Failed to clear match feedback")
            _send_error(self, 500, f"Clear failed: {e}")

    def _api_match(self, params):
        """GET /api/match -- return match results, paginated."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            page = _get_int_param(params, "page", 1)
            page_size = _get_int_param(params, "page_size", 30)
            min_score = _get_int_param(params, "min_score", 0)
            where = ""
            bind = []
            if min_score > 0:
                where = " WHERE m.match_score >= ?"
                bind.append(min_score)
            total = conn.execute("SELECT COUNT(*) FROM match_results m" + where, bind).fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
            offset = (page - 1) * page_size
            rows = conn.execute(
                """SELECT m.*, j.location, j.salary_min, j.salary_max,
                          j.urls
                   FROM match_results m
                   LEFT JOIN jobs j ON m.job_id = j.id"""
                + where
                + " ORDER BY m.match_score DESC LIMIT ? OFFSET ?",
                bind + [page_size, offset],
            ).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["missing_skills"] = json.loads(d.get("missing_skills", "[]"))
                except Exception:
                    d["missing_skills"] = []
                try:
                    d["strengths"] = json.loads(d.get("strengths", "[]"))
                except Exception:
                    d["strengths"] = []
                items.append(d)
            _send_json(
                self,
                {
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "pages": pages,
                },
            )
        finally:
            conn.close()

    # ----------------------------------------------------------- Flag ---
    def _api_flag_batch(self) -> None:
        """POST /api/flag/batch — batch flag multiple jobs in one transaction.

        Body (JSON): {"ids": ["id1","id2",...], "flag": "interested|rejected|clear"}
        """

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 1024 * 1024:
            _send_error(self, 400, "Invalid content length")
            return
        data = _read_json_body(self)
        if not data and length > 0:
            _send_error(self, 400, "Invalid JSON")
            return
        ids = data.get("ids", [])
        flag = data.get("flag", "")
        if flag not in ("interested", "rejected", "clear"):
            _send_error(self, 400, "flag must be interested, rejected, or clear")
            return
        if not ids or not isinstance(ids, list):
            _send_error(self, 400, "ids must be a non-empty array")
            return

        db_val = flag if flag != "clear" else ""
        placeholders = ",".join("?" for _ in ids)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            f"UPDATE jobs SET user_flag = ? WHERE id IN ({placeholders})",
            [db_val] + ids,
        )
        conn.commit()
        updated = conn.total_changes
        conn.close()
        _send_json(self, {"ok": True, "updated": updated})

    def _api_flag_job(self, path: str) -> None:
        """POST /api/flag/{job_id}?flag=interested|rejected|clear

        Manually mark a job as interested/rejected, or clear the flag.
        Only flagged jobs (user_flag='interested') are included in the next
        match stage.
        """

        parts = path.split("/")
        if len(parts) < 4:
            _send_error(self, 400, "Missing job_id in path")
            return
        job_id = parts[3]
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        flag = params.get("flag", [""])[0]

        valid_flags = {"interested", "rejected", "clear"}
        if flag not in valid_flags:
            _send_error(self, 400, "flag must be one of: interested, rejected, clear")
            return

        db_val = flag if flag != "clear" else ""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("UPDATE jobs SET user_flag = ? WHERE id = ?", (db_val, job_id))
            conn.commit()
            conn.close()
            _send_json(self, {"ok": True, "job_id": job_id, "flag": db_val})
        except Exception as e:
            _send_error(self, 500, f"Flag failed: {e}")

    def _api_files(self):
        """GET /api/files -- list generated files from output/ directory."""
        files = _scan_output_dir()
        _send_json(self, {"items": files, "total": len(files)})

    def _api_offer_upload(self):
        """POST /api/offer/upload -- save an uploaded offer .txt to offers/."""
        import os
        import re

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 5 * 1024 * 1024:
            _send_error(self, 400, "Invalid content length (1B-5MB allowed)")
            return
        data = _read_json_body(self)
        if not data and length > 0:
            _send_error(self, 400, "Invalid JSON body")
            return
        name = (data.get("name") or "").strip()
        content = data.get("content") or ""
        if not name:
            _send_error(self, 400, "Missing 'name'")
            return
        if not content.strip():
            _send_error(self, 400, "Missing 'content'")
            return
        safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" .")
        if not safe:
            safe = "offer.txt"
        if not safe.lower().endswith(".txt"):
            safe = safe + ".txt"
        offers_dir = self._offers_dir()
        os.makedirs(offers_dir, exist_ok=True)
        full = os.path.join(offers_dir, safe)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Saved offer file %s (%d bytes)", full, len(content))
        _send_json(self, {"ok": True, "name": safe, "size": len(content)})

    def _api_offer_list(self):
        """GET /api/offer/list -- list offer .txt files in offers/ with eval status."""
        from pathlib import Path

        from agent_core.storage.db import get_db

        offers_dir = self._offers_dir()
        p = Path(offers_dir)
        files = []
        if p.is_dir():
            files = [
                f
                for f in sorted(p.iterdir(), reverse=True)
                if f.is_file() and f.suffix.lower() == ".txt"
            ]
        evals = {}
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT offer_file_name, company, result, updated_at FROM offer_evaluations"
            ).fetchall()
            for r in rows:
                evals[r["offer_file_name"]] = r
        finally:
            conn.close()
        items = []
        for i, f in enumerate(files, 1):
            name = f.name
            stat = f.stat()
            ev = evals.get(name)
            overall = None
            if ev and ev["result"]:
                try:
                    overall = json.loads(ev["result"]).get("overall_score")
                except Exception:
                    overall = None
            items.append(
                {
                    "no": i,
                    "name": name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "evaluated": ev is not None,
                    "company": (ev["company"] if ev else ""),
                    "overall_score": overall,
                    "updated_at": (ev["updated_at"] if ev else ""),
                }
            )
        _send_json(self, {"items": items, "total": len(items)})

    def _api_offer_compare(self):
        """POST /api/offer/compare -- LLM re-compares offers (independent of evaluation)."""
        import asyncio
        import os
        import re

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.offer_eval import compare
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        names = body.get("file_names") or []
        if len(names) < 2:
            _send_error(self, 400, "至少需要 2 个 Offer 进行对比")
            return
        conn = get_db()
        try:
            rows = []
            unevaluated = []
            for n in names:
                r = conn.execute(
                    "SELECT offer_file_name, company, title, parsed_fields, result FROM offer_evaluations WHERE offer_file_name=?",
                    (n,),
                ).fetchone()
                if r:
                    rows.append(r)
                else:
                    unevaluated.append(n)
        finally:
            conn.close()
        offers_dir = self._offers_dir()
        offers = []
        for r in rows:
            raw_text = ""
            full = os.path.join(offers_dir, r["offer_file_name"])
            if not os.path.realpath(full).startswith(os.path.realpath(offers_dir) + os.sep):
                _send_error(self, 400, "invalid file path")
                return
            try:
                with open(full, encoding="utf-8") as fh:
                    raw_text = fh.read()
            except Exception:
                pass
            offers.append(
                {
                    "file_name": r["offer_file_name"],
                    "company": r["company"] or "",
                    "title": r["title"] or "",
                    "parsed": json.loads(r["parsed_fields"] or "{}"),
                    "result": json.loads(r["result"] or "{}"),
                    "raw_text": raw_text,
                }
            )
        for n in unevaluated:
            raw_text = ""
            full = os.path.join(offers_dir, n)
            if not os.path.realpath(full).startswith(os.path.realpath(offers_dir) + os.sep):
                _send_error(self, 400, "invalid file path")
                return
            try:
                with open(full, encoding="utf-8") as fh:
                    raw_text = fh.read()
            except Exception:
                _send_error(self, 404, f"Offer 文件不存在：{n}")
                return

            def _field(label, text=raw_text):
                m = re.search(rf"{re.escape(label)}[:：]\s*([^\n\r]*)", text)
                return m.group(1).strip() if m else ""

            parsed = {
                "company": _field("公司名") or _field("公司"),
                "title": _field("职位名") or _field("职位"),
                "location": _field("工作地点"),
                "monthly_base": _field("月薪base") or _field("月薪"),
                "pay_months": _field("发放月数"),
                "annual_total": _field("年总包") or _field("年薪"),
            }
            offers.append(
                {
                    "file_name": n,
                    "company": parsed.get("company", ""),
                    "title": parsed.get("title", ""),
                    "parsed": parsed,
                    "result": {},
                    "raw_text": raw_text,
                }
            )
        config = load_config()
        provider = create_provider(config, thinking_effort="max")
        try:
            analysis = asyncio.run(compare(config, provider, offers))
        except Exception as e:
            _send_error(self, 500, f"LLM 对比失败：{e}")
            return
        best = max(offers, key=lambda o: o["result"].get("overall_score") or 0) if offers else None
        _send_json(self, {"ok": True, "offers": offers, "best": best, "analysis": analysis})

    def _api_offer_template(self) -> None:
        """GET /api/offer/template -- download the 17-field offer import template (.txt)."""
        data = OFFER_TEMPLATE_TXT.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="offer_template.txt"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api_offer_preview(self, params) -> None:
        """GET /api/offer/preview?file_name=... -- return cached eval, or parse file text if not yet evaluated."""
        import os
        import re

        from agent_core.storage.db import get_db

        file_name = (
            params.get("file_name", [""])[0]
            if isinstance(params.get("file_name", [""]), list)
            else params.get("file_name", "")
        ).strip()
        if not file_name:
            _send_error(self, 400, "missing file_name")
            return
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT parsed_fields, eval_input, result, updated_at FROM offer_evaluations WHERE offer_file_name=?",
                (file_name,),
            ).fetchone()
        finally:
            conn.close()
        offers_dir = self._offers_dir()
        full = os.path.join(offers_dir, file_name)
        if not os.path.realpath(full).startswith(os.path.realpath(offers_dir) + os.sep):
            _send_error(self, 400, "invalid file path")
            return
        if row:
            # 缓存分支也读磁盘原始文本，供前端预览渲染（否则预览窗口无内容）
            _raw_txt = ""
            if os.path.isfile(full):
                try:
                    with open(full, encoding="utf-8") as _fh:
                        _raw_txt = _fh.read()
                except Exception:
                    _raw_txt = ""
            _send_json(
                self,
                {
                    "ok": True,
                    "parsed": json.loads(row["parsed_fields"] or "{}"),
                    "eval_input": json.loads(row["eval_input"] or "{}"),
                    "result": json.loads(row["result"] or "{}"),
                    "updated_at": row["updated_at"],
                    "raw_text": _raw_txt,
                },
            )
            return
        text = ""
        if os.path.isfile(full):
            try:
                with open(full, encoding="utf-8") as fh:
                    text = fh.read()
            except Exception:
                text = ""

            def _field(label):
                m = re.search(rf"{re.escape(label)}[:\uff1a]\s*([^\n\r]*)", text)
                return m.group(1).strip() if m else ""

            parsed = {
                "company": _field("\u516c\u53f8\u540d") or _field("\u516c\u53f8"),
                "title": _field("\u804c\u4f4d\u540d") or _field("\u804c\u4f4d"),
                "location": _field("\u5de5\u4f5c\u5730\u70b9"),
                "monthly_base": _field("\u6708\u85aabas") or _field("\u6708\u85aa"),
                "pay_months": _field("\u53d1\u653e\u6708\u6570"),
                "annual_total": _field("\u5e74\u603b\u5305") or _field("\u5e74\u85aa"),
            }
        else:
            parsed = {}
        _send_json(self, {"ok": True, "parsed": parsed, "raw_text": text})

    def _api_offer_delete(self, params: dict[str, list[str]]) -> None:
        """DELETE /api/offer?file_name=... -- delete offer file + cached eval."""
        import os

        from agent_core.storage.db import get_db

        raw_file_name = params.get("file_name", [""])
        file_name = (raw_file_name[0] if raw_file_name else "").strip()
        if not file_name:
            _send_error(self, 400, "missing file_name")
            return
        offers_dir = self._offers_dir()
        full = os.path.join(offers_dir, file_name)
        if not os.path.realpath(full).startswith(os.path.realpath(offers_dir) + os.sep):
            _send_error(self, 400, "invalid file path")
            return
        if os.path.isfile(full):
            os.remove(full)
        conn = get_db()
        try:
            conn.execute("DELETE FROM offer_evaluations WHERE offer_file_name=?", (file_name,))
            conn.commit()
        finally:
            conn.close()
        _send_json(self, {"ok": True})

    def _api_files_zip(self):
        """POST /api/files/zip {names:[...]} -- zip selected files and return as download."""
        import io
        import os
        import zipfile

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        names = body.get("names") or []
        if not names:
            _send_error(self, 400, "缺少 names")
            return
        output_root = os.path.realpath("output")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                fp = os.path.realpath(os.path.join("output", name))
                if not fp.startswith(output_root + os.sep):
                    continue
                if os.path.isfile(fp):
                    zf.write(fp, os.path.basename(fp))
        buf.seek(0)
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="jobagent_files.zip"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api_materials_drafts(self):
        """GET /api/materials/drafts?status=draft|confirmed|all -- list material drafts.

        Default 'draft' (pending review). 'confirmed' shows archived drafts,
        'all' shows both. Used by the 材料审核台 status filter.
        """
        from urllib.parse import parse_qs, urlparse

        from agent_core.storage.db import get_db

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        status = params.get("status", ["draft"])[0]
        if status not in ("draft", "confirmed", "all"):
            status = "draft"

        conn = get_db()
        try:
            if status == "all":
                rows = conn.execute(
                    "SELECT d.job_id, d.resume_md, d.hr_message, d.status, d.feedback, "
                    "d.version, d.updated_at, d.interview_prep_md, d.interview_confirmed, "
                    "j.title AS job_title, j.company, j.direction "
                    "FROM material_drafts d LEFT JOIN jobs j ON j.id=d.job_id "
                    "ORDER BY d.updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT d.job_id, d.resume_md, d.hr_message, d.status, d.feedback, "
                    "d.version, d.updated_at, d.interview_prep_md, d.interview_confirmed, "
                    "j.title AS job_title, j.company, j.direction "
                    "FROM material_drafts d LEFT JOIN jobs j ON j.id=d.job_id "
                    "WHERE d.status=? ORDER BY d.updated_at DESC",
                    (status,),
                ).fetchall()
        finally:
            conn.close()
        # Attach the interview-prep markdown (含自我介绍) so the 材料审核台 card
        # can show the whole prep doc next to resume + HR message. v12: read
        # directly from material_drafts.interview_prep_md (the generated draft
        # column) — the catalog only gets the file after confirmation, so it
        # can no longer be the preview source. Also expose interview_confirmed
        # so the card can show a draft/confirmed badge.
        items = [dict(r) for r in rows]
        for item in items:
            item["interview_prep_md"] = item.get("interview_prep_md") or ""
            item["interview_confirmed"] = 1 if item.get("interview_confirmed") else 0
        _send_json(self, {"ok": True, "items": items})

    def _api_materials_jobs(self):
        """GET /api/materials/jobs -- list jobs that have material_drafts records."""
        from agent_core.storage.db import get_db

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT DISTINCT j.id, j.title, j.company "
                "FROM jobs j INNER JOIN material_drafts d ON d.job_id = j.id "
                "ORDER BY j.last_seen DESC"
            ).fetchall()
        finally:
            conn.close()
        _send_json(
            self,
            [{"id": r["id"], "title": r["title"], "company": r["company"]} for r in rows],
        )

    def _api_materials_generate(self):
        """POST /api/materials/generate {job_ids:[...]} -- generate resume+HR msg+interview prep."""
        import asyncio

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.cover_letter import generate_cover_letter
        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.pipeline.tailor import tailor_resume
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        job_ids = body.get("job_ids") or []
        if not job_ids:
            _send_json(self, {"ok": False, "message": "未选择职位"})
            return
        if len(job_ids) > 10:
            _send_json(self, {"ok": False, "message": "单次最多生成 10 个职位的材料，请减少选择"})
            return
        config = load_config()
        provider = create_provider(config)
        conn = get_db()
        try:
            q = ",".join("?" * len(job_ids))
            rows = conn.execute(
                "SELECT id, title, company, location, description, urls, platforms, "
                "direction, security_id, lid "
                f"FROM jobs WHERE id IN ({q})",
                job_ids,
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            _send_json(self, {"ok": False, "message": "职位未找到"})
            return

        found_ids = {r["id"] for r in rows}
        missing_ids = [jid for jid in job_ids if jid not in found_ids]
        failed = [{"job_id": jid, "error": "职位不存在或已被清理"} for jid in missing_ids]

        _set_materials_progress(
            running=True,
            done=0,
            total=len(job_ids),
            current="",
            status="开始生成求职材料",
        )

        class _Job:
            pass

        async def _gen(job, llm_provider):
            enriched = await enrich_job_jd(job, config)
            resume_md = await tailor_resume(enriched, config, llm_provider)
            hr_msg = await generate_cover_letter(enriched, config, llm_provider)
            return resume_md, hr_msg, enriched

        loop = asyncio.new_event_loop()
        succeeded = 0
        interview_prep_failed = []
        try:
            asyncio.set_event_loop(loop)
            for idx, r in enumerate(rows):
                d = dict(r)
                job = _Job()
                job.id = d["id"]
                job.title = d["title"] or ""
                job.company = d["company"] or ""
                job.location = d["location"] or ""
                job.description = d["description"] or ""
                # DB stores urls/platforms as JSON strings; parse to real
                # dict/list — enrich/tailor call .keys()/.items() on them.
                try:
                    job.urls = json.loads(d["urls"] or "{}")
                except Exception:
                    job.urls = {}
                try:
                    job.platforms = json.loads(d["platforms"] or "[]")
                except Exception:
                    job.platforms = []
                job.direction = d["direction"] or ""
                # enrich_job_jd reads security_id/lid when the description lacks
                # JD keywords — without these attrs it AttributeErrors (bug:
                # jobs with no cached JD failed to generate materials).
                job.security_id = d.get("security_id") or ""
                job.lid = d.get("lid") or ""
                _set_materials_progress(
                    done=idx,
                    total=len(job_ids),
                    current=f"{job.title} @ {job.company}",
                    status="正在生成简历/HR消息...",
                )
                try:
                    resume_md, hr_msg, enriched = loop.run_until_complete(_gen(job, provider))
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "materials generate failed for %s (%s); retrying once",
                        d.get("id"),
                        e,
                    )
                    try:
                        resume_md, hr_msg, enriched = loop.run_until_complete(_gen(job, provider))
                    except Exception as e2:  # noqa: BLE001
                        logger.warning(
                            "materials generate retry failed for %s: %s", d.get("id"), e2
                        )
                        failed.append({"job_id": d.get("id"), "error": str(e2)})
                        continue
                now = datetime.now(UTC).isoformat()
                c = get_db()
                try:
                    c.execute(
                        "INSERT OR REPLACE INTO material_drafts "
                        "(job_id, resume_md, hr_message, status, feedback, version, "
                        "created_at, updated_at) VALUES (?, ?, ?, 'draft', '', "
                        "COALESCE((SELECT version FROM material_drafts WHERE job_id=?), 0) + 1, ?, ?)",
                        (d["id"], resume_md, hr_msg, d["id"], now, now),
                    )
                    c.commit()
                finally:
                    c.close()
                succeeded += 1
                _set_materials_progress(
                    done=idx,
                    total=len(job_ids),
                    current=f"{job.title} @ {job.company}",
                    status="正在生成面试准备...",
                )
                # interview prep (cache-aware, failure isolated from resume/hr)
                # v12: 生成后不再立即 catalog 到 generated_files —— 面试准备与
                # 简历/HR 消息一样，先进材料审核台草稿（interview_prep_md），
                # 用户确认后才归档到「已生成文件」TAB。缓存判断改为查
                # material_drafts.interview_prep_md（generated_files 只在
                # 确认后才有记录，未确认时查不到会重复生成）。
                try:
                    from pathlib import Path

                    from agent_core.pipeline.interview_prep import (
                        predict_questions,
                        save_interview_prep,
                    )

                    db = get_db()
                    try:
                        existing = db.execute(
                            "SELECT interview_prep_md FROM material_drafts WHERE job_id=?",
                            (job.id,),
                        ).fetchone()
                        if not existing or not existing[0]:
                            try:
                                qs = loop.run_until_complete(
                                    predict_questions(
                                        enriched,
                                        config,
                                        provider,
                                        direction=job.direction,
                                    )
                                )
                            except Exception as e:  # noqa: BLE001
                                logger.warning(
                                    "interview prep failed for %s (%s); retrying once",
                                    job.id,
                                    e,
                                )
                                qs = loop.run_until_complete(
                                    predict_questions(
                                        enriched,
                                        config,
                                        provider,
                                        direction=job.direction,
                                    )
                                )
                            md_path = save_interview_prep(qs, enriched)
                            md_text = Path(md_path).read_text(encoding="utf-8")
                            db.execute(
                                "UPDATE material_drafts SET interview_prep_md=?, "
                                "interview_confirmed=0, updated_at=? WHERE job_id=?",
                                (md_text, datetime.now(UTC).isoformat(), job.id),
                            )
                            db.commit()
                    finally:
                        db.close()
                except Exception as e:  # noqa: BLE001
                    logger.warning("interview prep failed for %s: %s", job.id, e)
                    interview_prep_failed.append({"job_id": job.id, "error": str(e)})
                _set_materials_progress(
                    done=idx + 1,
                    total=len(job_ids),
                    current="",
                    status=f"已完成 {idx + 1}/{len(job_ids)}",
                )
        finally:
            loop.close()
        _set_materials_progress(
            running=False,
            done=len(job_ids),
            total=len(job_ids),
            current="",
            status="",
        )
        response = {
            "ok": True,
            "succeeded": succeeded,
            "failed": failed,
            "total": len(job_ids),
        }
        if interview_prep_failed:
            response["interview_prep_failed"] = interview_prep_failed
        _send_json(self, response)

    def _api_mock_interview_start(self):
        """POST /api/mock-interview/start {job_id, direction?, from_prep?, focus?, difficulty?}.

        Creates a server-side mock interview session and returns its id. The
        caller then opens the conversation via /api/mock-interview/reply with
        an empty text to get the interviewer's opening line.
        """
        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.interview_prep import start_mock_session
        from agent_core.storage.db import get_db

        body = _read_json_body(self)
        job_id = body.get("job_id")
        if not job_id:
            _send_json(self, {"ok": False, "message": "缺少 job_id"})
            return
        config = load_config()
        provider = create_provider(config)
        db_path = Handler.db_path or "data/agent.db"
        conn = get_db(db_path)
        try:
            r = conn.execute(
                "SELECT id, title, company, location, description, urls, platforms, direction "
                "FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
        if not r:
            _send_json(self, {"ok": False, "message": "职位未找到"})
            return
        d = dict(r)

        class _Job:
            pass

        job = _Job()
        job.id = d["id"]
        job.title = d["title"] or ""
        job.company = d["company"] or ""
        job.location = d["location"] or ""
        job.description = d["description"] or ""
        job.urls = d["urls"] or "{}"
        job.platforms = d["platforms"] or ""
        job.direction = d["direction"] or ""
        info = start_mock_session(
            job,
            config,
            provider,
            direction=body.get("direction") or None,
            from_prep=bool(body.get("from_prep")),
            focus=body.get("focus") or None,
            difficulty=body.get("difficulty") or None,
            db_path=db_path,
        )
        _send_json(self, info)

    def _api_mock_interview_reply(self):
        """POST /api/mock-interview/reply {session_id, text?} -> SSE stream.

        Streams one interview turn as `data: {json}\\n\\n` events:
          {"type":"delta","text":...}   incremental reply chunk
          {"type":"turn_end"}           reply done, interview continues
          {"type":"end","assessment":...} interview concluded, transcript saved
          {"type":"error","text":...}   session missing or LLM failure
        """
        import asyncio

        from agent_core.pipeline.interview_prep import stream_mock_turn

        body = _read_json_body(self)
        session_id = body.get("session_id")
        text = (body.get("text") or "").strip() or None
        if not session_id:
            _send_error(self, 400, "缺少 session_id")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        async def _pump():
            try:
                async for evt in stream_mock_turn(session_id, text):
                    line = f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
            except Exception as e:  # noqa: BLE001
                logger.exception("mock-interview reply stream failed")
                err = {"type": "error", "text": f"流式中断: {e}"}
                try:
                    self.wfile.write(f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                except Exception:
                    pass

        try:
            asyncio.run(_pump())
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected mid-stream

    def _api_mock_interview_end(self):
        """POST /api/mock-interview/end {session_id} -> {ok}.

        2026-08-12: manual end now persists the transcript AND generates an
        assessment (marked 中途结束 since the question bank may be incomplete).
        """
        import asyncio

        from agent_core.pipeline.interview_prep import end_mock_session

        body = _read_json_body(self)
        session_id = body.get("session_id")
        if not session_id:
            _send_json(self, {"ok": False, "message": "缺少 session_id"})
            return
        result = asyncio.run(end_mock_session(session_id))
        # 2026-08-12: end_mock_session 返回 {ok, md, assessment}（文件名供进度弹窗查看按钮）
        if isinstance(result, dict):
            _send_json(self, result)
        else:
            _send_json(self, {"ok": bool(result)})

    def _api_mock_interview_abandon(self):
        """POST /api/mock-interview/abandon {session_id} -> {ok}.

        清空面板时丢弃文字面试服务端会话，不生成任何文件。
        """
        from agent_core.pipeline.interview_prep import abandon_mock_session

        body = _read_json_body(self)
        session_id = body.get("session_id")
        if not session_id:
            _send_json(self, {"ok": False, "message": "缺少 session_id"})
            return
        _send_json(self, {"ok": abandon_mock_session(session_id)})

    def _api_mock_latest_transcript(self, params):
        """GET /api/mock-interview/latest-transcript?job_id=X&mode=realtime|text.

        Returns the most recent mock interview transcript .md as a .txt download
        (Windows CRLF line breaks). 404 if no transcript found for the job.
        """
        import glob
        from urllib.parse import quote

        from agent_core.pipeline.interview_prep import _fs
        from agent_core.storage.db import get_db

        job_id = params.get("job_id", [""])[0]
        mode = params.get("mode", ["realtime"])[0]
        if not job_id:
            _send_error(self, 400, "缺少 job_id")
            return
        db_path = Handler.db_path or "data/agent.db"
        conn = get_db(db_path)
        try:
            r = conn.execute("SELECT title, company FROM jobs WHERE id=?", (job_id,)).fetchone()
        finally:
            conn.close()
        if not r:
            _send_error(self, 404, "职位未找到")
            return
        suffix = "_realtime_mock" if mode == "realtime" else "_mock_interview"
        pattern = os.path.join(
            "output", f"{_fs(r['company'] or '')}_{_fs(r['title'] or '')}{suffix}.md"
        )
        matches = glob.glob(pattern)
        if not matches:
            _send_error(self, 404, "暂无对话记录")
            return
        matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        safe_path = os.path.realpath(matches[0])
        output_root = os.path.realpath("output")
        if not safe_path.startswith(output_root + os.sep):
            _send_error(self, 403, "Access denied")
            return
        try:
            with open(safe_path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            _send_error(self, 404, "读取失败")
            return
        content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        body = content.encode("utf-8")
        download_name = os.path.splitext(os.path.basename(safe_path))[0] + ".txt"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header(
            "Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api_mock_assessment_preview(self, params):
        """GET /api/mock-assessment/preview?name=<file> -- read a mock interview
        assessment .txt (or .json) and return its structured fields so the
        frontend can render the radar-chart report (like offer eval).

        Parses the plain-text assessment produced by format_assessment_txt()
        (lines: 总分 / 维度评分 / 优势 / 改进点). Returns assessment JSON.
        """
        import re

        name = params.get("name", [""])[0]
        if not name:
            _send_error(self, 400, "缺少 name")
            return
        safe_name = os.path.basename(name)  # strip any dir traversal
        safe_path = os.path.realpath(os.path.join("output", safe_name))
        output_root = os.path.realpath("output")
        if not safe_path.startswith(output_root + os.sep):
            _send_error(self, 403, "Access denied")
            return
        if not os.path.isfile(safe_path):
            _send_error(self, 404, "评估文件未找到")
            return
        try:
            content = open(safe_path, encoding="utf-8").read()
        except OSError:
            _send_error(self, 404, "读取失败")
            return
        if safe_path.endswith(".json"):
            try:
                import json as _json

                assessment = _json.loads(content)
                _send_json(self, {"ok": True, "name": safe_name, "assessment": assessment})
                return
            except Exception:  # noqa: BLE001
                pass  # fall through to text parse
        # Parse plain-text: 🎯 总分: N/10 | 【维度评分】label(key): N/10 | 【优势】 | 【改进点】
        assessment = {"dimensions": {}, "strengths": [], "improvements": []}
        overall_m = re.search(r"总分[:\s]*([\d.]+)\s*/10", content)
        if overall_m:
            assessment["overall"] = float(overall_m.group(1))
        dim_m = re.search(r"【维度评分】(.*?)(?:【优势】|$)", content, re.S)
        if dim_m:
            for line in dim_m.group(1).splitlines():
                m = re.search(r"([^:：]+)\((\w+)\)[:\s]*([\d.]+)\s*/10", line)
                if m:
                    key = m.group(2)
                    val = float(m.group(3))
                    if isinstance(assessment["dimensions"].get(key), dict):
                        assessment["dimensions"][key]["score"] = val
                    else:
                        assessment["dimensions"][key] = val
        seg = re.search(r"【优势】(.*?)(?:【改进点】|$)", content, re.S)
        if seg:
            assessment["strengths"] = [
                ln.strip().lstrip("- ").strip()
                for ln in seg.group(1).splitlines()
                if ln.strip() and not ln.strip().startswith("【")
            ]
        seg2 = re.search(r"【改进点】(.*)$", content, re.S)
        if seg2:
            assessment["improvements"] = [
                ln.strip().lstrip("- ").strip()
                for ln in seg2.group(1).splitlines()
                if ln.strip() and not ln.strip().startswith("【")
            ]
        _send_json(self, {"ok": True, "name": safe_name, "assessment": assessment})

    def _api_offer_evaluate(self):
        """POST /api/offer/evaluate -- evaluate a job offer.

        Two input modes (frontend sends file_name; CLI-style sends raw fields):
          1. {"file_name": "<offer>.txt"} -> read offers/<file>, LLM-parse 17
             fields, pack into evaluate() params, cache to offer_evaluations.
          2. {"company": "...", "title": "...", ...} -> evaluate() directly
             (no file, no cache). company is required in this mode.

        Returns the evaluate() JSON plus the parsed 17-field dict (mode 1) so
        the frontend can render company/title alongside the radar chart.
        """
        import asyncio
        import os

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.offer_eval import evaluate
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)

        file_name = (body.get("file_name") or "").strip()
        company = (body.get("company") or "").strip()

        config = load_config()
        provider = create_provider(config)

        # Path traversal guard for file_name mode
        if file_name:
            offers_dir = self._offers_dir()
            full = os.path.join(offers_dir, file_name)
            if not os.path.realpath(full).startswith(os.path.realpath(offers_dir) + os.sep):
                _send_error(self, 400, "invalid file path")
                return
            if not os.path.isfile(full):
                _send_error(self, 404, f"Offer 文件不存在：{file_name}")
                return
            try:
                with open(full, encoding="utf-8") as fh:
                    raw_text = fh.read()
            except Exception as e:
                _send_error(self, 500, f"读取失败: {e}")
                return

            async def _run():
                parsed = await _parse_offer_fields(provider, config, raw_text)
                eval_input = _pack_offer_eval_input(parsed)
                result = await evaluate(
                    config,
                    provider,
                    company=eval_input["company"],
                    title=eval_input["title"],
                    location=eval_input["location"],
                    salary=eval_input["salary"],
                    bonus=eval_input["bonus"],
                    benefits=eval_input["benefits"],
                    level=eval_input["level"],
                    notes=eval_input["notes"],
                    raw_text=raw_text,
                )
                return parsed, eval_input, result

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                parsed, eval_input, result = loop.run_until_complete(_run())
            except Exception as e:  # noqa: BLE001
                logger.warning("offer_eval failed: %s", e)
                _send_error(self, 500, f"评估失败: {e}")
                return
            finally:
                loop.close()

            # Cache to offer_evaluations (keyed by offer_file_name UNIQUE)
            now_iso = datetime.now(UTC).isoformat()
            conn = get_db()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO offer_evaluations "
                    "(offer_file_name, offer_file_path, company, title, "
                    " parsed_fields, eval_input, result, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE("
                    "  (SELECT created_at FROM offer_evaluations WHERE offer_file_name=?), ?), ?)",
                    (
                        file_name,
                        full,
                        parsed.get("company", ""),
                        parsed.get("title", ""),
                        json.dumps(parsed, ensure_ascii=False),
                        json.dumps(eval_input, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False),
                        file_name,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
            except Exception as e:  # noqa: BLE001
                logger.warning("offer_eval cache write failed: %s", e)
            finally:
                conn.close()

            _send_json(
                self, {"ok": True, "parsed": parsed, "eval_input": eval_input, "result": result}
            )
            return

        # Fallback: raw-field mode (CLI / chat tool contract)
        if not company:
            _send_error(self, 400, "缺少 company 或 file_name")
            return

        async def _run_raw():
            return await evaluate(
                config,
                provider,
                company=company,
                title=body.get("title", ""),
                location=body.get("location", ""),
                salary=body.get("salary", ""),
                bonus=body.get("bonus", ""),
                benefits=body.get("benefits", ""),
                level=body.get("level", ""),
                notes=body.get("notes", ""),
            )

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run_raw())
        except Exception as e:  # noqa: BLE001
            logger.warning("offer_eval failed: %s", e)
            _send_error(self, 500, f"评估失败: {e}")
            return
        finally:
            loop.close()
        _send_json(self, result)

    def _api_offer_save(self):
        """POST /api/offer/save -- save an evaluated offer as markdown + catalog."""
        import os
        import re

        from agent_core.pipeline.file_catalog import TYPE_OFFER_EVAL, catalog_file
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        company = (body.get("company") or "").strip()
        title = (body.get("title") or "").strip()
        if not company:
            _send_error(self, 400, "缺少 company")
            return

        def _safe_filename(text):
            s = re.sub(r'[\\/:*?"<>|]+', "_", text)
            s = re.sub(r"\s+", "_", s).strip("_")
            return s or "unknown"

        base_name = f"{_safe_filename(company)}_{_safe_filename(title)}_offer_eval"
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        file_name = f"{base_name}.md"
        file_path = os.path.join(output_dir, file_name)
        counter = 1
        stem = base_name
        while os.path.exists(file_path):
            file_name = f"{stem}_{counter}.md"
            file_path = os.path.join(output_dir, file_name)
            counter += 1

        overall = body.get("overall_score", 0)
        competitive = body.get("competitive_score", 0)
        growth = body.get("growth_score", 0)
        risk = body.get("risk_score", 0)
        salary = body.get("salary_score", 0)
        commute = body.get("commute_score", 0)
        wlb = body.get("wlb_score", 0)
        culture = body.get("culture_score", 0)
        stability = body.get("stability_score", 0)
        summary = body.get("summary") or ""
        pros = body.get("pros") or []
        cons = body.get("cons") or []
        levers = body.get("negotiation_levers") or []

        lines = [
            f"# {company} · {title or 'Offer'} 评估报告",
            "",
            "## 基本信息",
            "",
            f"- 公司：{company}",
            f"- 职位：{title or '-'}",
            f"- 地点：{body.get('location') or '-'}",
            f"- 月薪/总包：{body.get('salary') or '-'}",
            f"- 奖金/股票：{body.get('bonus') or '-'}",
            f"- 福利：{body.get('benefits') or '-'}",
            f"- 级别：{body.get('level') or '-'}",
            f"- 备注：{body.get('notes') or '-'}",
            "",
            "## 评分表",
            "",
            "| 维度 | 分数 |",
            "| --- | --- |",
            f"| 综合 | {overall} / 10 |",
            f"| 竞争力 | {competitive} / 10 |",
            f"| 成长性 | {growth} / 10 |",
            f"| 风险 | {risk} / 10 |",
            f"| 薪资满意度 | {salary} / 10 |",
            f"| 通勤便利 | {commute} / 10 |",
            f"| 工作生活平衡 | {wlb} / 10 |",
            f"| 文化匹配 | {culture} / 10 |",
            f"| 稳定性 | {stability} / 10 |",
            "",
            "## 评估总结",
            "",
            summary or "暂无",
            "",
            "## 优势",
            "",
        ]
        if pros:
            lines.extend([f"- {p}" for p in pros])
        else:
            lines.append("暂无")
        lines.extend(["", "## 风险 / 劣势", ""])
        if cons:
            lines.extend([f"- {c}" for c in cons])
        else:
            lines.append("暂无")
        if levers:
            lines.extend(["", "## 谈判杠杆", ""])
            lines.extend([f"- {item}" for item in levers])

        # Include the original offer text (offers/<file_name>.txt) so the saved
        # report carries the full raw input, not just the LLM-parsed fields.
        # Falls back to the body's salary/bonus/benefits when the file is gone.
        try:
            offers_dir = self._offers_dir()
            raw_name = (body.get("file_name") or "").strip()
            raw_path = os.path.join(offers_dir, raw_name)
            # Path traversal guard (mirrors _api_offer_delete): only read
            # files inside offers/.
            if (
                raw_name
                and os.path.realpath(raw_path).startswith(os.path.realpath(offers_dir) + os.sep)
                and os.path.isfile(raw_path)
            ):
                with open(raw_path, encoding="utf-8") as _fh:
                    raw_txt = _fh.read()
                lines.extend(["", "## 原始 Offer 信息", "", "```", raw_txt, "```"])
            else:
                lines.extend(["", "## 原始 Offer 信息", "", "（未找到原始 Offer 文件）"])
        except Exception as e:  # noqa: BLE001
            logger.warning("offer eval save: raw text append failed: %s", e)

        md = "\n".join(lines)
        # 原封不动：前端传了 html_content（评估预览完整 HTML，含雷达图 SVG）则保存 .html
        html_content = body.get("html_content") or ""
        try:
            if html_content:
                # 只保存完整 HTML（含雷达图 + 布局），已生成文件 tab 预览即见完整评估
                file_path = file_path[:-3] + ".html"
                file_name = file_name[:-3] + ".html"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md)
        except Exception as e:  # noqa: BLE001
            logger.warning("offer eval save failed writing %s: %s", file_path, e)
            _send_error(self, 500, f"保存失败: {e}")
            return

        db = get_db()
        try:
            catalog_file(
                db,
                None,
                TYPE_OFFER_EVAL,
                file_path,
                company=company,
                job_title=title,
            )
        finally:
            db.close()
        _send_json(
            self,
            {"ok": True, "file_path": file_path.replace("\\", "/"), "file_name": file_name},
        )

    def _api_offer_compare_save(self):
        """POST /api/offer/compare/save -- save multi-offer comparison as markdown + catalog."""
        import os

        from agent_core.pipeline.file_catalog import (
            TYPE_OFFER_COMPARE,
            catalog_file,
        )
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        offers = body.get("offers") or []
        if len(offers) < 2:
            _send_error(self, 400, "至少需要 2 个 Offer 进行对比")
            return

        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        html_content = body.get("html_content") or ""
        ext = ".html" if html_content else ".md"
        counter = 1
        while True:
            file_name = f"offer_compare_{counter}{ext}"
            file_path = os.path.join(output_dir, file_name)
            if not os.path.exists(file_path):
                break
            counter += 1

        dim_rows = [
            ("综合", "overall_score"),
            ("竞争力", "competitive_score"),
            ("成长性", "growth_score"),
            ("风险", "risk_score"),
            ("薪资满意度", "salary_score"),
            ("通勤便利", "commute_score"),
            ("工作生活平衡", "wlb_score"),
            ("文化匹配", "culture_score"),
            ("稳定性", "stability_score"),
        ]
        header = ["维度"] + [o.get("company") or f"Offer {i + 1}" for i, o in enumerate(offers)]
        lines = [
            "# 多 Offer 对比报告",
            "",
            f"对比数量：{len(offers)}",
            "",
            "## 分数对比",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join([" --- " for _ in header]) + "|",
        ]
        for label, key in dim_rows:
            row = [label] + [str((o.get("result") or {}).get(key) or "-") for o in offers]
            lines.append("| " + " | ".join(row) + " |")

        lines.extend(["", "## 各 Offer 详情", ""])
        for i, o in enumerate(offers, 1):
            res = o.get("result") or {}
            lines.extend(
                [
                    f"### {i}. {o.get('company') or '未命名'} · {o.get('title') or '-'}",
                    "",
                    f"- 地点：{o.get('location') or '-'} | 月薪/总包：{o.get('salary') or '-'} | 级别：{o.get('level') or '-'}",
                    f"- 综合评分：{res.get('overall_score') or '-'} / 10",
                    "",
                    "**优势**",
                ]
            )
            pros = res.get("pros") or []
            lines.extend([f"- {p}" for p in pros] if pros else ["- 暂无"])
            cons = res.get("cons") or []
            lines.extend(["", "**风险 / 劣势**"])
            lines.extend([f"- {c}" for c in cons] if cons else ["- 暂无"])
            levers = res.get("negotiation_levers") or []
            if levers:
                lines.extend(["", "**谈判杠杆**"])
                lines.extend([f"- {item}" for item in levers])
            lines.append("")

        lines.extend(["", "## 推荐", ""])
        best = max(offers, key=lambda o: (o.get("result") or {}).get("overall_score") or 0)
        lines.append(
            f"综合评分最高：**{best.get('company') or '未命名'}**（"
            f"{(best.get('result') or {}).get('overall_score') or '-'} / 10）。"
        )
        lines.append("建议结合个人优先级（薪资、成长、稳定性、通勤等）做最终决策。")

        md = "\n".join(lines)
        try:
            if html_content:
                # 原封不动：保存完整 HTML（对比表格 + LLM 分析 + 布局）
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md)
        except Exception as e:  # noqa: BLE001
            logger.warning("offer compare save failed writing %s: %s", file_path, e)
            _send_error(self, 500, f"保存失败: {e}")
            return

        db = get_db()
        try:
            catalog_file(
                db, None, TYPE_OFFER_COMPARE, file_path, company="多Offer对比", job_title=file_name
            )
        finally:
            db.close()
        _send_json(
            self, {"ok": True, "file_path": file_path.replace("\\", "/"), "file_name": file_name}
        )

    def _api_salary_advice(self):
        """POST /api/salary-advice -- generate salary negotiation advice via LLM."""
        import asyncio

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.salary_advice import get_advice

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        company = (body.get("company") or "").strip()
        if not company:
            _send_error(self, 400, "缺少 company")
            return
        config = load_config()
        provider = create_provider(config)

        async def _run():
            return await get_advice(
                config,
                provider,
                company=company,
                title=body.get("title", ""),
                salary=body.get("salary", ""),
                target=body.get("target", ""),
                strengths=body.get("strengths", ""),
                context=body.get("context", ""),
                floor=body.get("floor", ""),
                negotiator=body.get("negotiator", ""),
                monthly_base=body.get("monthly_base", ""),
                pay_months=body.get("pay_months", ""),
                annual_total=body.get("annual_total", ""),
            )

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run())
        except Exception as e:  # noqa: BLE001
            logger.warning("salary_advice failed: %s", e)
            _send_error(self, 500, f"建议生成失败: {e}")
            return
        finally:
            loop.close()
        _send_json(self, result)

    def _api_salary_advice_save(self):
        """POST /api/salary-advice/save -- save advice as markdown + catalog."""
        import os

        from agent_core.pipeline.file_catalog import TYPE_SALARY_ADVICE, catalog_file
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        company = (body.get("company") or "").strip()
        title = (body.get("title") or "").strip()
        if not company:
            _send_error(self, 400, "缺少 company")
            return

        def _safe_filename(text):
            keep = []
            for ch in text:
                if ch.isalnum() or ch in ("_", "-", ".", "·"):
                    keep.append(ch)
                else:
                    keep.append("_")
            return "".join(keep).strip("_") or "unknown"

        base_name = f"{_safe_filename(company)}_salary_advice"
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        file_name = f"{base_name}.md"
        file_path = os.path.join(output_dir, file_name)
        counter = 1
        stem = base_name
        while os.path.exists(file_path):
            file_name = f"{stem}_{counter}.md"
            file_path = os.path.join(output_dir, file_name)
            counter += 1

        anchor = body.get("anchor") or ""
        leverage = body.get("leverage") or []
        concessions = body.get("concessions") or []
        scripts = body.get("scripts") or []
        confidence = body.get("confidence") or ""

        lines = [
            f"# {company} 薪资谈判策略",
            "",
            "## 基本信息",
            "",
            f"- 公司：{company}",
            f"- 职位：{title or '-'}",
            f"- 当前 Offer：{body.get('salary') or '-'}",
            f"- 目标：{body.get('target') or '-'}",
            "",
            "## 锚定薪资",
            "",
            anchor or "暂无",
            "",
            f"**置信度**：{confidence or '-'}",
            "",
            "## 杠杆点",
            "",
        ]
        if leverage:
            lines.extend([f"- {x}" for x in leverage])
        else:
            lines.append("暂无")
        lines.extend(["", "## 让步计划", ""])
        if concessions:
            lines.extend([f"- {x}" for x in concessions])
        else:
            lines.append("暂无")
        lines.extend(["", "## 话术", ""])
        if scripts:
            lines.extend([f"- {x}" for x in scripts])
        else:
            lines.append("暂无")

        md = chr(10).join(lines)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md)
        except Exception as e:  # noqa: BLE001
            logger.warning("salary advice save failed writing %s: %s", file_path, e)
            _send_error(self, 500, f"保存失败: {e}")
            return

        db = get_db()
        try:
            catalog_file(
                db,
                None,
                TYPE_SALARY_ADVICE,
                file_path,
                company=company,
                job_title=title,
            )
        finally:
            db.close()
        _send_json(
            self,
            {"ok": True, "file_path": file_path.replace(os.sep, "/"), "file_name": file_name},
        )

    def _api_materials_regenerate(self):
        """POST /api/materials/regenerate {job_id, feedback} -- regenerate with feedback."""
        import asyncio

        from agent_core.config import load_config
        from agent_core.llm.providers import create_provider
        from agent_core.pipeline.cover_letter import generate_cover_letter
        from agent_core.pipeline.enrichment import enrich_job_jd
        from agent_core.pipeline.tailor import tailor_resume
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        job_id = body.get("job_id")
        feedback = body.get("feedback") or ""
        if not job_id:
            _send_json(self, {"ok": False, "message": "缺少 job_id"})
            return
        config = load_config()
        provider = create_provider(config)
        conn = get_db()
        try:
            r = conn.execute(
                "SELECT id, title, company, location, description, urls, platforms, "
                "direction, security_id, lid "
                "FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
        if not r:
            _send_json(self, {"ok": False, "message": "职位未找到"})
            return

        class _Job:
            pass

        d = dict(r)
        job = _Job()
        job.id = d["id"]
        job.title = d["title"] or ""
        job.company = d["company"] or ""
        job.location = d["location"] or ""
        job.description = d["description"] or ""
        # DB stores urls/platforms as JSON strings; parse to real dict/list —
        # enrich_job_jd calls .keys() on urls, so it must be a dict not str.
        try:
            job.urls = json.loads(d["urls"] or "{}")
        except Exception:
            job.urls = {}
        try:
            job.platforms = json.loads(d["platforms"] or "[]")
        except Exception:
            job.platforms = []
        job.direction = d["direction"] or ""
        # enrich_job_jd reads security_id/lid when the description lacks JD
        # keywords — without these attrs it AttributeErrors (same bug that
        # previously broke _api_materials_generate for jobs with no cached JD).
        job.security_id = d.get("security_id") or ""
        job.lid = d.get("lid") or ""

        _set_materials_progress(
            running=True,
            done=0,
            total=1,
            current=f"{job.title} @ {job.company}",
            status="正在生成简历/HR消息...",
        )
        prep_errors: list[dict] = []

        async def _gen(job, llm_provider):
            enriched = await enrich_job_jd(job, config)
            resume_md = await tailor_resume(
                enriched,
                config,
                llm_provider,
                feedback=feedback or None,
            )
            hr_msg = await generate_cover_letter(
                enriched,
                config,
                llm_provider,
                feedback=feedback or None,
            )
            # 面试准备一起重做（用同一个改进意见）。失败不影响简历/HR消息落库。
            # v12: 与 generate 一致——不再立即 catalog，改存 material_drafts
            # 草稿列，确认后才归档。
            try:
                from pathlib import Path

                from agent_core.pipeline.interview_prep import (
                    predict_questions,
                    save_interview_prep,
                )

                _set_materials_progress(
                    done=0,
                    total=1,
                    current=f"{job.title} @ {job.company}",
                    status="正在生成面试准备...",
                )
                try:
                    qs = await predict_questions(
                        enriched,
                        config,
                        llm_provider,
                        direction=job.direction,
                        feedback=feedback or None,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "interview prep regenerate failed (%s); retrying once",
                        e,
                    )
                    qs = await predict_questions(
                        enriched,
                        config,
                        llm_provider,
                        direction=job.direction,
                        feedback=feedback or None,
                    )
                prep_md_path = save_interview_prep(qs, enriched)
                prep_md_text = Path(prep_md_path).read_text(encoding="utf-8")
                prep_conn = get_db()
                try:
                    prep_conn.execute(
                        "UPDATE material_drafts SET interview_prep_md=?, "
                        "interview_confirmed=0, updated_at=? WHERE job_id=?",
                        (prep_md_text, datetime.now(UTC).isoformat(), job.id),
                    )
                    prep_conn.commit()
                finally:
                    prep_conn.close()
            except Exception as e:  # noqa: BLE001 — prep regen is best-effort
                logger.warning("interview prep regenerate failed for %s: %s", job.id, e)
                prep_errors.append({"job_id": job.id, "error": str(e)})
            return resume_md, hr_msg

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            try:
                resume_md, hr_msg = loop.run_until_complete(_gen(job, provider))
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "materials regenerate failed for %s (%s); retrying once",
                    job_id,
                    e,
                )
                resume_md, hr_msg = loop.run_until_complete(_gen(job, provider))
        finally:
            loop.close()
        _set_materials_progress(running=False, done=1, total=1, current="", status="")
        now = datetime.now(UTC).isoformat()
        c = get_db()
        try:
            # 再生成后清空 feedback，避免“意见已应用却还留在输入框/草稿里”的困惑。
            # 用户如果需要再次调整，可以重新填写。
            c.execute(
                "UPDATE material_drafts SET resume_md=?, hr_message=?, feedback='', "
                "version=version+1, status='draft', updated_at=? WHERE job_id=?",
                (resume_md, hr_msg, now, job_id),
            )
            c.commit()
            version = c.execute(
                "SELECT version FROM material_drafts WHERE job_id=?", (job_id,)
            ).fetchone()[0]
        finally:
            c.close()
        resp: dict = {"ok": True, "job_id": job_id, "version": version}
        if prep_errors:
            resp["interview_prep_failed"] = prep_errors
        _send_json(self, resp)

    def _api_materials_delete(self):
        """DELETE /api/materials {job_ids:[...]} -- delete material draft records."""
        import re

        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        job_ids = body.get("job_ids") or []
        if not job_ids or not isinstance(job_ids, list):
            _send_json(self, {"ok": False, "message": "job_ids 不能为空"})
            return
        conn = get_db()
        try:
            q = ",".join("?" * len(job_ids))
            # v12: 删除草稿时同步清理面试准备 —— generated_files 里已登记的
            # interview_prep 记录（确认过才有）+ 磁盘上未登记的 .md/.json。
            rows = conn.execute(
                f"SELECT id, company, title FROM jobs WHERE id IN ({q})", job_ids
            ).fetchall()
            cur = conn.execute(f"DELETE FROM material_drafts WHERE job_id IN ({q})", job_ids)
            for r in rows:
                conn.execute(
                    "DELETE FROM generated_files WHERE job_id=? AND file_type='interview_prep'",
                    (r["id"],),
                )
                safe_company = re.sub(r'[\\/*?:"<>|]', "", r["company"] or "")[:20]
                safe_title = re.sub(r'[\\/*?:"<>|]', "", r["title"] or "")[:20]
                for suffix in (".md", ".json"):
                    p = f"output/{safe_company}_{safe_title}_interview{suffix}"
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        pass
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()
        _send_json(self, {"ok": True, "deleted": deleted})

    def _api_materials_confirm(self):
        """POST /api/materials/confirm {job_id} -- confirm draft, save + catalog."""
        from agent_core.pipeline.cover_letter import save_cover_letter
        from agent_core.pipeline.file_catalog import (
            TYPE_COVER_LETTER,
            TYPE_TAILORED_RESUME,
            catalog_file,
        )
        from agent_core.pipeline.tailor import save_resume
        from agent_core.platforms.base import Job
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        job_id = body.get("job_id")
        if not job_id:
            _send_json(self, {"ok": False, "message": "缺少 job_id"})
            return
        conn = get_db()
        try:
            job_row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            draft_row = conn.execute(
                "SELECT resume_md, hr_message FROM material_drafts WHERE job_id=?", (job_id,)
            ).fetchone()
            if not job_row or not draft_row:
                _send_json(self, {"ok": False, "message": "职位或草稿不存在"})
                return
            job = Job.from_storage(job_row)
            paths = save_resume(draft_row["resume_md"], job)
            hr_path = save_cover_letter(draft_row["hr_message"], job)
            catalog_file(
                conn,
                job_id,
                TYPE_TAILORED_RESUME,
                paths["md"],
                direction=job.direction or "",
                company=job.company or "",
                job_title=job.title or "",
            )
            catalog_file(
                conn,
                job_id,
                TYPE_TAILORED_RESUME,
                paths["docx"],
                direction=job.direction or "",
                company=job.company or "",
                job_title=job.title or "",
            )
            catalog_file(
                conn,
                job_id,
                TYPE_COVER_LETTER,
                hr_path,
                direction=job.direction or "",
                company=job.company or "",
                job_title=job.title or "",
            )
            # v12: 确认面试准备 —— 磁盘文件生成时已落盘（未登记），现在归档到
            # generated_files（出现在「已生成文件」TAB），并解锁模拟面试
            # from-prep 题库。文件名规则与 save_interview_prep 一致。
            import re as _re

            from agent_core.pipeline.file_catalog import TYPE_INTERVIEW_PREP

            safe_company = _re.sub(r'[\\/*?:"<>|]', "", job.company or "")[:20]
            safe_title = _re.sub(r'[\\/*?:"<>|]', "", job.title or "")[:20]
            prep_base = f"output/{safe_company}_{safe_title}_interview"
            prep_draft = conn.execute(
                "SELECT interview_prep_md FROM material_drafts WHERE job_id=?", (job_id,)
            ).fetchone()
            if prep_draft and prep_draft["interview_prep_md"]:
                # v12.1 自愈：磁盘 .md 丢失（误删/清理）时，从草稿列重建人读版，
                # 避免"已生成文件"只剩机器读 .json、没有面试者题库。
                md_path = prep_base + ".md"
                if not os.path.exists(md_path):
                    try:
                        with open(md_path, "w", encoding="utf-8") as f:
                            f.write(prep_draft["interview_prep_md"])
                    except OSError:
                        pass  # best-effort，重建失败不阻断归档
                for suffix in (".md", ".json"):
                    prep_path = prep_base + suffix
                    if os.path.exists(prep_path):
                        catalog_file(
                            conn,
                            job_id,
                            TYPE_INTERVIEW_PREP,
                            prep_path,
                            direction=job.direction or "",
                            company=job.company or "",
                            job_title=job.title or "",
                        )
                conn.execute(
                    "UPDATE material_drafts SET interview_confirmed=1, updated_at=? WHERE job_id=?",
                    (datetime.now(UTC).isoformat(), job_id),
                )
            conn.execute(
                "UPDATE material_drafts SET status='confirmed', updated_at=? WHERE job_id=?",
                (datetime.now(UTC).isoformat(), job_id),
            )
            # Auto-create application record so it shows in 投递追踪 with reminders.
            now_iso = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO applications (job_id, status, applied_at, updated_at, notes) "
                "VALUES (?, '待投递', ?, ?, '')",
                (job_id, now_iso, now_iso),
            )
            conn.commit()
        finally:
            conn.close()
        _send_json(
            self,
            {"ok": True, "job_id": job_id, "resume_docx": paths["docx"], "hr_message": hr_path},
        )

    def _api_applications(self):
        """GET /api/applications -- list applications joined with job info."""
        from agent_core.storage.db import get_db

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT a.id, a.job_id, a.status, a.applied_at, a.updated_at, a.notes, "
                "j.title AS job_title, j.company, j.direction, j.urls "
                "FROM applications a LEFT JOIN jobs j ON j.id=a.job_id "
                "ORDER BY a.updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
        _send_json(self, {"ok": True, "items": [dict(r) for r in rows]})

    def _api_application_create(self):
        """POST /api/application {job_id, status?} -- manually add an application record."""
        from agent_core.storage.db import get_db

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 65536:
            _send_error(self, 400, "Invalid content length")
            return
        data = _read_json_body(self)
        if not data:
            _send_error(self, 400, "Invalid JSON")
            return
        job_id = str(data.get("job_id") or "").strip()
        status = str(data.get("status") or "待投递").strip()
        if not job_id:
            _send_error(self, 400, "缺少 job_id")
            return
        if not status:
            status = "待投递"
        conn = get_db()
        try:
            job = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                _send_error(self, 404, f"岗位不存在: {job_id}")
                return
            now = datetime.now(UTC).isoformat()
            cur = conn.execute(
                "INSERT INTO applications (job_id, status, applied_at, updated_at, notes) "
                "VALUES (?,?,?,?,?)",
                (job_id, status, now, now, ""),
            )
            conn.commit()
            app_id = cur.lastrowid
        finally:
            conn.close()
        _send_json(self, {"ok": True, "id": app_id})

    def _api_application_update(self):
        """POST /api/application/update {id, status, notes?} -- manual status change.

        Identifies the row by application ``id`` (primary key), NOT job_id, so
        only the selected row is touched even if duplicate job_id rows existed
        historically.
        """
        from agent_core.storage.db import get_db

        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        app_id = body.get("id")
        status = body.get("status")
        notes = body.get("notes")
        if not app_id or not status:
            _send_json(self, {"ok": False, "message": "缺少 id 或 status"})
            return
        now = datetime.now(UTC).isoformat()
        conn = get_db()
        try:
            # 读旧状态，状态变化时写 timeline（与 tracker.update_status 一致，
            # 保证 dashboard 改状态也有历史审计）。
            old = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
            if old is None:
                _send_json(self, {"ok": False, "message": f"投递记录不存在: {app_id}"})
                return
            old_status = old["status"]
            if notes is not None:
                conn.execute(
                    "UPDATE applications SET status=?, updated_at=?, notes=? WHERE id=?",
                    (status, now, notes, app_id),
                )
            else:
                conn.execute(
                    "UPDATE applications SET status=?, updated_at=? WHERE id=?",
                    (status, now, app_id),
                )
            if status != old_status:
                conn.execute(
                    "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (app_id, old_status, status, now),
                )
            conn.commit()
        finally:
            conn.close()
        _send_json(self, {"ok": True, "id": app_id, "status": status})

    def _api_application_reminder(self):
        """POST /api/application/reminder {days} -- set reminder period (stored in scheduler_state)."""
        import json as _json
        from pathlib import Path

        state_file = Path("data/scheduler_state.json")
        int(self.headers.get("Content-Length", 0))
        body = _read_json_body(self)
        days = int(body.get("days", 3))
        if days < 1:
            days = 1
        state = {}
        if state_file.exists():
            try:
                state = _json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        state["reminder_days"] = days
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(_json.dumps(state, indent=2), encoding="utf-8")
        _send_json(self, {"ok": True, "reminder_days": days})

    def _api_delete_application(self, params: dict[str, list[str]]) -> None:
        """DELETE /api/application?id=... -- delete an application record by id.

        Deletes any timeline rows referencing this application first, otherwise
        PRAGMA foreign_keys=ON blocks the delete for applications that have
        status-change history.
        """
        from agent_core.storage.db import get_db

        app_id = (params.get("id", [""])[0] or "").strip()
        if not app_id:
            _send_error(self, 400, "Missing id")
            return
        conn = get_db()
        try:
            conn.execute("DELETE FROM timelines WHERE application_id=?", (app_id,))
            conn.execute("DELETE FROM applications WHERE id=?", (app_id,))
            conn.commit()
        finally:
            conn.close()
        _send_json(self, {"ok": True, "id": app_id})

    def _api_delete_file(self, params: dict[str, list[str]]) -> None:
        """DELETE /api/file?path=... -- delete a generated file (disk + catalog)."""
        from agent_core.storage.db import get_db

        rel_path = (params.get("path", [""])[0] or "").strip()
        if not rel_path:
            _send_error(self, 400, "Missing path")
            return
        safe_path = os.path.realpath(os.path.join("output", rel_path))
        output_root = os.path.realpath("output")
        if not safe_path.startswith(output_root + os.sep):
            _send_error(self, 403, "Access denied")
            return
        conn = get_db()
        try:
            conn.execute("DELETE FROM generated_files WHERE file_name=?", (rel_path,))
            conn.commit()
        finally:
            conn.close()
        try:
            if os.path.isfile(safe_path):
                os.remove(safe_path)
        except OSError as e:
            logger.warning("delete file failed: %s", e)
        _send_json(self, {"ok": True, "path": rel_path})

    def _api_file_content(self, params):
        """GET /api/file?path=... -- read and return file content. Path-validated."""
        rel_path = params.get("path", [""])[0]
        if not rel_path:
            _send_error(self, 400, "Missing path parameter")
            return
        safe_path = os.path.realpath(os.path.join("output", rel_path))
        output_root = os.path.realpath("output")
        if not safe_path.startswith(output_root + os.sep):
            _send_error(self, 403, "Access denied")
            return
        if not os.path.isfile(safe_path):
            _send_error(self, 404, "File not found")
            return
        ext = os.path.splitext(safe_path)[1].lower()
        download = params.get("download", [""])[0] == "1"
        try:
            if download and ext == ".md":
                # Download .md as .txt with Windows line breaks (\r\n)
                download_name = os.path.splitext(rel_path)[0] + ".txt"
                with open(safe_path, encoding="utf-8") as f:
                    content = f.read()
                content = content.replace("\r\n", "\n").replace("\n", "\r\n")
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                from urllib.parse import quote

                self.send_header(
                    "Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}"
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif ext == ".md":
                with open(safe_path, encoding="utf-8") as f:
                    content = f.read()
                _send_json(self, {"path": rel_path, "content": content})
            elif ext == ".html":
                # Offer eval HTML (radar chart + layout) -- preview content.
                # download=1 serves raw file for browser rendering.
                with open(safe_path, encoding="utf-8") as f:
                    content = f.read()
                if download:
                    body = content.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    from urllib.parse import quote

                    self.send_header(
                        "Content-Disposition", f"attachment; filename*=UTF-8''{quote(rel_path)}"
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    _send_json(self, {"path": rel_path, "content": content, "is_html": True})
            elif ext == ".txt":
                # Plain-text files (mock interview assessment, transcripts...)
                # -- return content so the dashboard can preview them.
                with open(safe_path, encoding="utf-8") as f:
                    content = f.read()
                if download:
                    body = content.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    from urllib.parse import quote

                    self.send_header(
                        "Content-Disposition", f"attachment; filename*=UTF-8''{quote(rel_path)}"
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    _send_json(self, {"path": rel_path, "content": content})
            else:
                # Binary files (docx, etc.) -- return raw bytes
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                from urllib.parse import quote

                self.send_header(
                    "Content-Disposition", f"attachment; filename*=UTF-8''{quote(rel_path)}"
                )
                self.send_header("Content-Length", str(os.path.getsize(safe_path)))
                self.end_headers()
                with open(safe_path, "rb") as f:
                    self.wfile.write(f.read())
        except Exception as e:
            _send_error(self, 500, f"Failed to read file: {e}")

    # ----------------------------------------------------------- OpenAPI ---
    def _serve_openapi(self) -> None:
        _send_json(self, OPENAPI_SPEC)

    # Silence BaseHTTPRequestHandler's default stderr logging

    def _api_realtime_config(self) -> None:
        """GET /api/realtime/config -- return realtime voice config for frontend."""
        from agent_core.config import load_config

        config = load_config()
        enabled = bool(config.realtime.enabled and config.volc_app_id and config.volc_access_key)
        _send_json(
            self,
            {
                "enabled": enabled,
                "ws_port": config.realtime.ws_port,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Override to use logger instead of stderr."""
        logger.info("%s - %s", self.client_address[0], format % args)


_REMINDER_CHECK_INTERVAL_SECONDS = 3600


def _application_reminder_loop(db_path: str) -> None:
    """Background reminder checker.

    The dashboard is the long-lived process, so the application follow-up
    reminder is decoupled from the optional search scheduler.  It reads the
    reminder period that the user configured on the 投递追踪 tab and keeps
    it stored in data/scheduler_state.json (same file as the scheduler).
    """
    from agent_core.config import load_config
    from agent_core.scheduler.scheduler import check_application_reminders
    from agent_core.storage.db import get_db

    logger.info(
        "Application reminder loop started (interval %ss)", _REMINDER_CHECK_INTERVAL_SECONDS
    )
    while True:
        try:
            config = load_config()
            conn = get_db(db_path)
            try:
                check_application_reminders(config, conn)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 -- background loop must survive
            logger.warning("Application reminder check failed: %s", e)
        time.sleep(_REMINDER_CHECK_INTERVAL_SECONDS)


def _start_application_reminder_thread(db_path: str) -> None:
    threading.Thread(
        target=_application_reminder_loop,
        args=(db_path,),
        name="application-reminder-loop",
        daemon=True,
    ).start()


def start_server(port: int = 8765, db_path: str = "data/agent.db") -> None:
    """Start the dashboard HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Run migrations + backfill the generated_files catalog once at startup.
    # migrate() is idempotent; backfill_from_disk only inserts rows for files
    # not already cataloged, so this is safe on every boot.
    from agent_core.pipeline.file_catalog import backfill_from_disk
    from agent_core.storage.db import get_db, migrate

    _init_db = get_db(db_path)
    migrate(_init_db)
    backfill_from_disk(_init_db, "output")
    _init_db.close()

    Handler.db_path = db_path
    _start_application_reminder_thread(db_path)
    token = os.environ.get("AGENT_DASHBOARD_TOKEN", "")
    auth_status = "enabled" if token else "disabled (dev mode)"
    logger.info("Dashboard starting on http://localhost:%d (auth: %s)", port, auth_status)

    # Start realtime voice WS proxy (mock interview 实时语音). No-op when
    # realtime disabled or VOLC creds missing.
    try:
        from agent_core.config import load_config
        from agent_core.server.realtime_proxy import start_proxy_in_thread

        _rt_cfg = load_config()
        start_proxy_in_thread(_rt_cfg, db_path=db_path)
    except Exception as e:
        logger.warning("Realtime proxy start skipped: %s", e)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def run_dashboard():
    """CLI entry point: python -m agent_core.server.serve [--port PORT]"""
    import argparse

    parser = argparse.ArgumentParser(description="岗位雷达 Dashboard")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--stop", action="store_true", help="Stop running dashboard")
    args = parser.parse_args()
    if args.stop:
        _stop_dashboard()
    else:
        start_server(port=args.port)


if __name__ == "__main__":
    run_dashboard()
