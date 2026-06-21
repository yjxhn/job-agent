"""Local HTTP dashboard with sortable/filterable job table and timeline.

Features:
- /          — Interactive HTML dashboard
- /api/results      — GET job listings (paginated)
- /api/timeline     — GET timeline events (paginated, filterable)
- /api/openapi.json — OpenAPI 3.0 spec
- /docs             — Swagger UI

Auth: Bearer token via AGENT_DASHBOARD_TOKEN env var (dev-mode off when unset).
"""
# ruff: noqa: E501  — inline CSS/JS/HTML templates, long lines by design

import json
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


class _AuthRequired(Exception):
    """Raised internally when Bearer auth check fails."""


HTML = r"""<!DOCTYPE html><html lang="zh-CN">
<head><meta charset="utf-8"><title>求职Agent Dashboard</title>
<style>
:root{--bg:#f5f5f5;--card:#fff;--text:#1a1a2e;--muted:#6b7280;--border:#e5e7eb;--accent:#2563eb}
body{font-family:'Segoe UI','Microsoft YaHei',system-ui,sans-serif;max-width:1400px;margin:0 auto;padding:20px 24px;background:var(--bg);color:var(--text)}
h1{font-size:1.6rem;font-weight:700;margin:0 0 4px;letter-spacing:-.02em}
.subtitle{color:var(--muted);font-size:.85rem;margin:0 0 20px}
/* Tabs */
.tabs{display:flex;gap:0;margin:0 0 16px;border-bottom:2px solid var(--border)}
.tab{padding:10px 24px;cursor:pointer;font-size:.88rem;font-weight:600;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-2px;transition:color .15s,border-color .15s;user-select:none}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
/* Bar */
.bar{display:flex;gap:12px;margin:12px 0;align-items:center;flex-wrap:wrap}
input,select{padding:7px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;background:var(--card);outline:none;transition:border-color .15s}
input:focus,select:focus{border-color:var(--accent)}
/* Table */
.panel{display:none}.panel.show{display:block}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
th{background:#1e293b;color:#e2e8f0;padding:10px 14px;text-align:left;cursor:pointer;user-select:none;font-size:.8rem;font-weight:600;letter-spacing:.03em;text-transform:uppercase}
th:hover{background:#334155}td{padding:9px 14px;border-bottom:1px solid var(--border);font-size:.85rem}
tr:hover{background:#f8fafc}.score{font-weight:700;border-radius:6px;padding:3px 10px;color:#fff;font-size:.78rem}
.s-high{background:#16a34a}.s-mid{background:#d97706}.s-low{background:#dc2626}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.refresh{color:var(--accent);cursor:pointer;text-decoration:underline;font-size:.85rem}
/* Timeline */
.tl-container{padding:8px 0}
.tl-item{position:relative;padding:0 0 0 40px;margin:0 0 28px}
.tl-item:last-child{margin-bottom:0}
/* vertical line */
.tl-item::before{content:'';position:absolute;left:15px;top:28px;bottom:-28px;width:2px;background:var(--border)}
.tl-item:last-child::before{display:none}
/* dot */
.tl-dot{position:absolute;left:8px;top:4px;width:16px;height:16px;border-radius:50%;border:3px solid var(--card);box-shadow:0 0 0 2px var(--dot-color,#6366f1),0 2px 4px rgba(0,0,0,.12);z-index:1}
/* stages color map */
.tl-dot.st-search{--dot-color:#6b7280} .tl-dot.st-match{--dot-color:#8b5cf6}
.tl-dot.st-apply{--dot-color:#2563eb} .tl-dot.st-prescreen{--dot-color:#f59e0b}
.tl-dot.st-interview{--dot-color:#0891b2} .tl-dot.st-offer{--dot-color:#10b981}
.tl-dot.st-onboard{--dot-color:#ec4899} .tl-dot.st-terminated{--dot-color:#ef4444}
/* card */
.tl-card{background:var(--card);border-radius:10px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.05),0 0 0 1px var(--border);transition:box-shadow .15s}
.tl-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.08),0 0 0 1px var(--border)}
.tl-header{display:flex;align-items:center;gap:10px;margin:0 0 6px;flex-wrap:wrap}
.tl-badge{padding:3px 10px;border-radius:20px;font-size:.72rem;font-weight:700;letter-spacing:.02em;color:#fff}
.bg-search{background:#6b7280}.bg-match{background:#8b5cf6}.bg-apply{background:#2563eb}
.bg-prescreen{background:#f59e0b}.bg-interview{background:#0891b2}.bg-offer{background:#10b981}
.bg-onboard{background:#ec4899}.bg-terminated{background:#ef4444}
.tl-arrow{color:var(--muted);font-size:.75rem;font-weight:600}
.tl-job{font-weight:700;font-size:.9rem;color:var(--text)}
.tl-company{font-size:.8rem;color:var(--muted)}
.tl-meta{font-size:.75rem;color:#9ca3af;margin:4px 0 0}
.tl-empty{text-align:center;padding:60px 20px;color:var(--muted)}
.tl-empty-icon{font-size:2.5rem;margin:0 0 10px;opacity:.4}
/* Stats row */
.stats{display:flex;gap:12px;margin:0 0 18px;flex-wrap:wrap}
.stat-pill{padding:5px 14px;border-radius:20px;font-size:.78rem;font-weight:600;color:#fff}
/* Pagination */
.pgn{display:flex;gap:8px;align-items:center;margin:16px 0 0;font-size:.82rem;color:var(--muted);flex-wrap:wrap}
.pgn-btn{padding:5px 14px;border:1.5px solid var(--border);border-radius:6px;cursor:pointer;background:var(--card);color:var(--text);font-size:.82rem;transition:all .15s}
.pgn-btn:hover{border-color:var(--accent);color:var(--accent)}
.pgn-btn:disabled{opacity:.35;cursor:default}
.pgn-info{font-size:.8rem;color:var(--muted)}
</style></head>
<body>
<h1>求职Agent Dashboard</h1>
<p class="subtitle">实时岗位追踪与投递时间线 | <a href="/docs" style="font-size:.8rem">API Docs</a></p>
<div class="tabs">
<div class="tab active" onclick="switchTab('jobs')">岗位列表</div>
<div class="tab" onclick="switchTab('timeline')">时间线</div>
</div>

<!-- Jobs Panel -->
<div id="jobs-panel" class="panel show">
<div class="bar">
<input id="filter" placeholder="搜索公司/岗位..." oninput="renderJobs()">
<select id="dirFilter" onchange="renderJobs()"><option value="">全部方向</option><option>industrial_ai_agent</option><option>equipment_amr</option></select>
<span class="refresh" onclick="location.reload()">刷新</span>
<span style="color:#666;margin-left:auto" id="ts"></span>
</div>
<table><thead><tr>
<th onclick="sort('score')">评分</th><th onclick="sort('title')">岗位</th>
<th onclick="sort('company')">公司</th><th onclick="sort('location')">地点</th>
<th>方向</th><th>链接</th></tr></thead>
<tbody id="tb"></tbody></table>
<div id="jobsPgn" class="pgn"></div>
</div>

<!-- Timeline Panel -->
<div id="timeline-panel" class="panel">
<div class="bar">
<input id="tlFilter" placeholder="搜索公司/岗位..." oninput="renderTimeline()">
<select id="tlEventFilter" onchange="renderTimeline()">
<option value="">全部事件</option>
<option value="已投递">已投递</option>
<option value="HR已读">HR已读</option>
<option value="约面">约面</option>
<option value="一面">一面</option>
<option value="二面">二面</option>
<option value="Offer">Offer</option>
<option value="入职">入职</option>
<option value="已终止">已终止</option>
</select>
<span style="color:#666;margin-left:auto;font-size:.8rem" id="tlStats"></span>
</div>
<div id="tlContainer" class="tl-container"></div>
<div id="tlPgn" class="pgn"></div>
</div>

<script>
// --- shared helpers ---
function escHtml(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML}

function stageClass(status){
  if(!status)return'st-search';
  if(status.includes('投递'))return'st-apply';
  if(status.includes('读'))return'st-prescreen';
  if(status.includes('面')||status.includes('约'))return'st-interview';
  if(status.includes('Offer'))return'st-offer';
  if(status.includes('入职'))return'st-onboard';
  if(status.includes('终止'))return'st-terminated';
  return'st-search';
}
function badgeClass(status){
  if(!status)return'bg-search';
  if(status.includes('投递'))return'bg-apply';
  if(status.includes('读'))return'bg-prescreen';
  if(status.includes('面')||status.includes('约'))return'bg-interview';
  if(status.includes('Offer'))return'bg-offer';
  if(status.includes('入职'))return'bg-onboard';
  if(status.includes('终止'))return'bg-terminated';
  return'bg-search';
}
function fmtDate(iso){if(!iso)return'';var d=new Date(iso);return d.toLocaleDateString('zh-CN')+' '+d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}

// --- jobs panel ---
let allJobs=[],sortKey='score',sortAsc=false;
let jobsPage=1,jobsPages=1,jobsTotal=0;
function sort(k){sortAsc=sortKey===k?!sortAsc:false;sortKey=k;renderJobs()}
function loadJobs(page){
  jobsPage=page||1;
  fetch('/api/results?page='+jobsPage+'&page_size=30').then(function(r){return r.json()})
  .then(function(p){allJobs=p.items||p;jobsPages=p.pages||1;jobsTotal=p.total||allJobs.length;renderJobs();renderJobsPgn()});
}
function renderJobsPgn(){
  var el=document.getElementById('jobsPgn');
  el.innerHTML='<button class="pgn-btn" '+(jobsPage<=1?'disabled':'')+' onclick="loadJobs('+(jobsPage-1)+')">上一页</button>'+
    '<span class="pgn-info">第 '+jobsPage+' / '+jobsPages+' 页 共 '+jobsTotal+' 条</span>'+
    '<button class="pgn-btn" '+(jobsPage>=jobsPages?'disabled':'')+' onclick="loadJobs('+(jobsPage+1)+')">下一页</button>';
}
function renderJobs(){
  let f=document.getElementById('filter').value.toLowerCase();
  let df=document.getElementById('dirFilter').value;
  let rows=allJobs.filter(function(j){return(j.title||'').toLowerCase().includes(f)||(j.company||'').toLowerCase().includes(f)||(j.location||'').toLowerCase().includes(f)})
  .filter(function(j){return !df||j.direction===df});
  rows.sort(function(a,b){var va=a[sortKey]||'',vb=b[sortKey]||'';return typeof va==='number'?(sortAsc?va-vb:vb-va):sortAsc?(''+va).localeCompare(''+vb):(''+vb).localeCompare(''+va)});
  document.getElementById('tb').innerHTML=rows.map(function(j){
    var sc=j.score||j.rating||0;var cls=sc>=75?'s-high':sc>=50?'s-mid':'s-low';
    var urls=JSON.parse(j.urls||'{}');
    var links=Object.entries(urls).map(function(e){return'<a href="'+escHtml(e[1])+'" target="_blank">'+escHtml(e[0])+'</a>'}).join(' ');
    return'<tr><td><span class="score '+cls+'">'+sc+'%</span></td><td>'+escHtml(j.title)+'</td><td>'+escHtml(j.company)+'</td><td>'+escHtml(j.location)+'</td><td>'+escHtml(j.direction)+'</td><td>'+links+'</td></tr>'}).join('');
  document.getElementById('ts').textContent=new Date().toLocaleTimeString()
}

// --- timeline panel ---
let allTimeline=[];
let tlPage=1,tlPages=1,tlTotal=0;
function switchTab(t){
  document.querySelectorAll('.tab').forEach(function(el){el.classList.toggle('active',el.textContent===(t==='jobs'?'岗位列表':'时间线'))});
  document.getElementById('jobs-panel').classList.toggle('show',t==='jobs');
  document.getElementById('timeline-panel').classList.toggle('show',t==='timeline');
}
function loadTimeline(page){
  tlPage=page||1;
  var ef=document.getElementById('tlEventFilter').value;
  var url='/api/timeline?page='+tlPage+'&page_size=30';
  if(ef)url+='&event_type='+encodeURIComponent(ef);
  fetch(url).then(function(r){return r.json()})
  .then(function(p){allTimeline=p.items||p;tlPages=p.pages||1;tlTotal=p.total||allTimeline.length;renderTimeline();renderTlPgn();});
}
function renderTlPgn(){
  var el=document.getElementById('tlPgn');
  el.innerHTML='<button class="pgn-btn" '+(tlPage<=1?'disabled':'')+' onclick="loadTimeline('+(tlPage-1)+')">上一页</button>'+
    '<span class="pgn-info">第 '+tlPage+' / '+tlPages+' 页 共 '+tlTotal+' 条</span>'+
    '<button class="pgn-btn" '+(tlPage>=tlPages?'disabled':'')+' onclick="loadTimeline('+(tlPage+1)+')">下一页</button>';
}
function renderTimeline(){
  var f=document.getElementById('tlFilter').value.toLowerCase();
  var items=allTimeline.filter(function(t){
    var title=(t.job_title||'').toLowerCase();
    var comp=(t.job_company||'').toLowerCase();
    return title.includes(f)||comp.includes(f);
  });
  var container=document.getElementById('tlContainer');
  if(!items.length){
    container.innerHTML='<div class="tl-empty"><div class="tl-empty-icon">📋</div><div>暂无时间线数据</div><div style="font-size:.75rem;margin-top:4px">记录职位投递后将在此展示生命周期事件</div></div>';
    document.getElementById('tlStats').textContent='';
    return;
  }
  document.getElementById('tlStats').textContent='共 '+tlTotal+' 条事件';
  container.innerHTML=items.map(function(t){
    var sc=stageClass(t.to_status);
    var bc=badgeClass(t.to_status);
    var showJob=t.job_title||t.job_id||'';
    var showComp=t.job_company||'';
    var label=t.to_status||t.event_type||'事件';
    return'<div class="tl-item">'+
      '<div class="tl-dot '+sc+'"></div>'+
      '<div class="tl-card">'+
        '<div class="tl-header">'+
          '<span class="tl-badge '+bc+'">'+escHtml(label)+'</span>'+
          (t.from_status?'<span class="tl-arrow">'+escHtml(t.from_status)+' → '+escHtml(t.to_status)+'</span>':'')+
        '</div>'+
        (showJob||showComp?'<div style="display:flex;gap:8px;align-items:baseline"><span class="tl-job">'+escHtml(showJob)+'</span><span class="tl-company">'+escHtml(showComp)+'</span></div>':'')+
        '<div class="tl-meta">'+fmtDate(t.created_at)+'</div>'+
      '</div>'+
    '</div>';
  }).join('');
}

// --- boot ---
loadJobs(1);
loadTimeline(1);
</script></body></html>"""

DOCS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>求职Agent API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>html{box-sizing:border-box;overflow:-moz-scrollbars-vertical;overflow-y:scroll}*,*:before,*:after{box-sizing:inherit}
  body{margin:0;background:#fafafa}.topbar{display:none}</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js" crossorigin></script>
<script>
SwaggerUIBundle({url:"/api/openapi.json",dom_id:"#swagger-ui",presets:[SwaggerUIBundle.presets.apis],layout:"StandaloneLayout"});
</script>
</body></html>"""

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "求职Agent Dashboard API",
        "description": "Job tracking and application timeline API for the job-seeking AI agent.",
        "version": "1.0.0",
    },
    "servers": [{"url": "http://localhost:8765", "description": "Local dashboard server"}],
    "paths": {
        "/api/results": {
            "get": {
                "summary": "List jobs",
                "description": "Return job listings. Without pagination params, returns flat array (legacy). With page/page_size, returns paginated envelope.",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                    {"name": "page_size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500}},
                ],
                "responses": {
                    "200": {"description": "Job list (flat array or paginated envelope)"},
                    "401": {"description": "Unauthorized (missing/invalid token)"},
                },
            }
        },
        "/api/timeline": {
            "get": {
                "summary": "List timeline events",
                "description": "Return application timeline events. Supports filtering by job_id and event_type. Without pagination params, returns flat array. With page/page_size, returns paginated envelope.",
                "parameters": [
                    {"name": "job_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "event_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                    {"name": "page_size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500}},
                ],
                "responses": {
                    "200": {"description": "Timeline event list (flat array or paginated envelope)"},
                    "401": {"description": "Unauthorized (missing/invalid token)"},
                },
            }
        },
        "/api/openapi.json": {
            "get": {
                "summary": "OpenAPI specification",
                "responses": {"200": {"description": "OpenAPI 3.0 JSON spec"}},
            }
        },
    },
}


def _get_int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    """Safely parse an integer query parameter from parse_qs output."""
    try:
        val = int(params.get(key, [str(default)])[0])
    except (ValueError, TypeError):
        val = default
    return val


def _authenticate(request: BaseHTTPRequestHandler) -> tuple[bool, str | None]:
    """Check Bearer token against AGENT_DASHBOARD_TOKEN env var.

    Returns (allowed, error_message). Allowed is True when auth succeeds or
    auth is disabled (env var unset/empty).
    """
    expected = os.environ.get("AGENT_DASHBOARD_TOKEN", "").strip()
    if not expected:
        return True, None  # dev mode — no auth required

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "Missing or invalid Authorization header"
    token = auth_header[7:]
    if token != expected:
        return False, "Invalid token"
    return True, None


def _send_json(
    handler: BaseHTTPRequestHandler,
    data: Any,
    status: int = 200,
) -> None:
    """Serialize data as JSON and write the HTTP response."""
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_html(handler: BaseHTTPRequestHandler, html: str, status: int = 200) -> None:
    """Write an HTML response."""
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    message: str,
    details: str | None = None,
) -> None:
    """Send a JSON error response."""
    payload: dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    _send_json(handler, payload, status=status)


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
            elif path == "/api/timeline":
                self._require_auth()
                self._api_timeline(params)
            elif path == "/api/openapi.json":
                self._serve_openapi()
            elif path == "/docs":
                _send_html(self, DOCS_HTML)
            elif path == "/":
                _send_html(self, HTML)
            else:
                _send_error(self, 404, "Not Found", f"No route for {path}")
        except _AuthRequired:
            pass  # error response already sent by _require_auth
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
            total_row = conn.execute("SELECT COUNT(*) AS cnt FROM jobs").fetchone()
            total = total_row["cnt"] if total_row else 0
            pages = max(1, (total + page_size - 1) // page_size)
            offset = (page - 1) * page_size
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            conn.close()
            _send_json(
                self,
                {
                    "items": [dict(r) for r in rows],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "pages": pages,
                },
            )
        else:
            # Legacy flat-list mode (backward compatible)
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY last_seen DESC LIMIT 200"
            ).fetchall()
            conn.close()
            _send_json(self, [dict(r) for r in rows])

    def _api_timeline(self, params: dict[str, list[str]]) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        base_sql = (
            "SELECT t.id, t.application_id, t.from_status, t.to_status, t.created_at,"
            " a.job_id, a.status AS current_status,"
            " j.title AS job_title, j.company AS job_company"
            " FROM timelines t"
            " LEFT JOIN applications a ON t.application_id = a.id"
            " LEFT JOIN jobs j ON a.job_id = j.id"
        )
        where_clauses: list[str] = []
        bind_values: list[Any] = []

        if "job_id" in params and params["job_id"][0]:
            where_clauses.append("a.job_id = ?")
            bind_values.append(params["job_id"][0])

        if "event_type" in params and params["event_type"][0]:
            where_clauses.append("t.to_status = ?")
            bind_values.append(params["event_type"][0])

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        page = _get_int_param(params, "page", 0)
        page_size = _get_int_param(params, "page_size", 30)

        if page > 0:
            # Paginated mode
            # where_sql is built only from hardcoded clause strings
            # ("t.to_status = ?" etc.); all user input goes through bind_values
            # parameterized binding, never string-interpolated into SQL.
            count_sql = (
                "SELECT COUNT(*) AS cnt FROM timelines t"
                " LEFT JOIN applications a ON t.application_id = a.id"
                " LEFT JOIN jobs j ON a.job_id = j.id"
                + where_sql  # nosec B608 -- hardcoded clauses, values parameterized
            )
            total_row = conn.execute(count_sql, bind_values).fetchone()
            total = total_row["cnt"] if total_row else 0
            pages = max(1, (total + page_size - 1) // page_size)
            offset = (page - 1) * page_size
            rows = conn.execute(
                base_sql + where_sql + " ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
                bind_values + [page_size, offset],
            ).fetchall()
            conn.close()
            _send_json(
                self,
                {
                    "items": [dict(r) for r in rows],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "pages": pages,
                },
            )
        else:
            # Legacy flat-list mode (backward compatible)
            limit_val = _get_int_param(params, "limit", 100)
            limit_val = max(1, min(limit_val, 500))
            rows = conn.execute(
                base_sql + where_sql + " ORDER BY t.created_at DESC LIMIT ?",
                bind_values + [limit_val],
            ).fetchall()
            conn.close()
            _send_json(self, [dict(r) for r in rows])

    # ----------------------------------------------------------- OpenAPI ---
    def _serve_openapi(self) -> None:
        _send_json(self, OPENAPI_SPEC)

    # Silence BaseHTTPRequestHandler's default stderr logging
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Override to use logger instead of stderr."""
        logger.info("%s - %s", self.client_address[0], format % args)


def start_server(port: int = 8765, db_path: str = "data/agent.db") -> None:
    """Start the dashboard HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    Handler.db_path = db_path
    token = os.environ.get("AGENT_DASHBOARD_TOKEN", "")
    auth_status = "enabled" if token else "disabled (dev mode)"
    logger.info(
        "Dashboard starting on http://localhost:%d (auth: %s)", port, auth_status
    )
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
