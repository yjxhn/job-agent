"""Embedded frontend assets for the local dashboard.

Kept separate from serve.py so the HTTP/route layer stays reviewable.
"""

# ruff: noqa: E501  -- inline CSS/JS/HTML templates, long lines by design

from pathlib import Path
from typing import Any

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"


def _inline_vendor_js(name: str) -> str:
    """Read a vendored JS file for inline embedding.

    Empty string on any failure so the dashboard still loads without the
    vendor files (prevents a hard import-time crash for offline/dev copies).
    """
    try:
        return (_VENDOR_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return ""


HTML = r"""<!DOCTYPE html><html lang="zh-CN">
<head><meta charset="utf-8"><title>JobAgent</title><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E🎯%3C/text%3E%3C/svg%3E">
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script>
(function(){
  var meta=document.querySelector('meta[name="dashboard-token"]');
  var token=meta?meta.getAttribute('content'):'';
  if(token){
    var origFetch=window.fetch;
    window.fetch=function(input, init){
      init=init||{};
      var headers=new Headers(init.headers||{});
      if(!headers.has('Authorization')) headers.set('Authorization','Bearer '+token);
      init.headers=headers;
      return origFetch.call(this, input, init);
    };
  }
})();
</script>
<style>
html{box-sizing:border-box;overflow-y:scroll;scrollbar-gutter:stable}*,*:before,*:after{box-sizing:inherit}html::-webkit-scrollbar{width:14px;height:14px}html::-webkit-scrollbar-track{background:transparent}html::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:7px;border:3px solid #f7f8fa}html::-webkit-scrollbar-thumb:hover{background:#9ca3af}
:root{--bg:#f7f8fa;--card:#fff;--text:#1a1f2e;--muted:#6b7280;--border:#e5e7eb;--accent:#2563eb;--accent-h:#1d4ed8;--shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);--radius:8px;--th-bg:#f8fafc;--th-text:#374151;--hover:#f9fafb;--even:#fcfcfd;--bar-bg:#fff;--thick-border:#eee;--warn-bg:-webkit-linear-gradient(top,#fef3c7,#fef3c7);--striped:#fafafa}
body{font-family:'Inter','Segoe UI','Microsoft YaHei',system-ui,sans-serif;max-width:1400px;margin:0 auto;padding:24px 28px;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
h1{font-family:inherit;font-size:1.5rem;font-weight:700;margin:0 0 4px;letter-spacing:-.01em}
.subtitle{color:var(--muted);font-size:.85rem;margin:0 0 24px}
/* Tabs */
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 20px;border-bottom:1px solid var(--border)}
.tab{padding:10px 18px;cursor:pointer;font-size:.85rem;font-weight:500;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-1px;transition:color .15s,border-color .15s;user-select:none}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
/* Bar */
.bar{display:flex;gap:8px;margin:14px 0;align-items:center;flex-wrap:wrap;padding:12px 16px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
.bar > *{margin:0}
.bar select,.bar input[type=text],.bar > input{padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:.83rem;background:#fff;outline:none;transition:border-color .15s,box-shadow .15s;text-align:center;text-align-last:center}
.bar select{text-align:center;text-align-last:center;-webkit-text-align-last:center}
.bar select option{text-align:center}
.bar input::placeholder{text-align:center;color:var(--muted)}
.bar input:focus,.bar select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.1)}
.bar button{transition:transform .08s,box-shadow .15s,background .15s}
.bar button:hover{transform:translateY(-1px);box-shadow:0 2px 6px rgba(0,0,0,.1)}
.bar button:active{transform:translateY(0)}
.bar label{padding:6px 10px;border-radius:6px;background:#fff;border:1px solid var(--border);transition:border-color .15s}
.bar label:hover{border-color:var(--accent)}
.bar-divider{width:1px;height:24px;background:var(--border);margin:0 4px}
.bar-group{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:6px;background:rgba(37,99,235,.05)}
.bar-group-label{font-size:.72rem;color:var(--muted);font-weight:600;letter-spacing:.02em}
input,select,textarea{padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:.85rem;background:#fff;outline:none;transition:border-color .15s;box-sizing:border-box}
input:focus,select:focus{border-color:var(--accent)}
/* Table */
.panel{display:none}.panel.show{display:block}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);border:1px solid var(--border)}.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin;scrollbar-color:#cbd5e1 #eef1f5}.table-wrap::-webkit-scrollbar{height:12px;width:12px}.table-wrap::-webkit-scrollbar-track{background:#eef1f5;border-radius:6px}.table-wrap::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:6px;border:2px solid #eef1f5}.table-wrap table{min-width:840px}#filesTable th:nth-child(2),#filesTable td:nth-child(2){min-width:220px}@media (max-width:479px){.tabs{flex-wrap:wrap}.tab{padding:8px 12px;font-size:.78rem}.bar{flex-direction:column;align-items:stretch}.bar-group{flex-wrap:wrap}.bar-divider{display:none}#filesTable th:nth-child(4),#filesTable td:nth-child(4),#filesTable th:nth-child(5),#filesTable td:nth-child(5),#filesTable th:nth-child(6),#filesTable td:nth-child(6){display:none}}@media (max-width:900px){.tabs{flex-wrap:nowrap;overflow-x:auto;justify-content:flex-start}}@media (max-width:700px){.salary-form-grid{grid-template-columns:1fr !important}}
th{background:#f8fafc;color:#374151;padding:12px 14px;text-align:center;cursor:pointer;user-select:none;font-size:.78rem;font-weight:700;letter-spacing:.03em;text-transform:uppercase;border-bottom:1px solid var(--border);position:sticky;top:0;z-index:1}
th.select-col{white-space:nowrap}
.row-actions{display:flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap}
.row-actions .pgn-btn{flex:0 0 auto;width:72px;min-width:72px;height:30px;display:inline-flex;align-items:center;justify-content:center;text-align:center;padding:4px 8px!important;box-sizing:border-box}
.row-actions button:disabled{background:var(--card)!important;color:var(--muted)!important;border:1px solid var(--border)!important;opacity:.55}
#match-panel th:nth-child(1){min-width:60px}#match-panel th:nth-child(2){min-width:60px}
#match-panel th:nth-child(3){min-width:120px}#match-panel th:nth-child(4){min-width:100px}
#match-panel th:nth-child(7){min-width:140px}
#match-panel th:nth-child(9),#match-panel td:nth-child(9){width:110px;white-space:nowrap}
#match-panel td:nth-child(9) button{display:inline-block;margin:1px;vertical-align:middle}
#matchTable.hide-dir th:nth-child(5),#matchTable.hide-dir td:nth-child(5){display:none}
#match-panel .match-cell{cursor:pointer;color:inherit;text-decoration:underline dotted;text-underline-offset:2px}
#match-panel .match-cell:hover{background:#f0f7ff;color:var(--accent)}
/* 人工初筛: fixed layout + explicit column widths (2026-08-11 fix — auto layout let the
   long-company column inflate the title column to 38% width, making content look right-shifted) */
#jobs-panel table{table-layout:fixed}
#jobs-panel th:nth-child(1),#jobs-panel td:nth-child(1){width:28%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#jobs-panel th:nth-child(2),#jobs-panel td:nth-child(2){width:22%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#jobs-panel th:nth-child(3),#jobs-panel td:nth-child(3){width:14%}
#jobs-panel th:nth-child(4),#jobs-panel td:nth-child(4){width:8%}
#jobs-panel th:nth-child(5),#jobs-panel td:nth-child(5){width:12%}
#jobs-panel th:nth-child(6),#jobs-panel td:nth-child(6){width:5%}
#jobs-panel th:nth-child(7),#jobs-panel td:nth-child(7){width:11%}
th:hover{background:#f3f4f6}td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:.85rem;text-align:center}th{text-align:center}
tr:hover{background:#f9fafb}tr:nth-child(even){background:#fcfcfd}tr:nth-child(even):hover{background:#f9fafb}
/* Files table */
#filesTable{table-layout:fixed}
#filesTable th,#filesTable td{padding:10px 12px;font-size:.82rem;vertical-align:middle;border-bottom:1px solid var(--border)}
#filesTable th:nth-child(1){width:6%;text-align:center}
#filesTable th:nth-child(2){width:33%;text-align:left}
#filesTable th:nth-child(3){width:9%;text-align:center}
#filesTable th:nth-child(4){width:17%;text-align:left}
#filesTable th:nth-child(5){width:7%;text-align:right}
#filesTable th:nth-child(6){width:10%;text-align:center}
#filesTable th:nth-child(7){width:18%;text-align:right}
#filesTable td:nth-child(1){text-align:center}
#filesTable td:nth-child(2){text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#filesTable td:nth-child(3){text-align:center}
#filesTable td:nth-child(4){text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted)}
#filesTable td:nth-child(5){text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
#filesTable td:nth-child(6){text-align:center;white-space:nowrap;color:var(--muted)}
#filesTable td:nth-child(7){text-align:center}
.file-actions{display:inline-flex;gap:6px;align-items:center;justify-content:center}
.file-actions a{font-size:.76rem;padding:4px 10px;border-radius:4px;background:var(--card);border:1px solid var(--border);transition:all .15s;white-space:nowrap;min-width:56px;text-align:center;box-sizing:border-box}
.file-actions a:hover{background:#eff6ff;border-color:var(--accent);text-decoration:none}
.file-actions a.delete-action{color:#c15a3a;background:#fff;border-color:#fecaca}
.file-actions a.delete-action:hover{background:#fef2f2;border-color:#ef4442}
.empty-state{padding:44px 16px;text-align:center;color:var(--muted);font-size:.85rem;background:var(--card);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow)}
.empty-state .empty-ico{display:block;font-size:1.8rem;margin-bottom:8px}
.empty-state .empty-title{font-weight:700;color:var(--text);margin-bottom:6px;font-size:.9rem}
.empty-state .empty-hint{font-size:.78rem;line-height:1.6;color:var(--muted)}
.empty-state .pgn-btn{margin-top:12px}
/* 2026-08-18 UI polish: subtler table header, compact long-text cells, fuller empty states */
.panel{min-height:calc(100vh - 300px)}
.empty-state{min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center}
#match-panel td:nth-child(6),#match-panel td:nth-child(7){max-width:240px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#match-panel th:nth-child(6),#match-panel th:nth-child(7){min-width:120px}
td input[type=checkbox],th input[type=checkbox]{vertical-align:middle;width:16px;height:16px;cursor:pointer;accent-color:var(--accent)}
.tab{white-space:nowrap}
.bar button{white-space:nowrap}
#jobs-panel th:nth-child(1),#jobs-panel td:nth-child(1),#jobs-panel th:nth-child(2),#jobs-panel td:nth-child(2),#jobs-panel th:nth-child(3),#jobs-panel td:nth-child(3){text-align:left}
#match-panel th:nth-child(3),#match-panel td:nth-child(3),#match-panel th:nth-child(4),#match-panel td:nth-child(4),#match-panel th:nth-child(6),#match-panel td:nth-child(6),#match-panel th:nth-child(7),#match-panel td:nth-child(7){text-align:left}
#appsTable{table-layout:fixed}
#appsTable th,#appsTable td{padding:8px 10px;font-size:.82rem}
#appsTable th:nth-child(1){width:72px;white-space:nowrap}
#appsTable th:nth-child(2){width:16%;text-align:left}
#appsTable th:nth-child(3){width:16%;text-align:left}
#appsTable th:nth-child(4){width:12%}
#appsTable th:nth-child(5){width:14%}
#appsTable th:nth-child(6){width:12%}
#appsTable th:nth-child(7){width:90px;white-space:nowrap}
#appsTable td:nth-child(2),#appsTable td:nth-child(3),#appsTable td:nth-child(5){text-align:left;overflow:hidden;text-overflow:ellipsis}
/* 投递状态彩色 Tag 化下拉（2026-08-18） */
.app-status{padding:4px 10px;border-radius:12px;border:1px solid transparent;font-weight:600;font-size:.76rem;cursor:pointer;outline:none}
.app-status.st-pending{background:#f3f4f6;color:#4b5563;border-color:#e5e7eb}
.app-status.st-applied{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe}
.app-status.st-hr{background:#eef2ff;color:#4f46e5;border-color:#c7d2fe}
.app-status.st-interview{background:#faf5ff;color:#7e22ce;border-color:#e9d5ff}
.app-status.st-offer{background:#ecfdf5;color:#047857;border-color:#a7f3d0}
.app-status.st-onboard{background:#f0fdfa;color:#0f766e;border-color:#99f6e4}
.app-status.st-ended{background:#fef2f2;color:#b91c1c;border-color:#fecaca}
#offer-panel th:nth-child(3),#offer-panel td:nth-child(3){text-align:left}
/* 已生成文件表格自适应（2026-08-16 用户反馈：不要写死列宽）：
   宽屏按百分比分配；≤900px 隐藏“大小/生成时间”且操作按钮换行；≤700px 再隐藏“所属岗位” */
@media (max-width:900px){
.table-wrap table{min-width:0}
#filesTable th:nth-child(5),#filesTable td:nth-child(5),#filesTable th:nth-child(6),#filesTable td:nth-child(6){display:none}
#filesTable th:nth-child(1){width:6%}
#filesTable th:nth-child(2){width:50%}
#filesTable th:nth-child(3){width:10%}
#filesTable th:nth-child(4){width:17%}
#filesTable th:nth-child(7){width:17%}
.file-actions{flex-wrap:wrap;gap:4px}
}
@media (max-width:700px){
#filesTable th:nth-child(4),#filesTable td:nth-child(4){display:none}
#filesTable th:nth-child(1){width:8%}
#filesTable th:nth-child(2){width:56%}
#filesTable th:nth-child(3){width:16%}
#filesTable th:nth-child(7){width:20%}
.file-actions a{min-width:48px;padding:4px 8px}
}
#filesTable tbody tr:nth-child(even){background:#fafafa}
#filesTable tbody tr:hover{background:#f0f7ff}
.score{font-weight:600;border-radius:6px;padding:3px 10px;color:#fff;font-size:.78rem}
.s-high{background:#10b981}.s-mid{background:#f59e0b}.s-low{background:#ef4444}
a{color:var(--accent);text-decoration:none}a:hover{color:var(--accent-h);text-decoration:underline}
.refresh{display:inline-flex;align-items:center;gap:4px;color:var(--accent);cursor:pointer;font-size:.8rem;font-weight:500;padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--card);transition:border-color .15s,background .15s;text-decoration:none}.refresh:hover{border-color:var(--accent);background:#eff6ff;text-decoration:none}.refresh:not(.no-spin)::before{content:'↻';display:inline-block;font-size:.85rem;transition:transform .3s}.refresh.spinning:not(.no-spin)::before{animation:spin .8s linear}@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.sort-ind{font-size:.65rem;margin-left:2px;opacity:.4}.sort-ind.active{opacity:1}
.new-badge{background:var(--accent);color:#fff;font-size:.65rem;font-weight:700;padding:2px 7px;border-radius:10px;margin-left:6px;vertical-align:middle}
.sal{color:#0f172a;font-weight:600;white-space:nowrap}
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
.tl-dot.st-search{--dot-color:#5a7a6a} .tl-dot.st-match{--dot-color:#6b5d4a}
.tl-dot.st-apply{--dot-color:#2c4a3e} .tl-dot.st-interview{--dot-color:#3a6a6a} .tl-dot.st-offer{--dot-color:#3d7a5a}
.tl-dot.st-onboard{--dot-color:#8a4a5a} .tl-dot.st-terminated{--dot-color:#8a4a4a}
/* card */
.tl-card{background:var(--card);border-radius:4px;padding:14px 18px;box-shadow:0 1px 2px rgba(44,74,62,.06);border:1px solid var(--border);transition:box-shadow .15s}
.tl-card:hover{box-shadow:0 2px 8px rgba(44,74,62,.1);border-color:var(--accent)}
.tl-header{display:flex;align-items:center;gap:10px;margin:0 0 6px;flex-wrap:wrap}
.tl-badge{padding:3px 10px;border-radius:3px;font-size:.72rem;font-weight:700;letter-spacing:.02em;color:#fff}
.bg-search{background:#5a7a6a}.bg-match{background:#6b5d4a}.bg-apply{background:#2c4a3e}
.bg-interview{background:#3a6a6a}.bg-offer{background:#3d7a5a}
.bg-onboard{background:#8a4a5a}.bg-terminated{background:#8a4a4a}
.tl-arrow{color:var(--muted);font-size:.75rem;font-weight:600}
.tl-job{font-weight:700;font-size:.9rem;color:var(--text)}
.tl-company{font-size:.8rem;color:var(--muted)}
.tl-meta{font-size:.75rem;color:var(--muted);margin:4px 0 0}
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
button:disabled{opacity:1;cursor:not-allowed;transform:none;box-shadow:none;background:#e5e7eb!important;color:#9ca3af!important;border-color:#d1d5db!important}textarea:disabled,input:disabled,select:disabled{background:#f3f4f6;color:#9ca3af;cursor:not-allowed}
.pgn-info{font-size:.8rem;color:var(--muted)}
/* Clock */
.clock{position:relative;border:1.5px solid var(--border);border-radius:10px;padding:6px 14px;margin-left:auto;font-family:'SF Mono','Cascadia Code','Consolas',monospace;font-size:.78rem;color:var(--text);animation:clockPulse 2.5s ease-in-out infinite;min-width:82px;text-align:center}
.clock-badge{position:absolute;top:-9px;left:10px;background:var(--bg);padding:0 6px;font-size:.62rem;font-weight:700;letter-spacing:.08em;color:#10b981}
@keyframes clockPulse{0%,100%{box-shadow:0 0 0 0 rgba(16,185,129,.15)}50%{box-shadow:0 0 0 4px rgba(16,185,129,.08)}}
.post-stages-section{margin-top:22px}
.post-stages-title{font-size:.85rem;font-weight:700;color:var(--muted);margin:0 0 12px 2px;letter-spacing:.02em}
.post-stages-grid{display:grid;gap:16px;grid-template-columns:repeat(6,minmax(0,1fr))}
@media (max-width:1100px){.post-stages-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:640px){.post-stages-grid{grid-template-columns:repeat(1,minmax(0,1fr))}}
.stage-grid{display:grid;gap:12px;grid-template-columns:repeat(6,minmax(0,1fr))}
@media (max-width:1100px){.stage-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:640px){.stage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.stage-card{display:block;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:18px;min-height:150px;box-shadow:0 1px 3px rgba(44,74,62,.08);cursor:pointer;transition:box-shadow .2s,transform .2s}
.stage-card:hover{box-shadow:0 6px 20px rgba(44,74,62,.25);transform:translateY(-4px);border-color:var(--accent)}
.post-stage-card{display:block;background:var(--card);border:1px solid var(--border);border-left:5px solid #ccc;border-radius:6px;padding:18px;min-height:150px;box-shadow:0 1px 3px rgba(44,74,62,.08);cursor:pointer;transition:box-shadow .2s,transform .2s}
.post-stage-card.done{border-left:5px solid #3d7a5a}
.post-stage-card:hover{box-shadow:0 6px 20px rgba(44,74,62,.25);border-color:var(--accent);transform:translateY(-4px)}
.post-stage-num{font-size:1.5rem;color:var(--accent);margin:0 0 6px;font-weight:700}
.post-stage-body{margin:0}
.post-stage-name{font-weight:700;font-size:1rem;color:var(--text);margin:0 0 4px}
.post-stage-desc{font-size:.75rem;color:#8b7355;line-height:1.5}
.post-stage-btn{flex-shrink:0;background:var(--accent);color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600}
.post-stage-btn:hover{background:var(--accent-h)}
.post-stage-btn.secondary{background:var(--card);color:var(--accent);border:1.5px solid var(--border)}
.post-stage-btn.secondary:hover{background:#eff6ff;border-color:var(--accent)}
.md-body{font-size:.85rem;line-height:1.7;word-break:break-word;overflow-x:auto;-webkit-overflow-scrolling:touch}.md-body table{border-collapse:collapse;width:100%;margin:8px 0;min-width:100%}.md-body th,.md-body td{border:1px solid var(--border);padding:6px 8px;text-align:left;vertical-align:top}.md-body th{background:var(--bg);font-weight:600}.md-body h3{margin:12px 0 4px;font-size:.95rem;color:var(--text)}.md-body h4{margin:10px 0 4px;font-size:.88rem;color:var(--text)}.md-body ul{margin:4px 0;padding-left:20px}.md-body li{margin:3px 0}.md-body p{margin:6px 0}.md-body strong{color:var(--text)}.md-body hr{border:none;border-top:1px dashed var(--border);margin:10px 0}@media (prefers-color-scheme:dark){
:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--border:#334155;--accent:#60a5fa;--accent-h:#93c5fd;--shadow:0 1px 3px rgba(0,0,0,.4),0 1px 2px rgba(0,0,0,.3);--th-bg:#263449;--th-text:#cbd5e1;--hover:#24334a;--even:#1a2537;--bar-bg:#1e293b}
html::-webkit-scrollbar-thumb{background:#475569;border:3px solid #0f172a}
body{background:var(--bg);color:var(--text)}
input,select,textarea{background:#0f172a;color:var(--text);border-color:var(--border)}
.bar{background:var(--card);border-color:var(--border)}
.bar select,.bar input[type=text],.bar > input{background:#0f172a;color:var(--text);border-color:var(--border);text-align:center;text-align-last:center}
.bar label{background:#0f172a;border-color:var(--border)}
table{background:var(--card);border-color:var(--border)}
th{background:var(--th-bg);color:var(--th-text);border-bottom:1px solid var(--border)}
td{border-bottom:1px solid var(--border)}
tr:hover{background:var(--hover)}
tr:nth-child(even){background:var(--even)}
tr:nth-child(even):hover{background:var(--hover)}
.stage-card,.post-stage-card,.tl-card,.empty-state{background:var(--card);border-color:var(--border);box-shadow:var(--shadow)}
.stage-card:hover,.post-stage-card:hover{border-color:var(--accent)}
.post-stage-card{border-left:5px solid #475569}
.pgn-btn{background:var(--card);color:var(--text);border-color:var(--border)}
.pgn-btn:hover{border-color:var(--accent);color:var(--accent)}
button:disabled{background:#334155!important;color:#64748b!important;border-color:#475569!important}
textarea:disabled,input:disabled,select:disabled{background:#1a2537!important;color:#64748b!important}
.refresh{background:var(--card);border-color:var(--border);color:var(--accent)}
.clock{border-color:var(--border);color:var(--muted)}
.md-body strong{color:var(--text)}
.empty-state{background:var(--card)}
#postCountMock,#postCountOffer,#postCountSalary{color:#94a3b8}
.row-actions button:disabled{background:var(--card)!important;color:var(--muted)!important;border-color:var(--border)!important}
.app-status.st-pending{background:#334155;color:#cbd5e1;border-color:#475569}
#filesTable tbody tr:nth-child(even){background:var(--even)}
#filesTable tbody tr:hover{background:#24334a}
.sal{color:var(--text)}
}
</style></head>
<body>
<h1>JobAgent</h1>
<p class="subtitle">求职全流程自动化 · 搜索 → 筛选 → 匹配 → 生成材料 → 审核 → 投递 → 面试 → Offer → 薪资 | <a href="/docs" style="font-size:.8rem">API Docs</a></p>
<div class="tabs">
<div class="tab active" data-tab="resume" onclick="switchTab('resume')">📄 文件上传</div>
<div class="tab" data-tab="jobs" onclick="switchTab('jobs')">📋 人工初筛</div>
<div class="tab" data-tab="match" onclick="switchTab('match')">🎯 Agent智能匹配结果</div>
<div class="tab" data-tab="materials" onclick="switchTab('materials')">📝 材料审核台</div>
<div class="tab" data-tab="timeline" onclick="switchTab('timeline')">📅 投递追踪</div>
<div class="tab" data-tab="mock" onclick="switchTab('mock')">🎤 模拟面试</div>
<div class="tab" data-tab="offer" onclick="switchTab('offer')">💼 Offer 评估</div>
<div class="tab" data-tab="salary" onclick="switchTab('salary')">💰 薪资谈判</div>
<div class="tab" data-tab="files" onclick="switchTab('files')">📁 已生成文件</div>
<div class="tab" data-tab="pipeline" onclick="switchTab('pipeline')">⚙️ 流水线</div>
</div>

<!-- Jobs Panel -->
<div id="jobs-panel" class="panel">
<div id="flagLegend" style="display:flex;gap:16px;padding:6px 12px;background:var(--card);border:1px solid var(--border);border-radius:6px;margin:0 0 8px;font-size:.82rem;color:var(--text);align-items:center">
<span style="font-weight:600">标记说明（点击单元格循环切换）：</span>
<span style="color:var(--muted)">➖ 未标记</span>
<span style="color:#999;font-size:.75rem"> → </span>
<span style="color:#c15a3a;font-weight:700">❌ 不合适</span>
<span style="color:#999;font-size:.75rem"> → </span>
<span style="color:#3d7a5a;font-weight:700">🌟 想投递</span>
<span style="color:#999;font-size:.75rem"> → </span>
<span style="color:var(--muted)">➖ 未标记</span>
</div>
<div class="bar">
<div class="bar-group">
<span class="bar-group-label">筛选</span>
<input id="companyFilter" placeholder="按公司" oninput="debounceLoad()" style="width:88px">
<input id="titleFilter" placeholder="按职位(全词匹配)" title="全词匹配：需与职位名完全一致" oninput="debounceLoad()" style="width:152px">
<input id="locFilter" placeholder="按地点" oninput="debounceLoad()" style="width:88px">
<select id="platFilter" onchange="jobsPage=1;loadJobs(1)" style="width:96px"><option value="">全部平台</option></select>
<select id="flagFilter" onchange="jobsPage=1;loadJobs(1)" style="width:96px"><option value="">全部标记</option><option value="interested">🌟 想投递</option><option value="rejected">❌ 不合适</option><option value="unmarked">➖ 未标记</option></select>
<label style="font-size:.78rem;color:var(--muted);display:inline-flex;align-items:center;gap:3px">每页<select id="pageSize" onchange="jobsPage=1;loadJobs(1)" style="width:72px"><option value="0" selected>全部</option><option value="10">10条</option><option value="30">30条</option><option value="50">50条</option></select></label>
<button onclick="clearFilters()" style="background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">清空筛选</button>
</div>
<span class="bar-divider"></span>
<div class="bar-group">
<span class="bar-group-label">批量</span>
<label style="display:inline-flex;align-items:center;gap:4px;color:var(--muted);font-size:.8rem;cursor:pointer"><input type="checkbox" id="selectAll" onclick="toggleSelectAll(this)" title="全选/反选">全选</label>
<span style="color:var(--muted);font-size:.8rem">已选 <b id="selCount">0</b></span>
<select id="batchFlagSel" style="width:152px">
  <option value="">请选择批量操作</option>
  <option value="interested">批量标记 🌟</option>
  <option value="rejected">批量标记 ❌</option>
  <option value="clear">批量清除标记</option>
</select>
<button id="batchFlagBtn" onclick="batchFlag()" disabled style="background:var(--accent);color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">应用</button>
</div>
<span class="bar-divider"></span>
<div class="bar-group">
<span class="bar-group-label">操作</span>
<button id="fetchJDBtn" onclick="fetchJDForFlagged()" disabled style="background:var(--card);color:var(--accent);border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">📄 抓取JD</button>
<button id="viewJDBtn" onclick="viewJDForFlagged()" disabled style="background:var(--card);color:var(--accent);border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">📄 查看JD</button>
<button id="runMatchBtn" onclick="runMatch()" disabled style="background:var(--accent);color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🧠 精排</button>
</div>
<span class="bar-divider"></span>
<div class="bar-group">
<span class="bar-group-label">危险操作</span>
<button onclick="clearData()" title="清空所有职位与搜索历史（不可恢复）" style="background:#c15a3a;color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🗑 清空数据</button>
</div>
<span class="refresh" onclick="refreshJobsTab()">刷新</span>
<label style="font-size:.78rem;color:var(--muted);display:inline-flex;align-items:center;gap:3px;cursor:pointer" title="每 30 秒自动重新加载岗位列表"><input type="checkbox" id="jobsAuto" onchange="toggleJobsAuto(this)"> 自动刷新</label>
<span class="clock" id="ts" style="margin-left:auto" title="当前时间（非数据更新时间）"><span class="clock-badge">当前时间</span><span id="clockTime"></span></span>
</div>
<div class="table-wrap"><table><thead><tr>
<th onclick="sort('title')">岗位<span class="sort-ind"></span></th>
<th onclick="sort('company')">公司<span class="sort-ind"></span></th><th onclick="sort('location')">地点<span class="sort-ind"></span></th>
<th onclick="sort('salary_max')">薪资<span class="sort-ind"></span></th>
<th>链接</th><th class="select-col" style="text-align:center">选择</th><th>标记</th></tr></thead>
<tbody id="tb"></tbody></table></div>
<div id="jobsPgn" class="pgn"></div>
</div>

<!-- Match Panel -->
<div id="match-panel" class="panel">
  <div class="bar">
    <input id="matchFilter" placeholder="搜索公司/岗位..." oninput="loadMatch(1)" style="width:160px">
    <select id="matchMinScore" onchange="loadMatch(1)" style="width:100px">
      <option value="0" selected>全部分数</option>
      <option value="80">80+</option>
      <option value="60">60+</option>
      <option value="40">40+</option>
    </select>
    <button onclick="clearMatchFilter()" style="background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">清空筛选</button>
    <span class="refresh" onclick="loadMatch(1)">刷新</span>
    <button id="generateMatBtn" onclick="generateMaterials()" disabled style="background:var(--accent);color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">✍️ 生成求职材料</button>
    <button id="batchLowBtn" onclick="batchMatchFeedback('too_low')" disabled style="background:var(--card);color:#3d7a5a;border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">📈 批量偏低</button>
    <button id="batchHighBtn" onclick="batchMatchFeedback('too_high')" disabled style="background:var(--card);color:#c15a3a;border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">📉 批量偏高</button>
    <button id="clearFeedbackBtn" onclick="clearMatchFeedback()" style="background:var(--card);color:#c15a3a;border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🧹 清除历史反馈</button>
    <button id="clearMatchBtn" onclick="clearMatch()" disabled style="background:var(--card);color:#c15a3a;border:1.5px solid var(--border);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🗑️ 清空匹配</button>
  </div>
  <div style="display:flex;gap:16px;padding:6px 12px;background:var(--card);border:1px solid var(--border);border-radius:6px;margin:0 0 8px;font-size:.82rem;color:var(--text);align-items:center">
    <span style="font-weight:600">缺口分级：</span>
    <span>🔴 硬阻断：学历、法定证书等硬门槛，不满足基本无缘</span>
    <span style="color:#999">|</span>
    <span>🟡 可弥补：特定设备、行业背景等，入职后可快速上手</span>
    <span style="color:#999">|</span>
    <span>🟢 加分缺失：JD 写"优先"但非必须，不影响录用决策</span>
    <span style="color:#999;font-size:.72rem;margin-left:auto">点击“主要缺口/匹配理由”虚线文字可查看完整内容</span>
  </div>
  <div class="table-wrap"><table id="matchTable"><thead><tr>
    <th class="select-col" style="width:70px"><input type="checkbox" id="matchSelectAll" onclick="matchToggleAll(this)"> 选择</th><th>匹配分</th><th>岗位</th><th>公司</th><th>方向</th><th>主要缺口</th><th>匹配理由</th><th>链接</th><th style="width:60px">校准</th>
  </tr></thead>
  <tbody id="matchTb"></tbody></table></div>
  <div id="matchPgn" class="pgn"></div>
</div>

<!-- Materials Review Panel -->
<div id="materials-panel" class="panel">
  <div class="bar">
    <span class="refresh" onclick="loadMaterials()">刷新</span>
    <select id="matStatusFilter" onchange="loadMaterials()" style="font-size:.82rem;padding:3px">
      <option value="draft">待审核</option>
      <option value="confirmed">已确认</option>
      <option value="all">全部</option>
    </select>
    <label style="font-size:.82rem;display:inline-flex;align-items:center;gap:3px;cursor:pointer;margin-left:8px"><input type="checkbox" id="matSelectAll" onchange="toggleAllMaterials(this)"> 全选</label>
    <button onclick="batchRegenMaterials()" style="background:#c15a3a;color:#fff;border:none;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🔄 批量再生成</button>
    <button onclick="batchConfirmMaterials()" style="background:#3a7c4f;color:#fff;border:none;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">✓ 批量确认保存</button>
    <button onclick="batchDeleteMaterials()" style="background:#ef4444;color:#fff;border:none;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🗑️ 批量删除</button>
    <span style="margin-left:auto;font-size:.82rem;color:var(--muted)">草稿（未确认）· 确认后归档至「已生成文件」</span>
  </div>
  <div id="materialsList" style="display:flex;flex-direction:column;gap:10px"></div>
</div>

<!-- Resume Panel -->
<div id="resume-panel" class="panel show">
  <div class="bar">
    <input type="file" id="unifiedFileInput" accept=".txt,.md,.text" multiple style="display:none" onchange="onUnifiedFilePicked(this)">
    <select id="uploadTypeSel" onchange="switchUploadList()" style="font-size:.82rem;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text);cursor:pointer" title="选择上传类型">
      <option value="resume">📄 简历</option>
      <option value="offer">💼 Offer</option>
    </select>
    <button onclick="document.getElementById('unifiedFileInput').click()" style="background:var(--accent);color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600" title="按左侧所选类型上传：简历(.txt/.md)设为默认，Offer(.txt)进入评估">📤 文件上传</button>
    <button onclick="downloadOfferTemplate()" style="background:var(--card);color:var(--accent);border:1px solid var(--accent);padding:8px 14px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600" title="下载 17 字段 Offer 导入模板">📥 Offer导入模板</button>
    <span class="refresh" onclick="switchUploadList()">刷新</span>
    <button onclick="uploadBatchDelete()" style="background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600;margin-left:8px">🗑️ 批量删除</button>
    <span id="resumeStatus" style="font-size:.78rem;color:var(--muted);margin-left:auto"></span>
  </div>
  <div style="padding:10px 4px;font-size:.8rem;color:var(--muted);line-height:1.7">
    <span id="usageResume"><b style="color:var(--text)">使用说明</b>：上传纯文本简历（<code>.txt</code> / <code>.md</code>），<b>支持多选批量上传</b>。上传后<b style="color:var(--accent)">自动设为默认简历</b>，用于「深度匹配」和简历定制。可上传多份，⭐ 标记当前默认；删除默认简历会自动切换到其他简历。单文件上限 5MB。</span><span id="usageOffer" style="display:none"><b style="color:var(--text)">使用说明</b>：<b style="color:var(--accent)">Offer 评估</b>：点「Offer导入模板」下载 17 字段模板，填写后在「文件上传」处将类型选为「💼 Offer」再上传 .txt，再到「💼 Offer 评估」tab 评估/对比。</span>
  </div>
  <div class="table-wrap"><table><thead><tr>
    <th class="select-col" style="width:72px">选择<br><input type="checkbox" onclick="uploadToggleAll(this)"></th><th>文件名</th><th>大小</th><th>修改时间</th><th>状态</th><th style="width:200px">操作</th>
  </tr></thead>
  <tbody id="resumeTb"></tbody></table></div>
  <div id="resumeEmpty" style="padding:40px 20px;text-align:center;color:var(--muted);font-size:.85rem;display:none">
    📭 暂无简历，点击上方「文件上传」添加
  </div>
  <div id="resumePreview" style="margin-top:16px;border-top:1px dashed var(--border);padding-top:14px;display:none">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <b style="font-size:.9rem" id="resumePreviewTitle">📄 预览</b>
      <span class="refresh no-spin" onclick="document.getElementById('resumePreviewBox').style.display='none';document.getElementById('resumePreview').querySelector('b').textContent=''">关闭</span>
    </div>
    <pre id="resumePreviewBox" style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;max-height:400px;overflow:auto;font-size:.78rem;white-space:pre-wrap;word-break:break-word;line-height:1.6"></pre>
  </div>
</div>

<!-- Files Panel -->
<div id="files-panel" class="panel">
  <div class="bar">
    <span style="font-size:.85rem;color:var(--muted)" id="filesStats"></span>
    <input id="fileSearch" placeholder="搜索文件名..." oninput="loadFiles()" style="width:160px;font-size:.82rem;padding:6px 10px">
    <select id="fileTypeFilter" onchange="loadFiles()" style="font-size:.82rem;padding:3px">
      <option value="">全部类型</option>
      <option value="tailor_resume">简历定制</option>
      <option value="cover_letter">HR消息</option>
      <option value="interview_prep">面试准备</option>
      <option value="mock_interview">模拟面试</option>
      <option value="offer_eval">Offer评估</option>
      <option value="offer_compare">Offer对比</option>
      <option value="salary_advice">薪资谈判</option>
    </select>
    <span class="refresh" onclick="loadFiles()">刷新</span>
    <button id="batchDownloadBtn" onclick="batchDownloadFiles()" disabled style="background:var(--accent);color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600;margin-left:8px">📦 批量下载</button>
    <button id="batchDeleteBtn" onclick="batchDeleteFiles()" disabled style="background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600;margin-left:8px">🗑️ 批量删除</button>
  </div>
  <div class="table-wrap"><table id="filesTable"><thead><tr>
    <th class="select-col" style="width:80px"><span style="display:inline-flex;align-items:center;gap:4px">选择 <input type="checkbox" id="fileSelectAll" onclick="fileToggleAll(this)" title="全选" aria-label="全选"></span></th><th onclick="sortFiles('name')" title="点击排序">文件名 <span id="sortName" style="font-size:.65rem"></span></th><th>类型</th><th>所属岗位</th><th onclick="sortFiles('size')" title="点击排序">大小 <span id="sortSize" style="font-size:.65rem"></span></th><th onclick="sortFiles('modified')" title="点击排序">生成时间 <span id="sortModified" style="font-size:.65rem"></span></th><th>操作</th>
  </tr></thead>
  <tbody id="filesTb"></tbody></table></div>
  <div id="filesMore" style="text-align:center;margin-top:12px;display:none"></div>
</div>

<!-- Timeline Panel -->
<div id="timeline-panel" class="panel">
<div id="applicationsBar" style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
    <b>📍 投递状态</b>
    <select id="appStatusFilter" onchange="loadApplications()" style="padding:3px" title="按状态筛选">
      <option value="">全部状态</option>
      <option value="待投递">待投递</option>
      <option value="已投递">已投递</option>
      <option value="HR已读">HR已读</option>
      <option value="约面">约面</option>
      <option value="一面">一面</option>
      <option value="二面">二面</option>
      <option value="Offer">Offer</option>
      <option value="入职">入职</option>
      <option value="已终止">已终止</option>
    </select>
    <input id="appSearch" placeholder="搜索岗位/公司..." oninput="loadApplications()" style="width:140px;padding:4px 8px">
    <span id="appStats" style="font-size:.8rem;color:var(--muted)"></span>
    <button onclick="showAddAppModal()" style="background:var(--card);color:var(--accent);border:1.5px solid var(--border);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">➕ 手动新增</button>
    <select id="appBatchStatus" style="margin-left:12px;padding:3px">
      <option value="">批量操作…</option>
      <option value="待投递">批量设为 待投递</option>
      <option value="已投递">批量设为 已投递</option>
      <option value="HR已读">批量设为 HR已读</option>
      <option value="约面">批量设为 约面</option>
      <option value="一面">批量设为 一面</option>
      <option value="二面">批量设为 二面</option>
      <option value="Offer">批量设为 Offer</option>
      <option value="入职">批量设为 入职</option>
      <option value="已终止">批量设为 已终止</option>
    </select>
    <button onclick="batchUpdateAppStatus()" style="background:var(--accent);color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">✅ 应用</button>
    <button onclick="deleteApps()" style="background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">🗑️ 批量删除</button>
    <span style="margin-left:auto;font-size:.8rem;color:var(--muted)">提醒周期</span>
    <input id="reminderDays" type="number" min="1" max="30" value="3" style="width:50px">
    <span style="font-size:.8rem">天</span>
    <button onclick="setReminder()" style="background:var(--accent);color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">💾 保存</button>
    <label style="font-size:.78rem;color:var(--muted);display:inline-flex;align-items:center;gap:3px;cursor:pointer" title="每 30 秒自动重新加载投递列表"><input type="checkbox" id="appsAuto" onchange="toggleAppsAuto(this)"> 自动刷新</label>
    <span class="refresh" onclick="loadApplications()">刷新</span>
  </div>
  <div id="appStatsRow" style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0"></div>
  <div class="table-wrap"><table id="appsTable" style="width:100%;border-collapse:collapse;font-size:.85rem"><thead><tr style="background:var(--bg)">
    <th class="select-col" style="width:72px"><span style="display:inline-flex;align-items:center;gap:4px">选择 <input type="checkbox" onclick="appToggleAll(this)"></span></th>
    <th>岗位</th><th>公司</th><th>状态</th><th>链接</th><th onclick="sortApps('updated_at')" title="点击排序">更新时间 <span id="sortAppsUpdated" style="font-size:.65rem"></span></th><th style="width:90px;white-space:nowrap">操作</th>
  </tr></thead><tbody id="applicationsTb"></tbody></table></div>
</div>
</div>

<!-- Global Modal -->
<div id="globalModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9999;align-items:center;justify-content:center">
  <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:24px;max-width:380px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,.18)">
    <div id="globalModalTitle" style="font-weight:700;font-size:1rem;margin-bottom:10px;color:var(--text)">提醒</div>
    <div id="globalModalMsg" style="font-size:.88rem;color:var(--text);line-height:1.6;margin-bottom:18px;white-space:pre-line"></div>
    <div style="text-align:right"><button onclick="closeGlobalModal()" style="background:var(--accent);color:#fff;border:none;padding:7px 22px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">确定</button></div>
  </div>
</div>
<!-- Content Modal (large, for results/previews) -->
<div id="contentModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9998;align-items:center;justify-content:center;padding:20px">
  <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;max-width:820px;width:95%;max-height:88vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.2)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border)">
      <b id="contentModalTitle" style="font-size:1rem">预览</b>
      <button onclick="closeContentModal()" style="background:transparent;border:none;font-size:1.2rem;cursor:pointer;color:var(--muted);line-height:1">✕</button>
    </div>
    <div id="contentModalBody" aria-live="polite" style="overflow:auto;flex:1;font-size:.85rem;line-height:1.7"></div>
  </div>
</div>
<!-- Confirm Modal -->
<div id="confirmModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9999;align-items:center;justify-content:center">
  <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:24px;max-width:380px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,.18)">
    <div id="confirmModalMsg" style="font-size:.88rem;color:var(--text);line-height:1.6;margin-bottom:18px;white-space:pre-line"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button id="confirmModalNo" style="background:var(--card);color:var(--text);border:1px solid var(--border);padding:7px 18px;border-radius:6px;cursor:pointer;font-size:.85rem">取消</button>
      <button id="confirmModalYes" style="background:var(--accent);color:#fff;border:none;padding:7px 18px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">确定</button>
    </div>
  </div>
</div>
<!-- Pipeline Panel -->
<div id="pipeline-panel" class="panel">
  <div class="bar" style="flex-wrap:wrap">
    <span style="font-size:.85rem;color:var(--muted)">各阶段执行状态</span>
    <span class="refresh" onclick="loadPipeline()" style="margin-left:auto">刷新</span>
    <div id="pipeStats" style="flex-basis:100%;margin-top:10px"></div>
  </div>
  <div class="post-stages-title">核心流程</div>
  <div id="pipeContainer"></div>
  <!-- post-pipeline stages (Task 3) -->
  <div class="post-stages-section">
    <div class="post-stages-title">后续阶段</div>
    <div class="post-stages-grid">
      <div class="post-stage-card" onclick="goToStage('interview-prep')">
        <div style="font-weight:700;font-size:1rem"><span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;background:var(--accent);color:#fff;border-radius:50%;font-size:.7rem;margin-right:5px;vertical-align:middle">7</span>模拟面试</div>
        <div id="postCountMockNum" style="font-size:.85rem;color:var(--muted);margin:4px 0">-</div>
        <div id="postCountMock" style="font-size:.75rem;color:#3d7a5a">暂无数据</div>
      </div>
      <div class="post-stage-card" onclick="goToStage('offer-eval')">
        <div style="font-weight:700;font-size:1rem"><span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;background:var(--accent);color:#fff;border-radius:50%;font-size:.7rem;margin-right:5px;vertical-align:middle">8</span>Offer 评估</div>
        <div id="postCountOfferNum" style="font-size:.85rem;color:var(--muted);margin:4px 0">-</div>
        <div id="postCountOffer" style="font-size:.75rem;color:#3d7a5a">暂无数据</div>
      </div>
      <div class="post-stage-card" onclick="goToStage('salary-negotiate')">
        <div style="font-weight:700;font-size:1rem"><span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;background:var(--accent);color:#fff;border-radius:50%;font-size:.7rem;margin-right:5px;vertical-align:middle">9</span>薪资谈判</div>
        <div id="postCountSalaryNum" style="font-size:.85rem;color:var(--muted);margin:4px 0">-</div>
        <div id="postCountSalary" style="font-size:.75rem;color:#3d7a5a">暂无数据</div>
      </div>
    </div>
  </div>
</div>

<!-- Mock Interview Panel (Stage 3) -->
<div id="mock-panel" class="panel">
  <div class="bar">
    <select id="mockJobSel" style="width:300px" onchange="updateMockControls()"><option value="">选择职位...</option></select>
    <label style="font-size:.8rem;color:var(--muted);display:inline-flex;align-items:center;gap:3px;cursor:pointer"><input type="checkbox" id="mockFromPrep" onchange="updateMockControls()"> 用 prep 题库</label>
    <input id="mockFocus" placeholder="focus 关键词(可选)" style="width:170px" oninput="updateMockControls()">
    <select id="mockDifficulty" title="难度为软提示；使用 prep 题库时题量不变" style="width:90px" onchange="updateMockControls()"><option value="easy" selected>简单</option><option value="medium">中等</option><option value="hard">困难</option></select>
    <select id="mockModeSel" onchange="onMockModeChange()" title="切换面试模式" style="width:108px"><option value="text" selected>文字面试</option><option value="realtime">实时语音</option></select>
    <button id="mockStartBtn" onclick="startMockInterview()" disabled style="background:var(--accent);color:#fff;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-weight:600">开始面试</button>
    <button id="mockEndBtn" onclick="endMockInterview()" disabled style="background:#c15a3a;color:#fff;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-weight:600">结束面试</button>
    <button id="mockClearBtn" onclick="clearMockPanel()" disabled style="background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:7px 12px;border-radius:6px;cursor:pointer;font-size:.82rem">🗑 清空</button>
    <button id="mockDlBtn" onclick="downloadMockTranscript()" disabled title="下载本次对话记录(txt)" style="background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:7px 12px;border-radius:6px;cursor:pointer;font-size:.82rem">📥下载记录</button>
  </div>
  <div id="mockStatus" style="font-size:.8rem;color:var(--muted);padding:4px 12px"></div>
  <div id="mockChat" style="max-height:58vh;min-height:300px;overflow-y:auto;padding:12px;background:var(--card);border:1px solid var(--border);border-radius:6px;margin-top:8px;display:flex;flex-direction:column;justify-content:center;align-items:center;color:var(--muted);font-size:.85rem;text-align:center">👋 还没有面试记录，从上方选择职位开始一次模拟面试</div>
  <div class="bar" style="margin-top:8px">
    <textarea id="mockInput" rows="1" placeholder="开始面试后可输入..." style="flex:1;resize:none;min-height:38px;max-height:120px;overflow-y:auto;font-family:inherit" oninput="this.style.height='auto';this.style.height=(this.scrollHeight<38?38:this.scrollHeight)+'px';if(!this.disabled){document.getElementById('mockSendBtn').disabled=!this.value.trim()}" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMockMessage()}" disabled></textarea>
    <button id="mockMicBtn" type="button" onclick="toggleMockMic()" title="语音输入 (Chrome)" disabled style="background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:7px 12px;border-radius:6px;cursor:pointer;font-size:1rem">🎤</button>
    <button id="mockSendBtn" onclick="sendMockMessage()" disabled style="background:var(--accent);color:#fff;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-weight:600">发送</button>
    <label style="font-size:.78rem;color:var(--muted);display:inline-flex;align-items:center;gap:3px;cursor:pointer"><input type="checkbox" id="mockTTS" onchange="updateMockControls()"> 朗读面试官</label>
    <span id="mockVoiceHint" style="font-size:.78rem;color:var(--muted)"></span>
  </div>
</div>

<!-- Offer Evaluation Panel (file-driven table) -->
<div id="offer-panel" class="panel">
  <div class="bar">
    <button onclick="compareOffers()" style="background:#7c3aed;color:#fff;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">⚖ offer对比(≥2)</button>
    <button id="offerBatchBtn" onclick="batchEvalOffers()" style="background:#0891b2;color:#fff;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">⚡ 批量评估</button>
    <button id="offerDelBtn" onclick="batchDeleteOffers()" style="background:#c15a3a;color:#fff;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">🗑 批量删除</button>
    <progress id="offerProgress" value="0" max="1" style="display:none;width:120px;height:8px;accent-color:var(--accent)"></progress>
    <span class="refresh" onclick="loadOfferTable()">刷新</span>
    <span style="font-size:.85rem;color:#b45309;background:#fef3c7;border:1px solid #f59e0b;border-radius:4px;padding:2px 8px;margin-left:8px;font-weight:600">💡 请先评估 Offer 再对比</span>
    <span id="offerStatus" style="font-size:.78rem;color:var(--muted);margin-left:auto"></span>
  </div>
  <div style="padding:10px 4px;font-size:.8rem;color:var(--muted);line-height:1.7">
    <b style="color:var(--text)">使用说明</b>：在「文件上传」tab 下载导入模板并上传 Offer .txt 后，在此表格里点「评估」。「预览评估结果」免重跑直接回看缓存；勾选 ≥2 个点「offer对比」可内联展示并保存对比报告。
  </div>
  <div style="overflow-x:auto;-webkit-overflow-scrolling:touch">
  <table style="text-align:center"><thead><tr>
    <th style="width:52px">编号</th>
    <th class="select-col" style="width:72px"><span style="display:inline-flex;align-items:center;gap:4px">选择 <input type="checkbox" onclick="offerToggleAll(this)" title="全选" aria-label="全选"></span></th><th>文件名</th><th>状态</th><th style="min-width:200px">操作</th>
  </tr></thead>
  <tbody id="offerTb"></tbody></table>
  </div>
  <div id="offerEmpty" style="display:none"><div class="empty-state"><span class="empty-ico">📭</span><div class="empty-title">暂无 Offer 文件</div><div class="empty-hint">请到「文件上传」tab 下载模板并上传 Offer .txt。</div></div></div>
  <div id="offerResult" style="margin-top:16px;border-top:1px dashed var(--border);padding-top:14px;display:none"></div>
  <div id="offerCompareArea" style="margin-top:16px;display:none"></div>
</div>

<!-- Salary Advice Panel -->
<div id="salary-panel" class="panel">
  <!-- 顶部操作栏：标题 + 导入 + 操作按钮 -->
  <div class="bar" style="align-items:center;flex-wrap:wrap;gap:10px">
    <span style="font-size:.9rem;font-weight:700">💰 薪资谈判</span>
    <select id="importOfferSel" onchange="importOfferEval(this.value)" style="font-size:.8rem;padding:4px;max-width:260px"><option value="">📥 导入已评估Offer...</option></select>
    <span style="flex:1"></span>
    <button id="salaryGenBtn" onclick="genSalaryAdvice()" style="background:var(--accent);color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-weight:600;font-size:.85rem">⚡ 生成建议</button>
    <button id="salarySaveBtn" onclick="saveSalaryAdvice()" style="display:none;background:var(--card);color:var(--text);border:1.5px solid var(--border);padding:8px 16px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600">💾 保存策略</button>
    <button id="salaryClearBtn" onclick="clearSalaryPanel()" style="background:var(--card);color:#c15a3a;border:1.5px solid #fecaca;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600" title="清空当前表单和结果（保留历史策略）">🗑 清空</button>
    <span id="salaryStatus" style="font-size:.78rem;color:var(--muted)"></span>
  </div>
  <!-- 表单三栏卡片（信息流布局） -->
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:14px" class="salary-form-grid">
    <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0">
      <div style="font-weight:700;font-size:.88rem;color:var(--accent);margin-bottom:2px">🏢 基本信息</div>
      <label style="font-size:.72rem;color:var(--muted)">公司 *</label>
      <input id="salaryCompany" placeholder="公司名" style="width:100%">
      <label style="font-size:.72rem;color:var(--muted)">职位</label>
      <input id="salaryTitle" placeholder="职位名" style="width:100%">
      <label style="font-size:.72rem;color:var(--muted)">谈判对象</label>
      <select id="salaryNegotiator" style="width:100%"><option value="HR">HR</option><option value="用人经理">用人经理</option><option value="猎头">猎头</option></select>
    </div>
    <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0">
      <div style="font-weight:700;font-size:.88rem;color:var(--accent);margin-bottom:2px">💵 薪酬期望</div>
      <label style="font-size:.72rem;color:var(--muted)">当前薪酬（月薪/月数/年包）</label>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        <input id="salaryBase" placeholder="月薪base(k)" style="flex:1.2 1 0;min-width:110px" oninput="calcSalaryAnnual()">
        <input id="salaryMonths" placeholder="月数" style="flex:0.8 1 0;min-width:80px" oninput="calcSalaryAnnual()">
        <input id="salaryAnnual" placeholder="年包(自动)" style="flex:1 1 0;min-width:110px;background:var(--bg);color:var(--muted);cursor:default" readonly onfocus="this.blur()">
      </div>
      <label style="font-size:.72rem;color:var(--muted)">目标（涨幅/期望）</label>
      <input id="salaryTarget" placeholder="如 涨幅30% / 35k*16" style="width:100%">
      <label style="font-size:.72rem;color:var(--muted)">底线（低于则放弃）</label>
      <input id="salaryFloor" placeholder="如 30k*16" style="width:100%">
      <label style="font-size:.72rem;color:var(--muted)">当前 Offer 文本（可选）</label>
      <input id="salaryOffer" placeholder="结构化已填可留空" style="width:100%">
    </div>
    <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0">
      <div style="font-weight:700;font-size:.88rem;color:var(--accent);margin-bottom:2px">🧠 背景补充</div>
      <label style="font-size:.72rem;color:var(--muted)">个人优势</label>
      <textarea id="salaryStrengths" placeholder="技能/经验/竞品Offer" style="width:100%;min-height:100px;font-size:.82rem;font-family:inherit;resize:vertical;min-width:0;word-break:break-word;box-sizing:border-box"></textarea>
      <label style="font-size:.72rem;color:var(--muted)">背景上下文</label>
      <textarea id="salaryContext" placeholder="行业/紧迫度/HR态度" style="width:100%;min-height:100px;font-size:.82rem;font-family:inherit;resize:vertical;min-width:0;word-break:break-word;box-sizing:border-box"></textarea>
    </div>
  </div>
  <!-- 结果区：锚定薪资 hero + 三列 -->
  <div id="salaryResult" style="margin-top:14px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px">
    <div style="color:var(--muted);font-size:.85rem;text-align:center;padding:48px 0"><div style="font-size:2.5rem;margin-bottom:10px">💰</div><div style="font-size:.95rem">填写上方谈判信息后点击「⚡ 生成建议」</div><div style="font-size:.78rem;margin-top:4px">输出锚定薪资 / 杠杆点 / 让步计划 / 话术</div></div>
  </div>
  <!-- 历史策略 chip 行 -->
  <div style="margin-top:14px">
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">📚 历史策略 <button onclick="clearSalaryHistory()" style="background:transparent;border:none;color:#c15a3a;cursor:pointer;font-size:.72rem;font-weight:600;padding:0" title="清空全部历史策略">🗑 清空全部</button></div>
    <div id="salaryList" style="display:flex;flex-wrap:wrap;gap:8px;min-height:36px;align-items:center">
      <div style="color:var(--muted);text-align:center;padding:8px 0;font-size:.82rem">暂无记录，生成后自动保存</div>
    </div>
    <div id="salarySaveStatus" style="font-size:.75rem;color:var(--muted);min-height:16px;margin-top:4px"></div>
  </div>
</div>

<script>
var _uploadCache={resumes:null,offers:null};
var _uploadSeq=0;
// --- shared helpers ---
var platNames={boss_zhipin:'BOSS直聘',liepin:'猎聘',zhilian:'智联招聘',job51:'前程无忧',maimai:'脉脉',tencent:'腾讯',netease:'网易',byd:'比亚迪',naura:'北方华创',yofc:'长飞',company_site:'官网'};
function escHtml(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML}
function escAttr(s){return escHtml(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function safeMd(s){if(typeof marked==='undefined')return s||'';var t=(s||'').replace(/^\s*```(?:markdown|md)?\s*\n?/i,'').replace(/\n?\s*```\s*$/,'');var h=marked.parse(t);return window.DOMPurify?DOMPurify.sanitize(h):h}

function stageClass(status){
  if(!status)return'st-search';
  if(status.includes('投递'))return'st-apply';
  if(status.includes('面')||status.includes('约'))return'st-interview';
  if(status.includes('Offer'))return'st-offer';
  if(status.includes('入职'))return'st-onboard';
  if(status.includes('终止'))return'st-terminated';
  return'st-search';
}
function badgeClass(status){
  if(!status)return'bg-search';
  if(status.includes('投递'))return'bg-apply';
  if(status.includes('面')||status.includes('约'))return'bg-interview';
  if(status.includes('Offer'))return'bg-offer';
  if(status.includes('入职'))return'bg-onboard';
  if(status.includes('终止'))return'bg-terminated';
  return'bg-search';
}
function fmtDate(iso){if(!iso)return'';var d=new Date(iso);return d.toLocaleDateString('zh-CN')+' '+d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}

function clearFilters(){document.getElementById("companyFilter").value="";document.getElementById("titleFilter").value="";document.getElementById("locFilter").value="";document.getElementById("platFilter").value="";document.getElementById("flagFilter").value="";document.getElementById("pageSize").value="0";jobsPage=1;loadJobs(1)};function clearData(){
  showConfirm('确定要清空所有职位数据吗？此操作不可恢复。',function(){
    fetch('/api/results',{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){allJobs=[];jobsTotal=0;jobsPages=1;renderJobs();renderJobsPgn();}
    });
  });
}
// --- jobs panel ---
// Default sort is by last_seen (server ORDER BY). sortKey='score' is a legacy
// no-op here: the 人工初筛 tab renders no score/rating column (jobs carry no
// `score` field -- prescreen was removed), so sorting by 'score' leaves every
// va/vb as undefined and the comparator degrades to a stable no-op. Kept as
// the initial value so renderJobs() never throws on a missing key.
let allJobs=[],sortKey='score',sortAsc=false;
let jobsPage=1,jobsPages=1,jobsTotal=0;
// 人工初筛自动刷新开关（30s 轮询，默认关）
var jobsAutoTimer=null;
function toggleJobsAuto(src){
  if(src&&src.checked){
    if(jobsAutoTimer)clearInterval(jobsAutoTimer);
    jobsAutoTimer=setInterval(function(){loadJobs(jobsPage||1)},30000);
  }else if(jobsAutoTimer){clearInterval(jobsAutoTimer);jobsAutoTimer=null;}
}
// 投递追踪自动刷新开关（30s 轮询，默认关）
var appsAutoTimer=null;
function toggleAppsAuto(src){
  if(src&&src.checked){
    if(appsAutoTimer)clearInterval(appsAutoTimer);
    appsAutoTimer=setInterval(function(){loadApplications()},30000);
  }else if(appsAutoTimer){clearInterval(appsAutoTimer);appsAutoTimer=null;}
}
// Refresh the 人工初筛 (jobs) tab WITHOUT a full page reload. Instead
// just re-fetch jobs and stay on this tab.
function refreshJobsTab(){
  var btn=event&&event.target;
  if(btn){btn.style.pointerEvents='none'}
  // reset to page 1 so the user sees the freshest full list
  loadJobs(1);
  // also refresh the platform dropdown contents (all_platforms) which
  // loadJobs already injects from the response -- nothing extra needed.
  setTimeout(function(){if(btn){btn.style.pointerEvents='auto'}},800);
}
function sort(k){sortAsc=sortKey===k?!sortAsc:false;sortKey=k;var inds=document.querySelectorAll(".sort-ind");inds.forEach(function(el){el.textContent="";el.classList.remove("active")});var th=document.querySelector("th[onclick*="+k+"]");if(th){var si=th.querySelector(".sort-ind");si.textContent=sortAsc?"▲":"▼";si.classList.add("active")};renderJobs()}
var _debounceTimer=null;function debounceLoad(){clearTimeout(_debounceTimer);_debounceTimer=setTimeout(function(){jobsPage=1;loadJobs(1)},300)};function loadJobs(page){
  jobsPage=page||1;
  fetch('/api/results?page='+jobsPage+'&page_size='+(document.getElementById('pageSize').value||'30')+'&platform='+(document.getElementById('platFilter').value||'')+'&company='+encodeURIComponent(document.getElementById('companyFilter').value||'')+'&title='+encodeURIComponent(document.getElementById('titleFilter').value||'')+'&location='+encodeURIComponent(document.getElementById('locFilter').value||'')+'&user_flag='+(document.getElementById('flagFilter').value||'')).then(function(r){return r.json()})
  .then(function(p){allJobs=p.items||p;jobsPages=p.pages||1;jobsTotal=p.total||allJobs.length;var pf=document.getElementById("platFilter");if(p.all_platforms){var cur=pf.value;pf.innerHTML="<option value=''>全部平台</option>"+p.all_platforms.map(function(x){return"<option value='"+x+"'>"+(platNames[x]||x)+"</option>"}).join("");pf.value=cur}renderJobs();renderJobsPgn()});
}
function renderJobsPgn(){
  var el=document.getElementById('jobsPgn');
  if(jobsTotal<=0){
    el.innerHTML='';
    return;
  }
  el.innerHTML='<button class="pgn-btn" '+(jobsPage<=1?'disabled':'')+' onclick="loadJobs('+(jobsPage-1)+')">上一页</button>'+
    '<span class="pgn-info">第 '+jobsPage+' / '+jobsPages+' 页 共 '+jobsTotal+' 条</span>'+
    '<button class="pgn-btn" '+(jobsPage>=jobsPages?'disabled':'')+' onclick="loadJobs('+(jobsPage+1)+')">下一页</button>';
}
function renderJobs(){
  let cf=document.getElementById('companyFilter').value.toLowerCase(),tf=document.getElementById('titleFilter').value.toLowerCase(),lf=document.getElementById('locFilter').value.toLowerCase(),pf=document.getElementById('platFilter').value;
  let df='';
  let rows=allJobs.slice()
  ;
  rows.sort(function(a,b){var va=a[sortKey]||'',vb=b[sortKey]||'';return typeof va==='number'?(sortAsc?va-vb:vb-va):sortAsc?(''+va).localeCompare(''+vb):(''+vb).localeCompare(''+va)});
  // 「全部」模式渲染上限保护：极端大数据量下只渲染前 500 行，避免整表 DOM 卡顿
  // （分页信息仍显示真实总数）
  var MAX_RENDER=500;
  if(rows.length>MAX_RENDER){rows=rows.slice(0,MAX_RENDER);}
  if(!rows.length){
    document.getElementById('tb').innerHTML='<tr><td colspan="7"><div class="empty-state"><span class="empty-ico">📭</span><div class="empty-title">暂无职位数据</div><div class="empty-hint">请先运行搜索，或在「流水线」执行搜索阶段。</div></div></td></tr>';
    updateJobsActions();
    document.getElementById('clockTime').textContent=new Date().toLocaleTimeString();
    return;
  }
  document.getElementById('tb').innerHTML=rows.map(function(j){
    var sc=j.score||j.rating||0;var txt=sc>0?sc+"%":"-";var cls=sc>=75?'s-high':sc>=60?'s-mid':'s-low';
    var sal=j.salary_max?((j.salary_min||0)/1000).toFixed(0)+'K-'+((j.salary_max||0)/1000).toFixed(0)+'K':(j.salary_min?'~'+((j.salary_min||0)/1000).toFixed(0)+'K':'面议');
    var newTag=j.is_new?'<span class="new-badge">新</span>':'';
    var urls=JSON.parse(j.urls||'{}');
    var links=Object.entries(urls).map(function(e){return'<a href="'+escHtml(e[1])+'" target="_blank">'+(platNames[e[0]]||e[0])+'</a>'}).join(' ');
    var flag=j.user_flag||'';
    var flagBtn='';
    if(flag==='interested'){flagBtn='<span style="color:#3d7a5a;font-weight:700;cursor:pointer" data-act="flag" data-id="'+j.id+'" title="点击清除标记">🌟 想投递</span>'}
    else if(flag==='rejected'){flagBtn='<span style="color:#c15a3a;font-weight:700;cursor:pointer" data-act="flag" data-id="'+j.id+'" title="点击标记 🌟 想投递">❌ 不合适</span>'}
    else{flagBtn='<span style="color:var(--muted);cursor:pointer;font-size:.82rem" data-act="flag" data-id="'+j.id+'" title="点击标记 ❌ 不合适">➖ 未标记</span>'}
    return'<tr><td title="'+escAttr(j.title)+'">'+escHtml(j.title)+newTag+'</td><td title="'+escAttr(j.company)+'">'+escHtml(j.company)+'</td><td>'+escHtml(j.location)+'</td><td><span class="sal">'+sal+'</span></td><td>'+links+'</td><td style="text-align:center"><input type="checkbox" class="job-cb" value="'+j.id+'" onclick="updateSelCount()"></td><td>'+flagBtn+'</td></tr>'}).join('');
  updateJobsActions();
  document.getElementById('clockTime').textContent=new Date().toLocaleTimeString();
}

function updateJobsActions(){
  // 无数据/无勾选/无 🌟 岗位时禁用对应操作，避免“点了没反应”。
  var rows=allJobs||[];
  var interested=rows.some(function(j){return j.user_flag==='interested'});
  var selected=document.querySelectorAll('.job-cb:checked').length;
  var fb=document.getElementById('fetchJDBtn');if(fb)fb.disabled=!interested;
  var vb=document.getElementById('viewJDBtn');if(vb)vb.disabled=!interested;
  var rb=document.getElementById('runMatchBtn');if(rb)rb.disabled=!interested;
  var bb=document.getElementById('batchFlagBtn');if(bb)bb.disabled=selected===0;
}

// --- timeline panel ---
let _removed_timeline_state;  // timeline_events 事件流已移除
function switchTab(t){
  document.querySelectorAll('.tab').forEach(function(el){el.classList.toggle('active',el.getAttribute('data-tab')===t)});
  ['jobs-panel','timeline-panel','pipeline-panel','match-panel','materials-panel','files-panel','resume-panel','mock-panel','offer-panel','salary-panel'].forEach(function(id){document.getElementById(id).classList.toggle('show',id.startsWith(t))});
  if(t==='pipeline'){setTimeout(loadPipeline,50);if(window._pipeTimer)clearInterval(window._pipeTimer);window._pipeTimer=setInterval(loadPipeline,30000)}
  else if(window._pipeTimer){clearInterval(window._pipeTimer);window._pipeTimer=null}
  if(t==='match'){loadMatch(1)}
  if(t==='materials'){loadMaterials()}
  if(t==='files'){loadFiles()}
  if(t==='resume'){switchUploadList()}
  if(t==='jobs'){loadJobs(jobsPage||1)}
  if(t==='timeline'){loadApplications()}
  if(t==='mock'){loadMockJobs();initMockVoice();loadRealtimeConfig()}
  if(t==='offer'){loadOfferTable()}
  if(t==='salary'){
    loadSalaryAdviceHistory();loadOfferImportOptions();
    // 2026-08-12: 不再自动恢复第一条历史 —— 刷新/切 tab 均保持当前状态（清空即清空），
    // 查看历史靠点击 chip（restoreSalary）。
  }
}
function goToStage(stage){
  if(stage==='interview-prep'){switchTab('mock');}
  else if(stage==='offer-eval'){switchTab('offer');}
  else if(stage==='salary-negotiate'){switchTab('salary');}
}
var appSortKey='updated_at';
var appSortDir=-1;
var appLimit=20;
function updateAppSortIndicator(){
  var el=document.getElementById('sortAppsUpdated');
  if(el){el.textContent=(appSortKey==='updated_at'?(appSortDir===-1?'▼':'▲'):'');}
}
function sortApps(key){
  if(appSortKey===key){appSortDir=-appSortDir;}
  else{appSortKey=key;appSortDir=-1;}
  updateAppSortIndicator();
  loadApplications();
}
function loadApplications(){
  updateAppSortIndicator();
  fetch('/api/applications').then(function(r){return r.json()}).then(function(d){
    var allItems=d.items||[];
    var items=allItems;
    var st=document.getElementById('appStatusFilter')?document.getElementById('appStatusFilter').value:'';
    if(st){items=items.filter(function(a){return a.status===st;});}
    var q=document.getElementById('appSearch')?document.getElementById('appSearch').value.trim().toLowerCase():'';
    if(q){items=items.filter(function(a){return ((a.job_title||'')+' '+(a.company||'')).toLowerCase().indexOf(q)>=0;});}
    items.sort(function(a,b){
      var av=a[appSortKey]||'',bv=b[appSortKey]||'';
      av=String(av).toLowerCase();bv=String(bv).toLowerCase();
      return av<bv?-appSortDir:(av>bv?appSortDir:0);
    });
    var visibleItems=items.slice(0, appLimit);
    var statsEl=document.getElementById('appStats');
    if(statsEl){
      if(visibleItems.length<items.length){
        statsEl.innerHTML='共 '+items.length+' 条（显示前 '+visibleItems.length+' 条） <a href="javascript:;" onclick="appLimit+=20;loadApplications()" style="color:var(--accent);font-weight:600">加载更多</a>';
      }else{
        statsEl.textContent='共 '+items.length+' 条';
      }
    }
    renderAppStats(allItems);
    renderApplications(visibleItems);
  });
}
function renderAppStats(items){
  var row=document.getElementById('appStatsRow');
  if(!row)return;
  var counts={待投递:0,已投递:0,HR已读:0,约面:0,一面:0,二面:0,Offer:0,入职:0,已终止:0};
  items.forEach(function(a){if(counts[a.status]!==undefined)counts[a.status]++;});
  var interview=counts['约面']+counts['一面']+counts['二面'];
  var chips=[
    {label:'待投递',n:counts['待投递'],cls:'st-pending'},
    {label:'已投递',n:counts['已投递'],cls:'st-applied'},
    {label:'HR已读',n:counts['HR已读'],cls:'st-hr'},
    {label:'面试中',n:interview,cls:'st-interview'},
    {label:'Offer',n:counts['Offer'],cls:'st-offer'},
    {label:'入职',n:counts['入职'],cls:'st-onboard'},
    {label:'已终止',n:counts['已终止'],cls:'st-ended'}
  ];
  row.innerHTML=chips.map(function(c){
    return '<span class="app-status '+c.cls+'" style="font-size:.72rem">'+c.label+' '+c.n+'</span>';
  }).join('');
}
function appStatusClass(s){
  if(s==='待投递')return 'st-pending';
  if(s==='已投递')return 'st-applied';
  if(s==='HR已读')return 'st-hr';
  if(s==='约面'||s==='一面'||s==='二面')return 'st-interview';
  if(s==='Offer')return 'st-offer';
  if(s==='入职')return 'st-onboard';
  if(s==='已终止')return 'st-ended';
  return '';
}
function renderApplications(items){
  var tb=document.getElementById('applicationsTb');
  if(!items.length){tb.innerHTML='<tr><td colspan="7"><div class="empty-state"><span class="empty-ico">📭</span><div class="empty-title">暂无投递记录</div><div class="empty-hint">在材料审核台确认简历后，投递记录会自动生成到这里。</div></div></td></tr>';return;}
  var statuses=['待投递','已投递','HR已读','约面','一面','二面','Offer','入职','已终止'];
  tb.innerHTML=items.map(function(a){
    var opts=statuses.map(function(s){return '<option value="'+s+'"'+(s===a.status?' selected':'')+'>'+s+'</option>'}).join('');
    var urls={};try{urls=JSON.parse(a.urls||'{}')}catch(e){}
    var links=Object.entries(urls).map(function(e){return '<a href="'+escHtml(e[1])+'" target="_blank">'+(platNames[e[0]]||e[0])+'</a>'}).join(' ');
    return '<tr><td><input type="checkbox" class="app-ck" value="'+escHtml(a.id)+'"></td><td style="padding:4px">'+escHtml(a.job_title||'')+'</td><td style="padding:4px;color:var(--muted)">'+escHtml(a.company||'')+'</td><td style="padding:4px"><select data-act="appStatus" data-id="'+escHtml(a.id)+'" class="app-status '+appStatusClass(a.status)+'" style="font-size:.76rem">'+opts+'</select></td><td style="padding:4px;font-size:.75rem">'+links+'</td><td style="padding:4px;font-size:.75rem;color:var(--muted)">'+(a.updated_at||'').replace('T',' ').slice(0,16)+'</td><td><button data-act="delApp" data-id="'+a.id+'" style="background:var(--card);color:#c15a3a;border:1px solid #fecaca;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:.76rem;white-space:nowrap" title="删除">删除</button></td></tr>';
  }).join('');
}
function showAddAppModal(){
  var statuses=['待投递','已投递','HR已读','约面','一面','二面','Offer','入职','已终止'];
  var opts=statuses.map(function(s){return '<option value="'+s+'">'+s+'</option>'}).join('');
  var html='<div style="display:flex;flex-direction:column;gap:10px;padding:4px 2px">'
    +'<div><div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">岗位 ID <span style="color:#ef4444">*</span>（可在人工初筛表格或数据库 jobs 表中找到）</div>'
    +'<input id="addAppJobId" placeholder="例如 j1" style="width:100%;padding:8px 10px;box-sizing:border-box"></div>'
    +'<div><div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">初始状态</div>'
    +'<select id="addAppStatus" style="width:100%;padding:8px 10px">'+opts+'</select></div>'
    +'<div style="display:flex;gap:8px;justify-content:flex-end">'
    +'<button onclick="closeContentModal()" style="background:var(--card);color:var(--text);border:1px solid var(--border);padding:9px 14px;border-radius:6px;cursor:pointer;font-size:.85rem">取消</button>'
    +'<button onclick="submitAddApp()" style="background:var(--accent);color:#fff;border:none;padding:9px 14px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600">创建投递记录</button>'
    +'</div>'
    +'</div>';
  showContentModal('➕ 手动新增投递记录', html);
}
function submitAddApp(){
  var jobId=document.getElementById('addAppJobId')?document.getElementById('addAppJobId').value.trim():'';
  var status=document.getElementById('addAppStatus')?document.getElementById('addAppStatus').value:'待投递';
  if(!jobId){showModal('请填写岗位 ID');return;}
  fetch('/api/application',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,status:status})})
    .then(function(r){return r.json()}).then(function(d){
      if(d.ok){closeContentModal();showModal('已新增投递记录');loadApplications();}
      else{showModal(d.error||d.message||'新增失败');}
    }).catch(function(e){showModal('新增失败：'+e.message);});
}
function deleteApp(appId){
  showConfirm('确定删除这条投递记录？此操作不可恢复。',function(){
  fetch('/api/application?id='+encodeURIComponent(appId),{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){if(d.ok){loadApplications();}else{showModal('删除失败');}}).catch(function(e){showModal('删除失败：'+e.message)});
  });
}
function appToggleAll(src){
  document.querySelectorAll('.app-ck').forEach(function(c){c.checked=src.checked});
}
function deleteApps(){
  var ids=[];document.querySelectorAll('.app-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要删除的投递记录');return;}
  showConfirm('确定删除选中的 '+ids.length+' 条投递记录？此操作不可恢复。',function(){
  Promise.all(ids.map(function(id){return fetch('/api/application?id='+encodeURIComponent(id),{method:'DELETE'}).then(function(r){return r.json()})}))
    .then(function(){showModal('删除完成');loadApplications();var sa=document.querySelector('#applicationsBar thead input[type=checkbox]');if(sa)sa.checked=false;})
    .catch(function(e){showModal('删除失败：'+e.message)});
  });
}
function batchUpdateAppStatus(){
  var status=document.getElementById('appBatchStatus').value;
  if(!status){showModal('提示：请选择批量操作类型');return;}
  var ids=[];document.querySelectorAll('.app-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选职位');return;}
  showConfirm('确定将选中的 '+ids.length+' 个职位状态改为「'+status+'」？',function(){
  Promise.all(ids.map(function(id){return fetch('/api/application/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id,status:status})}).then(function(r){return r.json()})}))
    .then(function(){showModal('批量更新完成');loadApplications();var sa=document.querySelector('#applicationsBar thead input[type=checkbox]');if(sa)sa.checked=false;})
    .catch(function(e){showModal('批量更新失败：'+e.message)});
  });
}
function updateAppStatus(appId,status){
  fetch('/api/application/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:appId,status:status})})
    .then(function(r){return r.json()}).then(function(d){ if(!d.ok){showModal('更新失败：'+(d.message||''));} });
}
function setReminder(){
  var d=document.getElementById('reminderDays').value;
  fetch('/api/application/reminder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days:parseInt(d)||3})})
    .then(function(r){return r.json()}).then(function(d){ showModal(d.ok?'提醒周期已设为 '+d.reminder_days+' 天，Dashboard 后台会自动检查并提醒。':'设置失败'); });
}
// timeline_events 事件流已移除（投递追踪 tab 只保留投递状态区）
// --- pipeline tab ---
function loadPipeline(){
  fetch('/api/pipeline').then(function(r){return r.json()}).then(function(d){
    var stages=d.stages||{};
    var order=['search','filter','match','tailor','materials','track'];
    var tabMap={search:'jobs',filter:'jobs',match:'match',tailor:'materials',materials:'materials',track:'timeline'};
    var labelMap={search:'搜索',filter:'筛选',match:'匹配',tailor:'生成材料',materials:'审核',track:'投递'};
    var verbMap={search:'已收录',filter:'已筛选',match:'已匹配',tailor:'已生成',materials:'已审核',track:'已投递'};
    var html='<div class="stage-grid">';
    order.forEach(function(k,idx){
      var s=stages[k]||{label:k,count:0,done:false,last_run:null,hint:''};
      var label=labelMap[k]||s.label;
      var verb=verbMap[k]||'已收录';
      var icon='&#10003;';
      var color=s.done?'#3d7a5a':'#999';
      var countStr=s.count!==null && s.count!==undefined?s.count+''+((s.count+'').match(/^\d+$/)?' 个':''):'';
      var countLine='<div style="font-size:.85rem;color:var(--muted);margin:4px 0">'+(countStr||'-')+'</div>';
      var metaLine;
      if(s.count>0){
        metaLine='<div style="font-size:.75rem;color:#3d7a5a">'+verb+' '+countStr+'</div>';
      }else if(s.last_run){
        metaLine='<div style="font-size:.72rem;color:var(--muted)">'+fmtDate(s.last_run)+'</div>';
      }else{
        metaLine='<div style="font-size:.75rem;color:#8b7355">'+(s.hint||'暂无记录')+'</div>';
      }
      html+='<div data-tab="'+(tabMap[k]||'jobs')+'" onclick="switchTab(this.dataset.tab)" class="stage-card" style="border-left:5px solid '+(s.done?'#3d7a5a':'#ccc')+'"><div style="font-weight:700;font-size:1rem"><span style="display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;background:var(--accent);color:#fff;border-radius:50%;font-size:.7rem;margin-right:5px;vertical-align:middle">'+(idx+1)+'</span>'+label+'</div>'+countLine+metaLine+'</div>';
    });
    var _done=0;order.forEach(function(k){if(stages[k]&&stages[k].done)_done++;});
    var pc=d.post_counts||{};
    var postDone=(pc.mock?1:0)+(pc.offer?1:0)+(pc.salary?1:0);
    var _done9=_done+postDone;
    var _total9=9;
    var _pct9=Math.round(_done9/_total9*100);
    var _sc=function(k){return (stages[k]&&stages[k].count!=null)?stages[k].count:0;};
    var _next='';for(var ni=0;ni<order.length;ni++){var _k=order[ni];if(stages[_k]&&!stages[_k].done){_next=stages[_k].label;break;}}
    var _ps='<div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:14px;width:100%">';
    _ps+='<div style="display:flex;align-items:center;gap:8px;flex:1 1 100%;min-width:260px"><span style="font-size:.8rem;color:var(--muted)">已覆盖阶段</span><div style="flex:1;min-width:160px;height:10px;background:var(--bg);border:1px solid var(--border);border-radius:5px;overflow:hidden"><div style="width:'+_pct9+'%;height:100%;background:var(--accent);transition:width .3s"></div></div><span style="font-size:.78rem;color:var(--muted)">'+_done9+'/'+_total9+' ('+_pct9+'%)</span></div>';
    _ps+='<div style="font-size:.78rem;color:var(--muted)">漏斗: 搜索 '+_sc('search')+' → 筛选 '+_sc('filter')+' → 匹配 '+_sc('match')+' → 生成材料 '+_sc('tailor')+' → 审核 '+_sc('materials')+' → 投递 '+_sc('track')+' → 模拟面试 '+(pc.mock||0)+' → Offer 评估 '+(pc.offer||0)+' → 薪资谈判 '+(pc.salary||0)+' <span style="cursor:help;color:var(--accent);font-weight:700" title="生成材料数可能大于匹配岗位数：同一岗位可生成多份定制版本；审核数为进入材料审核台的草稿数">ⓘ</span></div>';
    if(_next)_ps+='<div style="font-size:.8rem;color:var(--accent);font-weight:600;background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.25);border-radius:6px;padding:6px 12px">➡ 下一步: '+_next+'</div>';
    if(d.search_status&&d.search_status.length){
      var stLine='最近搜索: '+d.search_status.map(function(x){var ic=x.status==='success'?'✅':(x.status==='error'?'❌':'🔹');return ic+' '+(platNames[x.platform]||x.platform)+' '+x.result_count+' 条'+(x.error_message?'('+x.error_message+')':'')}).join(' · ');
      _ps+='<div style="font-size:.78rem;color:var(--muted);flex-basis:100%">'+stLine+'</div>';
    }
    _ps+='</div>';
    var _psEl=document.getElementById('pipeStats');if(_psEl)_psEl.innerHTML=_ps;
    document.getElementById('pipeContainer').innerHTML=html;
    var pm=document.getElementById('postCountMock'),pmn=document.getElementById('postCountMockNum');if(pmn){pmn.textContent=pc.mock?(pc.mock+' 次'):'-';}if(pm){pm.textContent=pc.mock?('已练习 '+pc.mock+' 次'):'暂无数据';var _pcm=pm.closest('.post-stage-card');if(_pcm)_pcm.classList.toggle('done',!!pc.mock);}
    var po=document.getElementById('postCountOffer'),pon=document.getElementById('postCountOfferNum');if(pon){pon.textContent=pc.offer?(pc.offer+' 个'):'-';}if(po){po.textContent=pc.offer?('已评估 '+pc.offer+' 个'):'暂无数据';var _pco=po.closest('.post-stage-card');if(_pco)_pco.classList.toggle('done',!!pc.offer);}
    var ps=document.getElementById('postCountSalary'),psn=document.getElementById('postCountSalaryNum');if(psn){psn.textContent=pc.salary?(pc.salary+' 条'):'-';}if(ps){ps.textContent=pc.salary?('已保存 '+pc.salary+' 条'):'暂无数据';var _pcs=ps.closest('.post-stage-card');if(_pcs)_pcs.classList.toggle('done',!!pc.salary);}
  });
}

// --- match tab ---
var matchPage=1,matchPages=1,matchTotal=0;
function loadMatch(page){
  matchPage=page||1;
  var ms=document.getElementById('matchMinScore').value;
  var url='/api/match?page='+matchPage+'&page_size=30';
  if(ms>0)url+='&min_score='+ms;
  fetch(url).then(function(r){return r.json()}).then(function(p){
    var items=p.items||[];
    matchPages=p.pages||1;
    matchTotal=p.total||items.length;
    var filter=document.getElementById('matchFilter').value.toLowerCase();
    var filtered=filter?items.filter(function(x){return(x.job_title||'').toLowerCase().includes(filter)||(x.company||'').toLowerCase().includes(filter)}):items;
    // 2026-08-12: pagination info must reflect the FILTERED count — before this fix
    // it always showed the server-side total (e.g. 12) while the table showed the
    // filtered rows (e.g. 1), which misled the user.
    var shownTotal=filter?filtered.length:matchTotal;
    var shownPages=filter?Math.max(1,Math.ceil(filtered.length/30)):matchPages;
    var hideDir=filtered.every(function(m){return !m.direction || m.direction==='default';});
    var mt=document.getElementById('matchTable');if(mt)mt.classList.toggle('hide-dir', hideDir);
    var tb=document.getElementById('matchTb');
    if(!filtered.length){
      var hasServerData=matchTotal>0;
      var tip;
      if(hasServerData){
        tip='<div style="padding:46px 20px;text-align:center;color:var(--muted);font-size:.86rem">'
          +'<div style="font-size:1.4rem;margin-bottom:8px">&#128269;</div>'
          +'<div style="font-weight:600;color:var(--text)">没有符合条件的匹配结果</div>'
          +'<div style="margin:8px 0">当前搜索/分数筛选没有命中，清空筛选后查看全部匹配结果。</div>'
          +'<button class="pgn-btn" onclick="clearMatchFilter();loadMatch(1)">清空筛选</button></div>';
      }else{
        tip='<div style="padding:46px 20px;text-align:center;color:var(--muted);font-size:.86rem">'
          +'<div style="font-size:1.4rem;margin-bottom:8px">&#127919;</div>'
          +'<div style="font-weight:600;color:var(--text)">暂无匹配结果</div>'
          +'<div style="margin:8px 0">请先到「人工初筛」把感兴趣岗位标记为 🌟，再点击「🧠 精排」生成匹配结果。</div>'
          +'<button class="pgn-btn" onclick="goToJobsTab()">去人工初筛</button></div>';
      }
      var colSpan=hideDir?8:9;
      tb.innerHTML='<tr><td colspan="'+colSpan+'">'+tip+'</td></tr>';
      document.getElementById('matchPgn').innerHTML='';
      updateMatchActions();
      return;
    }
    tb.innerHTML=filtered.map(function(m){
      var msAll=m.missing_skills||[];var msRaw=msAll.slice(0,5);var ms2=msRaw.map(function(g){return typeof g==='string'?g:(g.severity||'')+' '+g.gap+(g.reason?' ('+g.reason+')':'')}).join('; ');if(msAll.length>5)ms2+='；…还有 '+(msAll.length-5)+' 项';
      var sc=m.match_score||0;
      var cls=sc>=75?'s-high':sc>=60?'s-mid':'s-low';
      var urls={};try{urls=JSON.parse(m.urls||'{}')}catch(e){}var links=Object.entries(urls).map(function(e){return'<a href="'+escHtml(e[1])+'" target="_blank">'+(platNames[e[0]]||e[0])+'</a>'}).join(' ');
      var fbBtns='<button data-act="fb" data-id="'+m.job_id+'" data-type="too_low" title="我认为匹配分应更高" style="cursor:pointer;background:#eff6ff;border:1px solid #bfdbfe;border-radius:4px;font-size:.68rem;padding:2px 5px;color:#1d4ed8;font-weight:600">偏低</button> <button data-act="fb" data-id="'+m.job_id+'" data-type="too_high" title="我认为匹配分应更低" style="cursor:pointer;background:#fffbeb;border:1px solid #fde68a;border-radius:4px;font-size:.68rem;padding:2px 5px;color:#b45309;font-weight:600">偏高</button>';
      var dirName=(m.direction||'')==='default'?'默认方向':(m.direction||'');
      return '<tr><td><input type="checkbox" class="match-ck" value="'+escHtml(m.job_id)+'" onclick="updateMatchActions()"></td><td><span class="score '+cls+'">'+sc+'%</span></td><td title="'+escAttr(m.job_title||'')+'">'+escHtml(m.job_title)+'</td><td title="'+escAttr(m.company||'')+'">'+escHtml(m.company)+'</td><td>'+escHtml(dirName)+'</td><td class="match-cell" title="点击查看完整缺口" data-full="'+escAttr(ms2)+'" onclick="showMatchCell(this)">'+escHtml(ms2)+'</td><td class="match-cell" title="点击查看完整理由" data-full="'+escAttr(m.match_reason||'')+'" onclick="showMatchCell(this)">'+escHtml(m.match_reason||'')+'</td><td>'+links+'</td><td>'+fbBtns+'</td></tr>';
    }).join('');
    document.getElementById('matchPgn').innerHTML='<button class="pgn-btn" '+(matchPage<=1?'disabled':'')+' onclick="loadMatch('+(matchPage-1)+')">上一页</button><span class="pgn-info">第 '+matchPage+'/'+shownPages+' 页 共 '+shownTotal+' 条</span><button class="pgn-btn" '+(matchPage>=shownPages?'disabled':'')+' onclick="loadMatch('+(matchPage+1)+')">下一页</button>';
    updateMatchActions();
  });
}
function updateMatchActions(){
  var selected=document.querySelectorAll('.match-ck:checked').length;
  var rows=document.querySelectorAll('#matchTb .match-ck').length;
  var gb=document.getElementById('generateMatBtn');if(gb)gb.disabled=selected===0;
  var lb=document.getElementById('batchLowBtn');if(lb)lb.disabled=selected===0;
  var hb=document.getElementById('batchHighBtn');if(hb)hb.disabled=selected===0;
  var cb=document.getElementById('clearMatchBtn');if(cb)cb.disabled=matchTotal<=0;
  var sa=document.getElementById('matchSelectAll');if(sa){sa.disabled=rows===0;if(rows===0)sa.checked=false;}
}
function matchFeedback(jobId,fbType,ev){ev.stopPropagation();
  fetch('/api/match/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,feedback_type:fbType})})
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){showModal((fbType==='too_low'?'📈 已记录：评分偏低':'📉 已记录：评分偏高')+'\n累计反馈：'+d.total_feedback+' 条')}
    else{showModal('记录失败')}
  });
}
function showMatchCell(el){
  var full=el.getAttribute('data-full')||'';
  showContentModal(el.title||'详情','<div class="md-body"><pre style="white-space:pre-wrap;word-break:break-word;font-size:.82rem;line-height:1.6">'+escHtml(full)+'</pre></div>');
}
function batchMatchFeedback(fbType){
  var ids=[];document.querySelectorAll('.match-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要校准的职位');return;}
  showConfirm('将 '+ids.length+' 个职位标记为'+(fbType==='too_low'?'评分偏低':'评分偏高')+'？',function(){
  var i=0,failed=0;
  function next(){
    if(i>=ids.length){showModal('批量校准完成：成功 '+(ids.length-failed)+'/'+ids.length);return;}
    fetch('/api/match/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:ids[i],feedback_type:fbType})})
      .then(function(r){return r.json()}).then(function(d){if(!d.ok)failed++;i++;next();})
      .catch(function(e){failed++;i++;next();});
  }
  next();
  });
}
function clearMatchFeedback(){
  showConfirm('确定清除全部历史匹配校准反馈？此操作不可恢复。',function(){
    fetch('/api/match/feedback',{method:'DELETE',headers:{'Content-Type':'application/json'}})
      .then(function(r){return r.json()}).then(function(d){
        if(d.ok){showModal('已清除历史反馈：'+d.deleted+' 条')}
        else{showModal('清除失败')}
      }).catch(function(){showModal('清除失败')});
  });
}
function matchToggleAll(src){
  document.querySelectorAll('.match-ck').forEach(function(c){c.checked=src.checked});
  updateMatchActions();
}
function generateMaterials(){
  var ids=[];document.querySelectorAll('.match-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要生成求职材料的职位');return;}
  showConfirm('将为选中的 '+ids.length+' 个职位生成「定制简历 + HR打招呼消息 + 面试准备」草稿（全部进材料审核台审核，确认后才归档）？',function(){
  var ov=document.createElement('div');
  ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  ov.innerHTML='<div style="background:#fff;padding:24px 32px;border-radius:8px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.2)"><div style="font-size:1.1rem;font-weight:600;margin-bottom:8px">⏳ 正在生成 '+ids.length+' 个职位的求职材料</div><div id="matGenProgress" style="font-size:.85rem;color:#666;margin-top:10px">正在连接...</div><div style="font-size:.75rem;color:#999;margin-top:8px">每个职位约 1-3 分钟，请耐心等待...</div></div>';
  document.body.appendChild(ov);
  var timer=setInterval(function(){
    fetch('/api/materials/progress').then(function(r){return r.json()}).then(function(p){
      var box=document.getElementById('matGenProgress');if(!box)return;
      if(p.running){
        var cur=escHtml(p.current||'');var st=escHtml(p.status||'');
        box.innerHTML='<div style="font-weight:600;margin-bottom:4px">'+(p.done||0)+'/'+(p.total||0)+'</div>'
          +(cur?'<div style="margin-bottom:2px">'+cur+'</div>':'')
          +(st?'<div>'+st+'</div>':'');
      } else {
        box.innerHTML='<div>正在收尾...</div>';
      }
    }).catch(function(){});
  },1000);
  fetch('/api/materials/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_ids:ids})})
    .then(function(r){return r.json()}).then(function(d){
      document.body.removeChild(ov);
      if(d.ok){
        var msg='生成完成：成功 '+d.succeeded+'/'+d.total;
        if(d.failed&&d.failed.length){
          msg+='，失败 '+d.failed.length+' 个\n\n失败详情：';
          d.failed.forEach(function(f){
            msg+='\n· '+(f.job_id||'?')+' — '+(f.error||'未知错误');
          });
        }
        if(d.interview_prep_failed&&d.interview_prep_failed.length){
          msg+='\n\n⚠️ 面试准备生成失败 '+d.interview_prep_failed.length+' 个（简历/HR消息已生成）：';
          d.interview_prep_failed.forEach(function(f){
            msg+='\n· '+(f.job_id||'?')+' — '+(f.error||'未知错误');
          });
          msg+='\n可稍后在材料审核台对该职位单独重新生成。';
        }
        showModal(msg);loadMaterials();switchTab('materials');
      }
      else{showModal('生成失败：'+(d.message||'未知错误'));}
    }).catch(function(e){document.body.removeChild(ov);showModal('请求失败：'+e.message)})
    .finally(function(){clearInterval(timer);});
  });
}
function toggleAllMaterials(src){document.querySelectorAll('.mat-ck').forEach(function(c){c.checked=src.checked;});}
function batchRegenMaterials(){
  var ids=[];document.querySelectorAll('.mat-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要再生成的草稿');return;}
  if(ids.length>10){showModal('提示：单次最多再生成 10 个草稿，请减少选择');return;}
  showConfirm('将重新生成 '+ids.length+' 个职位的简历+HR消息（每个用各自的改进意见）？',function(){
  var ov=document.createElement('div');
  ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  ov.innerHTML='<div style="background:#fff;padding:24px 32px;border-radius:8px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.2)"><div style="font-size:1.1rem;font-weight:600;margin-bottom:8px" id="batchRegenStatus">⏳ 批量再生成 0/'+ids.length+'</div><div id="batchRegenStep" style="font-size:.85rem;color:#666;margin-top:6px">准备中...</div><div style="font-size:.75rem;color:#999;margin-top:8px">每个约 1-3 分钟，请耐心等待...</div></div>';
  document.body.appendChild(ov);
  var i=0,failed=[],prepFailed=[];
  var timer=setInterval(function(){
    fetch('/api/materials/progress').then(function(r){return r.json()}).then(function(p){
      var box=document.getElementById('batchRegenStep');if(!box)return;
      var cur=escHtml(p.current||'');var st=escHtml(p.status||'');
      box.innerHTML=(cur?'<div>'+cur+'</div>':'')+(st?'<div>'+st+'</div>':'');
    }).catch(function(){});
  },1000);
  function next(){
    if(i>=ids.length){
      clearInterval(timer);
      document.body.removeChild(ov);
      var msg='批量再生成完成：成功 '+(ids.length-failed.length)+'/'+ids.length;
      if(failed.length){msg+='，失败 '+failed.length+' 个\n\n失败详情：\n· '+failed.join('\n· ');}
      if(prepFailed.length){
        msg+='\n\n⚠️ 面试准备生成失败 '+prepFailed.length+' 个（简历/HR消息已更新）：\n· '+prepFailed.join('\n· ');
      }
      showModal(msg);loadMaterials();return;
    }
    var jobId=ids[i];
    var fbEl=document.getElementById('fb_'+jobId);
    var fb=fbEl?fbEl.value:'';
    document.getElementById('batchRegenStatus').textContent='⏳ 批量再生成 '+(i+1)+'/'+ids.length;
    fetch('/api/materials/regenerate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,feedback:fb})})
      .then(function(r){return r.json()}).then(function(d){
        if(!d.ok)failed.push(jobId);
        if(d.interview_prep_failed&&d.interview_prep_failed.length){
          prepFailed.push(jobId+' — '+d.interview_prep_failed[0].error);
        }
        i++;next();
      })
      .catch(function(e){failed.push(jobId);i++;next();});
  }
  next();
  });
}
function batchConfirmMaterials(){
  var ids=[];document.querySelectorAll('.mat-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要确认保存的草稿');return;}
  showConfirm('将确认保存 '+ids.length+' 个职位的草稿？会生成 .md/.docx/_hrmsg.md 文件并归档至「已生成文件」，同时自动建投递追踪记录。',function(){
  var ov=document.createElement('div');
  ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  ov.innerHTML='<div style="background:#fff;padding:24px 32px;border-radius:8px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.2)"><div style="font-size:1.1rem;font-weight:600" id="batchConfirmStatus">⏳ 批量确认保存 0/'+ids.length+'</div></div>';
  document.body.appendChild(ov);
  var i=0,failed=[];
  function next(){
    if(i>=ids.length){document.body.removeChild(ov);showModal('批量确认保存完成：成功 '+(ids.length-failed.length)+'/'+ids.length+(failed.length?('，失败 '+failed.length):''));loadMaterials();loadFiles();return;}
    var jobId=ids[i];
    document.getElementById('batchConfirmStatus').textContent='⏳ 批量确认保存 '+(i+1)+'/'+ids.length;
    fetch('/api/materials/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})})
      .then(function(r){return r.json()}).then(function(d){if(!d.ok)failed.push(jobId);i++;next();})
      .catch(function(e){failed.push(jobId);i++;next();});
  }
  next();
  });
}
function batchDeleteMaterials(){
  var ids=[];document.querySelectorAll('.mat-ck:checked').forEach(function(c){ids.push(c.value)});
  if(!ids.length){showModal('提示：请先勾选要删除的草稿');return;}
  showConfirm('确定删除选中的 '+ids.length+' 个草稿？此操作不可恢复。',function(){
    fetch('/api/materials',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_ids:ids})})
      .then(function(r){return r.json()}).then(function(d){
        if(d.ok){showModal('已删除 '+d.deleted+' 个草稿');loadMaterials();}
        else{showModal('删除失败：'+(d.message||'未知错误'));}
      }).catch(function(e){showModal('请求失败：'+e.message)});
  });
}
function loadMaterials(){
  var st=document.getElementById('matStatusFilter')?document.getElementById('matStatusFilter').value:'draft';
  fetch('/api/materials/drafts?status='+st).then(function(r){return r.json()}).then(function(d){
    renderMaterials(d.items||[]);
  });
}
function renderMaterials(items){
  var el=document.getElementById('materialsList');
  if(!items.length){
    var st=document.getElementById('matStatusFilter')?document.getElementById('matStatusFilter').value:'draft';
    var tipTitle=st==='confirmed'?'暂无已确认的草稿':st==='all'?'暂无任何草稿':'暂无待审核草稿';
    var tipHint=st==='confirmed'?'草稿确认保存后才会显示在这里。':'请在「Agent智能匹配结果」勾选职位后点「生成求职材料」。';
    el.innerHTML='<div class="empty-state"><span class="empty-ico">📋</span><div class="empty-title">'+tipTitle+'</div><div class="empty-hint">'+tipHint+'</div></div>';return;
  }
  el.innerHTML=items.map(function(m){
    return '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
      +'<div style="display:flex;align-items:center;gap:8px"><input type="checkbox" class="mat-ck" value="'+escHtml(m.job_id)+'"><b>'+escHtml(m.job_title||'')+' @ '+escHtml(m.company||'')+'</b></div>'
      +'<span style="font-size:.75rem;color:var(--muted)">'+(m.status==='confirmed'?'<span style="color:#3a7c4f;font-weight:600">✓ 已确认</span> · ':'')+'v'+m.version+' · '+(m.direction||'')+' · '+(m.updated_at||'').slice(0,16).replace('T',' ')+'</span>'
      +'</div>'
      +'<details><summary style="cursor:pointer;font-size:.85rem;font-weight:600;color:#3a6b8c">📄 定制简历</summary><div style="margin-top:8px">'+safeMd(m.resume_md||'')+'</div></details>'
      +'<details style="margin-top:8px"><summary style="cursor:pointer;font-size:.85rem;font-weight:600;color:#3a6b8c">✉️ HR打招呼消息</summary><div style="margin-top:8px;padding:10px;background:#fff;border-radius:6px;border:1px solid var(--border);white-space:pre-wrap">'+escHtml(m.hr_message||'')+'</div></details>'
      +'<details style="margin-top:8px"><summary style="cursor:pointer;font-size:.85rem;font-weight:600;color:#3a6b8c">📋 面试准备（含自我介绍）</summary><div style="margin-top:8px">'+(m.interview_prep_md?safeMd(m.interview_prep_md):'<span style="color:var(--muted);font-size:.82rem">暂无面试准备文件。可在匹配结果中重新生成。</span>')+'</div></details>'
      +'<div style="margin-top:10px"><textarea id="fb_'+m.job_id+'" placeholder="改进意见（再生成时参考）" style="width:100%;min-height:48px;padding:6px;border:1px solid var(--border);border-radius:6px;font-size:.82rem">'+escHtml(m.feedback||'')+'</textarea>'
      +'<div style="margin-top:6px;display:flex;gap:8px">'
      +'<button data-act="regenMat" data-id="'+m.job_id+'" style="background:#c15a3a;color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem">🔄 再生成</button>'
      +'<button data-act="confirmMat" data-id="'+m.job_id+'" style="background:#3a7c4f;color:#fff;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.82rem">✓ 确认保存</button>'
      +'</div></div>'
      +'</div>';
  }).join('');
}
function regenMaterial(jobId){
  var fb=document.getElementById('fb_'+jobId).value;
  var ov=document.createElement('div');
  ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  ov.innerHTML='<div style="background:#fff;padding:24px 32px;border-radius:8px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.2)"><div style="font-size:1.1rem;font-weight:600;margin-bottom:8px">⏳ 正在重新生成求职材料</div><div id="matGenProgress" style="font-size:.85rem;color:#666;margin-top:10px">正在连接...</div><div style="font-size:.75rem;color:#999;margin-top:8px">约 1-3 分钟，请耐心等待...</div></div>';
  document.body.appendChild(ov);
  var timer=setInterval(function(){
    fetch('/api/materials/progress').then(function(r){return r.json()}).then(function(p){
      var box=document.getElementById('matGenProgress');if(!box)return;
      if(p.running){
        var cur=escHtml(p.current||'');var st=escHtml(p.status||'');
        box.innerHTML='<div style="font-weight:600;margin-bottom:4px">'+(p.done||0)+'/'+(p.total||0)+'</div>'
          +(cur?'<div style="margin-bottom:2px">'+cur+'</div>':'')
          +(st?'<div>'+st+'</div>':'');
      } else {
        box.innerHTML='<div>正在收尾...</div>';
      }
    }).catch(function(){});
  },1000);
  fetch('/api/materials/regenerate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,feedback:fb})})
    .then(function(r){return r.json()}).then(function(d){
      document.body.removeChild(ov);
      if(d.ok){showModal('已重新生成（v'+d.version+'）');loadMaterials();}
      else{showModal('再生成失败：'+(d.message||'未知错误'));}
    }).catch(function(e){document.body.removeChild(ov);showModal('请求失败：'+e.message)})
    .finally(function(){clearInterval(timer);});
}
function confirmMaterial(jobId){
  showConfirm('确认保存？将生成 .docx/.md 文件并归档至「已生成文件」tab。',function(){
  fetch('/api/materials/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})})
    .then(function(r){return r.json()}).then(function(d){
      if(d.ok){showModal('已保存：\n简历：'+d.resume_docx+'\nHR消息：'+d.hr_message);loadMaterials();loadFiles();}
      else{showModal('保存失败：'+(d.message||'未知错误'));}
    }).catch(function(e){showModal('请求失败：'+e.message)});
  });
}
function clearMatch(){
  showConfirm('确定清空全部精排匹配结果？\n（仅清除 match_results 表，不影响岗位数据和标记）',function(){
    fetch('/api/match',{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){
      if(d&&d.ok){
        showModal('已清空 '+(d.deleted||0)+' 条匹配结果');
        loadMatch(1);
      }else{
        showModal('清空失败：'+(d&&d.message||'未知错误'));
      }
    }).catch(function(e){showModal('请求失败：'+e.message)});
  });
}
function clearMatchFilter(){
  document.getElementById('matchFilter').value='';
  document.getElementById('matchMinScore').value='0';
  loadMatch(1);
}
function previewFile(path){
  fetch('/api/file?path='+encodeURIComponent(path)).then(function(r){return r.json()}).then(function(d){
    if(d.is_html){
      // Offer eval HTML（雷达图+布局）: 原样内嵌渲染
      showContentModal('📄 '+path,'<div style="padding:4px">'+ (d.content||'') +'</div>');
    }else if(/mock_interview_assessment|realtime_mock_assessment/.test(path)){
      // Mock interview assessment: render as radar-chart report (like offer eval)
      showContentModal('📄 '+path,'<div style="text-align:center;padding:40px 20px;color:var(--muted)">加载评估报告…</div>');
      fetch('/api/mock-assessment/preview?name='+encodeURIComponent(path)).then(function(r){return r.json()}).then(function(ad){
        if(ad&&ad.ok&&ad.assessment){
          _mockAssessmentCache[path]=ad;
          showContentModal('📄 '+path,renderMockAssessment(ad,path));
        }else{
          showContentModal('📄 '+path,'<div class="md-body">'+safeMd(d.content||'')+'</div>');
        }
      }).catch(function(){showContentModal('📄 '+path,'<div class="md-body">'+safeMd(d.content||'')+'</div>');});
    }else{
      showContentModal('📄 '+path,'<div class="md-body">'+safeMd(d.content||'')+'</div>');
    }
  }).catch(function(e){showModal('预览失败：'+e.message)});
}
function deleteFile(name){
  showConfirm('确定删除文件「'+name+'」？将删除磁盘文件+记录，不可恢复。',function(){
    fetch('/api/file?path='+encodeURIComponent(name),{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){if(d.ok){loadFiles();}else{showModal('删除失败');}}).catch(function(e){showModal('删除失败：'+e.message)});
  });
}
function fileToggleAll(src){document.querySelectorAll('.file-ck').forEach(function(c){c.checked=src.checked});updateFilesActions();}
function batchDeleteFiles(){
  var names=[];document.querySelectorAll('.file-ck:checked').forEach(function(c){names.push(c.value)});
  if(!names.length){showModal('提示：请先勾选要删除的文件');return;}
  var preview=names.length<=5?names.join('、'):names.slice(0,5).join('、')+' 等'+names.length+'个';
  showConfirm('确定删除选中的 '+names.length+' 个文件？将删除磁盘文件+记录，不可恢复：'+preview,function(){
    Promise.all(names.map(function(n){return fetch('/api/file?path='+encodeURIComponent(n),{method:'DELETE'}).then(function(r){return r.json()})}))
      .then(function(){showModal('✅ 删除完成');loadFiles();var sa=document.querySelector('#files-panel thead input[type=checkbox]');if(sa)sa.checked=false;})
      .catch(function(e){showModal('删除失败：'+e.message)});
  });
}
var filesLimit=20;
var filesSortKey='modified';
var filesSortDir=-1;
function updateFileSortIndicators(){
  var map={name:'sortName',size:'sortSize',modified:'sortModified'};
  Object.keys(map).forEach(function(k){
    var el=document.getElementById(map[k]);
    if(el){el.textContent=(filesSortKey===k?(filesSortDir===-1?'▼':'▲'):'');}
  });
}
function sortFiles(key){
  if(filesSortKey===key){filesSortDir=-filesSortDir;}
  else{filesSortKey=key;filesSortDir=-1;}
  updateFileSortIndicators();
  loadFiles();
}
function loadFiles(){
  updateFileSortIndicators();
  fetch('/api/files').then(function(r){return r.json()}).then(function(d){
    var allItems=d.items||[];
    var typeFilter=document.getElementById('fileTypeFilter')?document.getElementById('fileTypeFilter').value:'';
    var search=document.getElementById('fileSearch')?document.getElementById('fileSearch').value.trim().toLowerCase():'';
    var items=allItems;
    if(typeFilter){items=items.filter(function(f){return f.type===typeFilter});}
    if(search){items=items.filter(function(f){return (f.name||'').toLowerCase().indexOf(search)>=0;});}
    items.sort(function(a,b){
      var av=a[filesSortKey],bv=b[filesSortKey];
      if(filesSortKey==='size'){av=av||0;bv=bv||0;return (av-bv)*filesSortDir;}
      av=(av==null?'':String(av)).toLowerCase();bv=(bv==null?'':String(bv)).toLowerCase();
      return av<bv?-filesSortDir:(av>bv?filesSortDir:0);
    });
    var totalAll=allItems.length;
    var visibleItems=items.slice(0, filesLimit);
    var statParts=['共 '+items.length+' 个文件'];
    if(visibleItems.length<items.length){statParts.push('（显示前 '+visibleItems.length+' 个）');}
    if(typeFilter||search){statParts.push('（全部 '+totalAll+' 个）');}
    var statsEl=document.getElementById('filesStats');
    if(statsEl){
      if(visibleItems.length<items.length){
        statsEl.innerHTML=statParts.join(' ')+' <a href="javascript:;" onclick="filesLimit+=20;loadFiles()" style="color:var(--accent);font-weight:600">加载更多</a>';
      }else{
        statsEl.textContent=statParts.join(' ');
      }
    }
    var typeLabels={tailor_resume:'简历定制',cover_letter:'HR消息',interview_prep:'面试准备',mock_interview:'模拟面试',offer_eval:'Offer评估',offer_compare:'Offer对比',salary_advice:'薪资谈判'};
    var typeColors={tailor_resume:'#3d7a5a',cover_letter:'#2563eb',interview_prep:'#7c3aed',mock_interview:'#d97706',offer_eval:'#0891b2',offer_compare:'#6d28d9',salary_advice:'#db2777'};
    var ftb=document.getElementById('filesTb');
    if(!items.length){
      var tip;
      if(totalAll===0){
        tip='<div style="padding:46px 20px;text-align:center;color:var(--muted);font-size:.86rem">'
          +'<div style="font-size:1.4rem;margin-bottom:8px">&#128193;</div>'
          +'<div style="font-weight:600;color:var(--text)">暂无生成文件</div>'
          +'<div style="margin:8px 0">定制简历、HR消息、面试准备、Offer评估、薪资谈判等生成并确认后会归档到这里。</div>'
          +'<button class="pgn-btn" onclick="goToMatchTab()">去Agent匹配结果</button></div>';
      }else{
        tip='<div style="padding:46px 20px;text-align:center;color:var(--muted);font-size:.86rem">'
          +'<div style="font-size:1.4rem;margin-bottom:8px">&#128194;</div>'
          +'<div style="font-weight:600;color:var(--text)">该类型暂无文件</div>'
          +'<div style="margin:8px 0">当前类型筛选没有文件，可查看全部类型。</div>'
          +'<button class="pgn-btn" onclick="clearFileTypeFilter()">查看全部类型</button></div>';
      }
      ftb.innerHTML='<tr><td colspan="7">'+tip+'</td></tr>';
      updateFilesActions(0);
      var moreBtn=document.getElementById('filesMore');if(moreBtn){moreBtn.style.display='none';moreBtn.innerHTML='';}
      return;
    }
    ftb.innerHTML=visibleItems.map(function(f){
      var tl=typeLabels[f.type]||f.type;
      var sizeStr=(f.size/1024).toFixed(1)+'KB';
      var iconBg=f.ext==='.md'?'#2563eb':f.ext==='.json'?'#7c3aed':f.ext==='.docx'?'#6b7280':'#9ca3af';
      var iconLabel=(f.ext||'').replace('.','').toUpperCase()||'FILE';
      var icon='<span style="display:inline-block;min-width:36px;padding:1px 5px;border-radius:4px;font-size:.62rem;font-weight:700;color:#fff;background:'+iconBg+';text-align:center">'+iconLabel+'</span>';
      // jobTitle/company come from the generated_files catalog (v5+). For
      // legacy files cataloged from disk with no job row, show '--'.
      var jobText = (f.company||f.job_title) ? escHtml((f.company?f.company+' · ':'')+f.job_title) : '';
      var jobCell = jobText ? jobText : '<span style="color:var(--muted)">--</span>';
      var pvHtml=(f.ext==='.md'||f.ext==='.html'||f.ext==='.txt')?'<a href="javascript:;" onclick="previewFile(this.dataset.name)" data-name="'+escAttr(f.name)+'">预览</a>':'<span title="该类型暂不支持预览" style="min-width:56px;display:inline-block;opacity:.35;cursor:not-allowed;color:var(--muted)">预览</span>';
      return '<tr><td><input type="checkbox" class="file-ck" value="'+escAttr(f.name)+'" onclick="updateFilesActions()"></td><td title="'+escAttr(f.name)+'">'+icon+' '+escHtml(f.name)+'</td><td><span style="background:'+(typeColors[f.type]||'#666')+';color:#fff;padding:2px 8px;border-radius:10px;font-size:.72rem;white-space:nowrap">'+escHtml(tl)+'</span></td><td title="'+escAttr(jobText)+'">'+jobCell+'</td><td>'+sizeStr+'</td><td>'+escHtml((f.modified||'').replace('T',' ').slice(0,16))+'</td><td><span class="file-actions">'+pvHtml+'<a href="/api/file?path='+encodeURIComponent(f.name)+'&download=1" target="_blank" download>下载</a><a href="javascript:;" onclick="deleteFile(this.dataset.name)" data-name="'+escAttr(f.name)+'" class="delete-action">删除</a></span></td></tr>';
    }).join('');
    updateFilesActions(visibleItems.length);
    var moreBtn=document.getElementById('filesMore');
    if(moreBtn){
      if(visibleItems.length<items.length){
        moreBtn.style.display='block';
        moreBtn.innerHTML='<button class="pgn-btn" onclick="filesLimit+=20;loadFiles()">加载更多（还有 '+(items.length-visibleItems.length)+' 个）</button>';
      }else{
        moreBtn.style.display='none';
        moreBtn.innerHTML='';
      }
    }
  });
}
function goToJobsTab(){switchTab('jobs');}
function goToMatchTab(){switchTab('match');}
function clearFileTypeFilter(){document.getElementById('fileTypeFilter').value='';loadFiles();}
function updateFilesActions(visibleCount){
  if(visibleCount===undefined){visibleCount=document.querySelectorAll('.file-ck').length;}
  var selected=document.querySelectorAll('.file-ck:checked').length;
  var dl=document.getElementById('batchDownloadBtn');if(dl)dl.disabled=selected===0;
  var del=document.getElementById('batchDeleteBtn');if(del)del.disabled=selected===0;
  var sa=document.getElementById('fileSelectAll');
  if(sa){
    sa.disabled=(visibleCount||0)===0;
    if((visibleCount||0)===0)sa.checked=false;
  }
}
function batchDownloadFiles(){
  var names=[];document.querySelectorAll('.file-ck:checked').forEach(function(c){names.push(c.value)});
  if(!names.length){showModal('请先勾选要下载的文件');return;}
  var status=document.getElementById('filesStats');
  var old=status.textContent;status.textContent='正在打包 '+names.length+' 个文件...';
  fetch('/api/files/zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({names:names})})
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.blob();})
    .then(function(blob){
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a');a.href=url;a.download='jobagent_files.zip';document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(url);
      status.textContent=old;
    }).catch(function(e){status.textContent=old;showModal('下载失败：'+e.message);});
}

// --- boot ---
document.getElementById('clockTime').textContent=new Date().toLocaleTimeString();
setInterval(function(){document.getElementById('clockTime').textContent=new Date().toLocaleTimeString()},1000);
switchTab(document.querySelector('.tabs .tab').dataset.tab);
document.querySelectorAll('.tabs .tab').forEach(function(t){t.setAttribute('role','tab');t.setAttribute('tabindex','0');t.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();switchTab(t.dataset.tab);}});});
document.querySelectorAll('.refresh:not(.no-spin)').forEach(function(el){el.addEventListener('click',function(){el.classList.remove('spinning');void el.offsetWidth;el.classList.add('spinning');setTimeout(function(){el.classList.remove('spinning');},800);});});
// ESC closes whichever modal is visible (content/global/confirm)
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){
    var m=document.getElementById('contentModal');
    if(m&&m.style.display==='flex'){closeContentModal();return;}
    var g=document.getElementById('globalModal');
    if(g&&g.style.display==='flex'){closeGlobalModal();return;}
    var c=document.getElementById('confirmModal');
    if(c&&c.style.display==='flex'){c.style.display='none';}
  }
});
// a11y: label refresh buttons so screen readers announce intent,
// not the raw '↻' pseudo-element content of hidden tabs
document.querySelectorAll('.refresh').forEach(function(el){el.setAttribute('aria-label','刷新');});

// --- flagging ---
// flagJob(jobId, 'clear') POSTs flag=clear; the API returns flag='' (empty
// string). The previous code did `j.user_flag=(d.flag||flag)` -- when d.flag
// is '' (falsy) it fell back to the literal 'clear', leaving the cell showing
// the ❌-style branch. Normalize so an empty server flag maps to '' client-side.
function flagJob(jobId,flag){
  fetch('/api/flag/'+encodeURIComponent(jobId)+'?flag='+encodeURIComponent(flag),{method:'POST'})
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){
      loadJobs(jobsPage);
    }
  });
}
function toggleFlag(jobId){
  var job=allJobs.find(function(j){return j.id===jobId});
  var cur=job?job.user_flag:'';
  // 3-state cycle: '' -> 'rejected' -> 'interested' -> '' (clear).
  // Without a clear path back to '' the user can never un-flag a job from
  // the table cell (the legend says "点击文字即可切换" which implies a full cycle).
  var next = cur==='rejected' ? 'interested' : cur==='interested' ? 'clear' : 'rejected';
  flagJob(jobId,next);
}

// --- batch flag ---
function updateSelCount(){
  var cbs=document.querySelectorAll('.job-cb:checked');
  document.getElementById('selCount').textContent=cbs.length;
  updateJobsActions();
}
function toggleSelectAll(master){
  document.querySelectorAll('.job-cb').forEach(function(cb){cb.checked=master.checked});
  updateSelCount();
}
function batchFlag(){
  var cbs=Array.from(document.querySelectorAll('.job-cb:checked'));
  var ids=cbs.map(function(cb){return cb.value});
  if(!ids.length){showModal('提示：请先勾选岗位');return}
  var flag=document.getElementById('batchFlagSel').value;
  if(!flag){showModal('请选择批量操作类型');return}
  showConfirm('确定对 '+ids.length+' 条岗位执行「'+(flag==='interested'?'批量标记 🌟':flag==='rejected'?'批量标记 ❌':'批量清除标记')+'」？',function(){
  // optimistic: update local state immediately and re-render so the UI
  // feels instant; the network calls happen concurrently below.
  ids.forEach(function(id){
    var j=allJobs.find(function(x){return x.id===id});
    if(j)j.user_flag=(flag==='clear')?'':flag;
  });
  renderJobs();
  // Send all IDs in one batch request (single SQLite transaction
  // instead of N individual connections). Eliminates the lag from
  // firing 50+ concurrent POSTs.
  fetch('/api/flag/batch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ids:ids,flag:flag})})
  .then(function(r){return r.json()})
  .then(function(d){
    cbs.forEach(function(cb){cb.checked=false});
    document.getElementById('selectAll').checked = false;
    updateSelCount();
    if(!d.ok){
      showModal('批量标记失败，已重载列表');
    }
    // Reload from server so the current filter (e.g. "未标记") is re-applied,
    // hiding jobs that just got flagged as interested/rejected.
    loadJobs(jobsPage);
  }).catch(function(){
    showModal('批量标记请求失败，已重载列表');
    loadJobs(jobsPage);
  });
  });
}

// --- run match (精排, progress modal) ---
var _matchPollTimer=null;
function _showMatchProgressModal(wanted){
  var body='<div style="font-size:.9rem;margin-bottom:10px">将对 <b>'+wanted+'</b> 个 🌟 想投递岗位调用 LLM 做深度匹配（岗位较多时可能耗时较久，请耐心等待）</div>';
  body+='<div style="background:var(--card);border-radius:6px;padding:10px;margin-bottom:8px">';
  body+='<div style="display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:4px"><span id="matchProgText">准备开始…</span><span id="matchProgPct">0%</span></div>';
  body+='<div style="height:8px;background:#eee;border-radius:4px;overflow:hidden"><div id="matchProgBar" style="height:100%;width:0%;background:var(--accent);transition:width .3s"></div></div>';
  body+='<div id="matchProgCur" style="font-size:.78rem;color:var(--muted);margin-top:6px"></div>';
  body+='</div>';
  body+='<div style="display:flex;gap:8px;justify-content:flex-end">';
  body+='<button id="matchStartBtn" onclick="matchStartRun()" style="background:var(--accent);color:#fff;border:none;padding:7px 18px;border-radius:6px;cursor:pointer;font-weight:600">▶ 开始精排</button>';
  body+='</div>';
  showContentModal('🧠 精排进度',body);
}
function runMatch(){
  var btn=document.getElementById('runMatchBtn');
  var _selJobs=document.querySelectorAll('.job-cb:checked');
  if(!_selJobs.length){showModal('提示：请先勾选职位后再进行精排');return;}
  var wanted=allJobs.filter(function(j){return j.user_flag==='interested'}).length;
  if(!wanted){showModal('提示：没有标记为 🌟 想投递的岗位');return;}
  _showMatchProgressModal(wanted);
}
function matchStartRun(){
  var sb=document.getElementById('matchStartBtn');
  if(sb){sb.disabled=true;sb.textContent='精排中…'}
  var btn=document.getElementById('runMatchBtn');
  _matchStartPolling();
  fetch('/api/match/run',{method:'POST'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(_matchPollTimer){clearInterval(_matchPollTimer);_matchPollTimer=null}
      if(btn){btn.disabled=false;btn.innerHTML='🧠 精排'}
      if(d&&d.ok){
        var flagged=d.flagged||0, matched=d.matched||0, skipped=d.skipped||0;
        var msg='<div style="font-size:1rem;line-height:1.8;white-space:pre-wrap">✅ 精排完成\n\n';
        msg+='🌟 标记岗位：'+flagged+' 条\n';
        msg+='🎯 匹配通过：'+matched+' 条\n';
        if(skipped>0)msg+='⚠️ 解析失败：'+skipped+' 条\n';
        if(matched===0){
          msg+='\n💡 当前没有岗位达到分数阈值（默认 50 分）。\n已切换到「全部分数」视图。';
          var sel=document.getElementById('matchMinScore');
          if(sel)sel.value='0';
        }else{
          msg+='\n已跳转到匹配结果列表。';
        }
        msg+='</div>';
        showContentModal('✅ 精排完成',msg);
        switchTab('match');
        loadMatch(1);
      }else{
        showContentModal('精排失败','<div style="font-size:.9rem">'+(d&&d.message||'未知错误')+'</div>');
      }
    })
    .catch(function(e){
      if(_matchPollTimer){clearInterval(_matchPollTimer);_matchPollTimer=null}
      if(btn){btn.disabled=false;btn.innerHTML='🧠 精排'}
      showContentModal('精排请求失败','<div style="font-size:.9rem">'+e.message+'</div>');
    });
}
function _matchPoll(){
  fetch('/api/match/progress',{method:'GET'}).then(function(r){return r.json()}).then(function(p){
    if(!p)return;
    var t=document.getElementById('matchProgText'),b=document.getElementById('matchProgBar'),
        c=document.getElementById('matchProgPct'),cur=document.getElementById('matchProgCur');
    if(!t||!b)return;
    var total=p.total||1, done=p.done||0, pct=Math.round(done/total*100);
    b.style.width=pct+'%';c.textContent=pct+'%';
    t.textContent=p.status||('已完成 '+done+'/'+total);
    if(cur)cur.textContent=(p.current||'');
    if(p.running===false&&done>=total){if(_matchPollTimer){clearInterval(_matchPollTimer);_matchPollTimer=null}}
  }).catch(function(){});
}
function _matchStartPolling(){
  if(_matchPollTimer)clearInterval(_matchPollTimer);
  _matchPollTimer=setInterval(_matchPoll,500);
  _matchPoll();
}

// --- fetch JD for flagged jobs (progress modal) ---
var _jdPollTimer=null;
function _showJdProgressModal(wanted){
  var body='<div style="font-size:.9rem;margin-bottom:10px">将对 <b>'+wanted+'</b> 个 🌟 想投递岗位抓取 JD（可能触发平台反爬，请耐心等待）</div>';
  body+='<div style="background:var(--card);border-radius:6px;padding:10px;margin-bottom:8px">';
  body+='<div style="display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:4px"><span id="jdProgText">准备开始…</span><span id="jdProgPct">0%</span></div>';
  body+='<div style="height:8px;background:#eee;border-radius:4px;overflow:hidden"><div id="jdProgBar" style="height:100%;width:0%;background:var(--accent);transition:width .3s"></div></div>';
  body+='<div id="jdProgCur" style="font-size:.78rem;color:var(--muted);margin-top:6px"></div>';
  body+='</div>';
  body+='<div style="display:flex;gap:8px;justify-content:flex-end">';
  body+='<button id="jdStartBtn" onclick="jdStartFetch()" style="background:var(--accent);color:#fff;border:none;padding:7px 18px;border-radius:6px;cursor:pointer;font-weight:600">▶ 开始抓取</button>';
  body+='</div>';
  showContentModal('📄 抓取 JD 进度',body);
}
function fetchJDForFlagged(){
  var btn=document.getElementById('fetchJDBtn');
  var _selJobs=document.querySelectorAll('.job-cb:checked');
  if(!_selJobs.length){showModal('提示：请先勾选职位后再抓取JD');return;}
  // 抓取实际作用于 🌟 想投递岗位（后端只查 user_flag='interested'）
  var wanted=allJobs.filter(function(j){return j.user_flag==='interested'}).length;
  if(!wanted){showModal('提示：没有标记为 🌟 想投递的岗位');return;}
  _showJdProgressModal(wanted);
}
function jdStartFetch(){
  var sb=document.getElementById('jdStartBtn');
  if(sb){sb.disabled=true;sb.textContent='抓取中…'}
  var btn=document.getElementById('fetchJDBtn');
  _jdStartPolling();
  fetch('/api/jd/fetch',{method:'POST'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(_jdPollTimer){clearInterval(_jdPollTimer);_jdPollTimer=null}
      if(btn){btn.disabled=false;btn.innerHTML='📄 抓取JD'}
      if(d&&d.ok){
        var fetched=d.fetched||0, skipped=d.skipped||0, failed=d.failed||0;
        showContentModal('✅ JD抓取完成','<div style="font-size:1rem;line-height:1.8;white-space:pre-wrap">已抓取：'+fetched+' 条\n跳过(已有JD)：'+skipped+' 条\n失败：'+failed+' 条</div>');
        loadJobs(1);
      }else{
        showContentModal('JD抓取失败','<div style="font-size:.9rem">'+(d&&d.error||'未知错误')+'</div>');
      }
    })
    .catch(function(e){
      if(_jdPollTimer){clearInterval(_jdPollTimer);_jdPollTimer=null}
      if(btn){btn.disabled=false;btn.innerHTML='📄 抓取JD'}
      showContentModal('JD抓取请求失败','<div style="font-size:.9rem">'+e.message+'</div>');
    });
}
function _jdPoll(){
  fetch('/api/jd/progress',{method:'GET'}).then(function(r){return r.json()}).then(function(p){
    if(!p)return;
    var t=document.getElementById('jdProgText'),b=document.getElementById('jdProgBar'),
        c=document.getElementById('jdProgPct'),cur=document.getElementById('jdProgCur');
    if(!t||!b)return;
    var total=p.total||1, done=p.done||0, pct=Math.round(done/total*100);
    b.style.width=pct+'%';c.textContent=pct+'%';
    t.textContent=p.status||('已完成 '+done+'/'+total);
    if(cur)cur.textContent=(p.current||'');
    if(p.running===false&&done>=total){if(_jdPollTimer){clearInterval(_jdPollTimer);_jdPollTimer=null}}
  }).catch(function(){});
}
function _jdStartPolling(){
  if(_jdPollTimer)clearInterval(_jdPollTimer);
  _jdPollTimer=setInterval(_jdPoll,500);
  _jdPoll();
}

// --- 查看 JD（想投递岗位的全部 JD）+ 人工导入 ---
var _BAD_JD_MARKERS=['正在验证连接安全性','验证码','安全验证','访问过于频繁','请稍后重试','您已被限制','human verification','captcha','Protected by'];
function _jdIsAntiBot(jd){
  if(!jd)return false;
  var l=jd.toLowerCase();
  for(var i=0;i<_BAD_JD_MARKERS.length;i++){if(l.indexOf(_BAD_JD_MARKERS[i].toLowerCase())>=0)return true}
  return false;
}
function viewJDForFlagged(){
  var btn=document.getElementById('viewJDBtn');
  var orig=btn?btn.innerHTML:'';
  if(btn){btn.disabled=true;btn.innerHTML='⏳ 加载中…';btn.style.opacity='.7'}
  fetch('/api/jd/view',{method:'GET'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(btn){btn.disabled=false;btn.innerHTML=orig;btn.style.opacity='1'}
      if(!(d&&d.ok)){showModal('查看JD失败：'+(d&&d.message||'未知错误'));return}
      var jobs=d.jobs||[];
      if(!jobs.length){showModal('提示：没有标记为 🌟 想投递的岗位');return}
      var h='<div id="jdListBody" style="max-height:60vh;overflow-y:auto;padding:4px">';
      jobs.forEach(function(j){
        var anti=_jdIsAntiBot(j.jd);
        var antiBadge=anti?'<span id="jdAnti_'+j.id+'" style="background:#c15a3a;color:#fff;padding:1px 8px;border-radius:10px;font-size:.75rem;margin-left:6px">⚠️ 疑似反爬</span>':'';
        h+='<div id="jdCard_'+j.id+'" style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:10px">';
        h+='<div style="font-weight:700;font-size:.95rem">'+escHtml(j.company)+' · '+escHtml(j.title)+antiBadge+'</div>';
        h+='<div id="jdText_'+j.id+'" style="background:var(--card);border-radius:6px;padding:8px;margin:8px 0;white-space:pre-wrap;font-size:.82rem;max-height:200px;overflow-y:auto;color:var(--text)">'+escHtml(j.jd||'（无 JD 内容）')+'</div>';
        h+='<button data-act="manualJd" data-id="'+j.id+'" data-name="'+escHtml(j.company+' '+j.title)+'" style="background:var(--accent);color:#fff;border:none;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.8rem">📥 导入JD</button>';
        h+='</div>';
      });
      h+='</div>';
      showContentModal('📄 想投递岗位的 JD（'+jobs.length+' 个）',h);
    })
    .catch(function(e){
      if(btn){btn.disabled=false;btn.innerHTML=orig;btn.style.opacity='1'}
      showModal('查看JD请求失败：'+e.message);
    });
}
function manualImportJD(jobId,jobName){
  var cur='';
  // 预填现有 JD（若有）
  fetch('/api/jd/view',{method:'GET'}).then(function(r){return r.json()}).then(function(d){
    if(d&&d.ok){var j=d.jobs.filter(function(x){return x.id===jobId})[0];if(j)cur=j.jd||''}
    _showImportModal(jobId,jobName,cur);
  }).catch(function(){_showImportModal(jobId,jobName,'')});
}
function _showImportModal(jobId,jobName,cur){
  // 独立 overlay 浮在查看JD弹窗之上 —— 不动 contentModal，保留滚动位置
  var ov=document.getElementById('jdImportOverlay');
  if(!ov){
    ov=document.createElement('div');
    ov.id='jdImportOverlay';
    document.body.appendChild(ov);
  }
  var body='<div style="font-size:.9rem;margin-bottom:8px">为 <b>'+escHtml(jobName)+'</b> 导入真实 JD（将覆盖现有内容）</div>';
  body+='<textarea id="manualJdInput" rows="12" style="width:100%;box-sizing:border-box;font-family:inherit;font-size:.85rem;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text)">'+escHtml(cur)+'</textarea>';
  body+='<div style="display:flex;gap:8px;margin-top:10px;justify-content:flex-end">';
  body+='<button onclick="cancelImportJd()" style="background:var(--card);color:var(--text);border:1px solid var(--border);padding:7px 16px;border-radius:6px;cursor:pointer">取消</button>';
  body+='<button id="manualJdSaveBtn" onclick="saveManualJd(\''+jobId+'\')" style="background:var(--accent);color:#fff;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-weight:600">💾 保存导入</button>';
  body+='</div>';
  ov.innerHTML='<div style="position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px">'
    +'<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;max-width:720px;width:95%;box-shadow:0 12px 40px rgba(0,0,0,.25)">'
    +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border)"><b style="font-size:1rem">📥 导入真实 JD</b>'
    +'<button onclick="cancelImportJd()" style="background:transparent;border:none;font-size:1.2rem;cursor:pointer;color:var(--muted);line-height:1">✕</button></div>'
    +body
    +'</div></div>';
  ov.style.display='block';
  document.getElementById('manualJdSaveBtn').focus();
}
function saveManualJd(jobId){
  var input=document.getElementById('manualJdInput');
  var jd=(input&&input.value||'').trim();
  if(!jd){showModal('提示：请粘贴 JD 内容');return}
  var btn=document.getElementById('manualJdSaveBtn');
  if(btn){btn.disabled=true;btn.textContent='保存中…'}
  fetch('/api/jd/manual',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({job_id:jobId,jd:jd})})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d&&d.ok){
        var jdTextEl=document.getElementById('jdText_'+jobId);
        if(jdTextEl){jdTextEl.textContent=jd;}
        var antiEl=document.getElementById('jdAnti_'+jobId);
        if(antiEl){antiEl.style.display='none';}
        cancelImportJd();
        showModal('✅ '+d.message);
        loadJobs(1);
      }else{
        if(btn){btn.disabled=false;btn.textContent='💾 保存导入'}
        showModal('导入失败：'+(d&&d.message||'未知错误'));
      }
    })
    .catch(function(e){
      if(btn){btn.disabled=false;btn.textContent='💾 保存导入'}
      showModal('导入请求失败：'+e.message);
    });
}
function cancelImportJd(){
  // 移除导入 overlay → 查看JD弹窗（含滚动位置）原封不动保留
  var ov=document.getElementById('jdImportOverlay');
  if(ov)ov.style.display='none';
}
function closeModal(){
  var m=document.getElementById('contentModal');
  if(m)m.style.display='none';
  var m2=document.getElementById('globalModal');
  if(m2)m2.style.display='none';
}

// --- resume panel (独立 tab) ---
function onResumeFilePicked(input){
  var files=input.files;
  if(!files||!files.length)return;
  var status=document.getElementById('resumeStatus');
  var queue=Array.prototype.slice.call(files);
  var idx=0,total=queue.length,okCount=0,failCount=0;
  function uploadNext(){
    if(idx>=queue.length){
      if(status){status.textContent='✅ 批量上传完成：'+okCount+'/'+total+' 成功'+(failCount?(' · '+failCount+' 失败'):'')}
      _invalidateUploadCache('resumes');loadResumes();input.value='';return;
    }
    var file=queue[idx];idx++;
    if(file.size>5*1024*1024){if(status){status.textContent='⏭ 跳过过大文件：'+file.name};failCount++;uploadNext();return}
    var reader=new FileReader();
    reader.onload=function(e){
      var content=e.target.result||'';
      var name=file.name||'resume.txt';
      if(status){status.textContent='上传中… ('+idx+'/'+total+') '+name}
      fetch('/api/resume/upload',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:name,content:content,set_default:false})})
        .then(function(r){return r.json()})
        .then(function(d){if(d&&d.ok){okCount++}else{failCount++}})
        .catch(function(){failCount++})
        .finally(uploadNext);
    };
    reader.onerror=function(){failCount++;uploadNext()};
    reader.readAsText(file,'utf-8');
  }
  uploadNext();
}
function loadResumes(){
  var seq=++_uploadSeq;
  var tb0=document.getElementById('resumeTb');if(!tb0)return;
  // 缓存优先：先渲染缓存（秒开），后台静默刷新
  if(_uploadCache&&_uploadCache.resumes){
    _renderResumes(_uploadCache.resumes.items,_uploadCache.resumes.default);
  }
  fetch('/api/resumes').then(function(r){return r.json()}).then(function(d){
    if(seq!==_uploadSeq)return; // 过期响应丢弃
    _uploadCache.resumes={items:d.items||[],default:d.default};
    if(document.getElementById('uploadTypeSel').value==='resume'){
      _renderResumes(d.items||[],d.default);
    }
  }).catch(function(){});
}
function _renderResumes(items,def){
  var tb=document.getElementById('resumeTb');
  var empty=document.getElementById('resumeEmpty');
  if(!tb)return;
  if(!items.length){
    tb.innerHTML='';
    if(empty){empty.style.display='block';empty.textContent='📭 暂无简历，点击上方「文件上传」添加'}
    return;
  }
  if(empty){empty.style.display='none'}
  tb.innerHTML=items.map(function(r){
    var isDef=(r.name===def);
    var sz=r.size>1024?(r.size/1024).toFixed(1)+' KB':r.size+' B';
    var mt=new Date(r.mtime*1000);
    var mtStr=mt.getFullYear()+'-'+_pad(mt.getMonth()+1)+'-'+_pad(mt.getDate())+' '+_pad(mt.getHours())+':'+_pad(mt.getMinutes());
    var defTag=isDef?'<span style="color:var(--accent);font-weight:700">⭐ 默认</span>':'<span style="color:var(--muted)">--</span>';
    var enc=encodeURIComponent(r.name);
    var actions='<div class="row-actions">'
      +'<button data-act="setDef" data-name="'+enc+'" '+(isDef?'disabled style="opacity:.4;cursor:not-allowed"':'')+' class="pgn-btn" style="font-size:.72rem">设为默认</button>'
      +'<button data-act="preview" data-name="'+enc+'" class="pgn-btn" style="font-size:.72rem">👁 预览</button>'
      +'<button data-act="del" data-name="'+enc+'" class="pgn-btn" style="font-size:.72rem;color:#c15a3a">🗑 删除</button></div>';
    return '<tr><td><input type="checkbox" class="res-ck" value="'+encodeURIComponent(r.name)+'"></td><td style="font-weight:'+(isDef?'700':'400')+'">📄 '+escHtml(r.name)+'</td><td>'+sz+'</td><td style="font-size:.75rem;color:var(--muted)">'+mtStr+'</td><td>'+defTag+'</td><td>'+actions+'</td></tr>';
  }).join('');
}
function _invalidateUploadCache(t){if(!t){_uploadCache.resumes=null;_uploadCache.offers=null;}else{_uploadCache[t]=null;}}
function switchUploadList(){var ut=document.getElementById('uploadTypeSel');var v=ut?ut.value:'resume';var ur=document.getElementById('usageResume');var uo=document.getElementById('usageOffer');if(ur)ur.style.display=(v==='offer')?'none':'';if(uo)uo.style.display=(v==='offer')?'':'none';if(v==='offer')loadOfferListInUploadTab();else loadResumes();}
function loadOfferListInUploadTab(){
  var seq=++_uploadSeq;
  var tb0=document.getElementById('resumeTb');if(!tb0)return;
  // 缓存优先：先渲染缓存（秒开），后台静默刷新
  if(_uploadCache&&_uploadCache.offers){
    _renderOffers(_uploadCache.offers);
  }
  fetch('/api/offer/list').then(function(r){return r.json()}).then(function(d){
    if(seq!==_uploadSeq)return; // 过期响应丢弃
    _uploadCache.offers=d.items||[];
    if(document.getElementById('uploadTypeSel').value==='offer'){
      _renderOffers(d.items||[]);
    }
  }).catch(function(){});
}
function _renderOffers(items){
  var tb=document.getElementById('resumeTb');var empty=document.getElementById('resumeEmpty');
  if(!tb)return;
  if(!items.length){tb.innerHTML='';if(empty){empty.style.display='block';empty.innerHTML='<div class="empty-state" style="padding:26px 16px"><span class="empty-ico">📭</span><div class="empty-title">暂无 Offer 文件</div><div class="empty-hint">类型选 Offer 后点「文件上传」添加。</div></div>';}return;}
  if(empty){empty.style.display='none';}
  tb.innerHTML=items.map(function(o){
    var sz=o.size>1024?(o.size/1024).toFixed(1)+' KB':o.size+' B';
    var mt=new Date(o.mtime*1000);
    var mtStr=mt.getFullYear()+'-'+_pad(mt.getMonth()+1)+'-'+_pad(mt.getDate())+' '+_pad(mt.getHours())+':'+_pad(mt.getMinutes());
    var st=o.evaluated?('✅ '+(o.overall_score!=null?o.overall_score:'已评估')):'<span style="color:var(--muted)">未评估</span>';
    var nameText=escHtml(o.name);
    var enc=encodeURIComponent(o.name);
    var actions='<div class="row-actions">'
      +'<button data-act="previewOffer" data-name="'+enc+'" class="pgn-btn" style="font-size:.72rem">👁 预览</button>'
      +'<button data-act="delOffer" data-name="'+enc+'" class="pgn-btn" style="font-size:.72rem;color:#c15a3a">🗑 删除</button></div>';
    return '<tr><td><input type="checkbox" class="offer-ck" value="'+escAttr(o.name)+'"></td><td>📄 '+nameText+'</td><td>'+sz+'</td><td style="font-size:.75rem;color:var(--muted)">'+mtStr+'</td><td style="font-size:.78rem">'+st+'</td><td>'+actions+'</td></tr>';
  }).join('');
}
function previewOfferFile(encName){
  var name=decodeURIComponent(encName);
  fetch('/api/offer/preview?file_name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
    showContentModal('📄 '+name,'<pre style="white-space:pre-wrap;font-size:.82rem;line-height:1.7;margin:0">'+escHtml(d.raw_text||d.content||'')+'</pre>');
  }).catch(function(e){showModal('预览失败：'+e.message);});
}
function uploadBatchDelete(){var ut=document.getElementById('uploadTypeSel');var v=ut?ut.value:'resume';if(v==='offer')batchDeleteOffersInUpload();else batchDeleteResumes();}
function batchDeleteOffersInUpload(){
  var names=_checkedOfferNamesInUpload();if(!names.length){showModal('提示：请先勾选要删除的 Offer');return;}
  showConfirm('确定删除选中的 '+names.length+' 个 Offer？评估缓存也会清除。',function(){
    var i=0,ok=0,fail=0;
    function next(){
      if(i>=names.length){showModal('✅ 删除完成：'+ok+' 个'+(fail?('，失败 '+fail):''));_invalidateUploadCache('offers');loadOfferListInUploadTab();loadOfferTable();return;}
      var n=names[i];i++;
      fetch('/api/offer?file_name='+encodeURIComponent(n),{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok)ok++;else fail++;}).catch(function(){fail++;}).finally(next);
    }
    next();
  });
}
function uploadToggleAll(src){var ut=document.getElementById('uploadTypeSel');var v=ut?ut.value:'resume';var sel=v==='offer'?'#resumeTb .offer-ck':'.res-ck';document.querySelectorAll(sel).forEach(function(c){c.checked=src.checked});}
function resToggleAll(src){document.querySelectorAll('.res-ck').forEach(function(c){c.checked=src.checked});}
function batchDeleteResumes(){
  var names=[];document.querySelectorAll('.res-ck:checked').forEach(function(c){names.push(c.value)});
  if(!names.length){showModal('提示：请先勾选要删除的简历');return;}
  showConfirm('确定删除选中的 '+names.length+' 份简历？此操作不可恢复。',function(){
    Promise.all(names.map(function(n){return fetch('/api/resume?name='+n,{method:'DELETE'}).then(function(r){return r.json()})}))
      .then(function(){showModal('删除完成');loadResumes();var sa=document.querySelector('#resume-panel thead input[type=checkbox]');if(sa)sa.checked=false;})
      .catch(function(e){showModal('删除失败：'+e.message)});
  });
}
function _pad(n){return n<10?'0'+n:''+n}
// 上传页按钮 + 人工筛选标记事件委托（data-act 统一分发，避免内联 onclick 引号转义问题）
document.addEventListener('click', function(ev){
  var btn=ev.target.closest('button[data-act]')||ev.target.closest('span[data-act]')||ev.target.closest('a[data-act]');
  if(!btn)return;
  var act=btn.getAttribute('data-act');
  var name=btn.getAttribute('data-name');
  if(act==='setDef')setDefResume(name);
  else if(act==='preview')previewResume(name);
  else if(act==='del')deleteResume(name);
  else if(act==='previewOffer')previewOfferFile(name);
  else if(act==='delOffer')deleteOfferFile(name);
  else if(act==='evalOffer')evalOfferRow(name);
  else if(act==='previewOfferRes')previewOfferRow(name);
  else if(act==='delOfferFile')deleteOfferFile(name);
  else if(act==='saveOffer')saveOfferReport(name);
  else if(act==='flag')toggleFlag(btn.getAttribute('data-id'));
  else if(act==='delApp')deleteApp(btn.getAttribute('data-id'));
  else if(act==='regenMat')regenMaterial(btn.getAttribute('data-id'));
  else if(act==='confirmMat')confirmMaterial(btn.getAttribute('data-id'));
  else if(act==='fb')matchFeedback(btn.getAttribute('data-id'),btn.getAttribute('data-type'),ev);
  else if(act==='manualJd')manualImportJD(btn.getAttribute('data-id'),btn.getAttribute('data-name'));
  else if(act==='viewEval'){var ep=_endProgress&&_endProgress.names?_endProgress.names.assessment:'';if(ep)previewFile(ep);}
  else if(act==='viewMd'){var ep2=_endProgress&&_endProgress.names?_endProgress.names.md:'';if(ep2)previewFile(ep2);}
});
// 投递追踪行内状态下拉（select change 分发）
document.addEventListener('change', function(ev){
  var sel=ev.target.closest('select[data-act="appStatus"]');
  if(!sel)return;
  updateAppStatus(sel.getAttribute('data-id'),sel.value);
});
function setDefResume(encName){
  var name=decodeURIComponent(encName);
  fetch('/api/resume/default',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name})})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d&&d.ok){_invalidateUploadCache('resumes');loadResumes()}
      else{showModal('设置失败：'+(d&&d.error||'未知错误'))}
    }).catch(function(e){showModal('请求失败：'+e.message)});
}
function previewResume(encName){
  var name=decodeURIComponent(encName);
  fetch('/api/resume/preview?name='+encName).then(function(r){return r.json()})
    .then(function(d){
      if(d&&d.ok){showContentModal('📄 '+(d.name||name)+' ('+d.size+' 字符)','<pre style="white-space:pre-wrap;font-size:.82rem;line-height:1.7;margin:0">'+escHtml(d.content||'')+'</pre>');}
      else{showModal('预览失败：'+(d&&d.error||'未知错误'));}
    }).catch(function(e){showModal('请求失败：'+e.message)});
}
function deleteResume(encName){
  var name=decodeURIComponent(encName);
  showConfirm('确定删除简历「'+name+'」？此操作不可恢复。',function(){
    fetch('/api/resume?name='+encName,{method:'DELETE'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d&&d.ok){
        var wrap=document.getElementById('resumePreview');
        if(wrap){wrap.style.display='none'}
        _invalidateUploadCache('resumes');loadResumes();
      }else{showModal('删除失败：'+(d&&d.error||'未知错误'))}
    }).catch(function(e){showModal('请求失败：'+e.message)});
});
}
// --- assistant bubble factory ---
// --- send/pause button state machine (DeepSeek-style) ---
// Regenerate the LAST assistant reply: drop it + its user prompt from
// --- mock interview panel (Stage 3: Dashboard online + SSE) ---
var mockSession={id:null,active:false};
function loadMockJobs(){
  fetch('/api/materials/jobs').then(function(r){return r.json()}).then(function(d){
    var sel=document.getElementById('mockJobSel');var cur=sel.value;
    sel.innerHTML='<option value="">选择职位...</option>';
    var items=Array.isArray(d)?d:(d.items||[]);
    items.forEach(function(j){var o=document.createElement('option');o.value=j.id;o.textContent=(j.title||'')+' @ '+(j.company||'');sel.appendChild(o);});
    if(cur)sel.value=cur;
    updateMockControls();
  }).catch(function(){});
}
function setMockInputEnabled(en){
  document.getElementById('mockInput').disabled=!en;
  document.getElementById('mockSendBtn').disabled=!en||!document.getElementById('mockInput').value.trim();
  var mb=document.getElementById('mockMicBtn');if(mb)mb.disabled=!en;
  setMockPlaceholder();
  if(en)document.getElementById('mockInput').focus();
}
function _mockShowPlaceholder(){
  var box=document.getElementById('mockChat');if(!box)return;
  box.innerHTML='👋 还没有面试记录，从上方选择职位开始一次模拟面试';
  box.style.display='flex';box.style.justifyContent='center';box.style.alignItems='center';
}
function _mockClearPlaceholder(){
  var box=document.getElementById('mockChat');if(!box)return;
  // 2026-08-12 fix: placeholder text starts with '👋 ', so indexOf(...)===0 never
  // matched and the placeholder was never cleared. Use >=0 (substring check).
  if(box.innerHTML.indexOf('还没有面试记录')>=0){box.innerHTML='';}
  box.style.display='';box.style.justifyContent='';box.style.alignItems='';
}
function addMockBubble(who,text){
  var box=document.getElementById('mockChat');var b=document.createElement('div');
  _mockClearPlaceholder();
  // 2026-08-12 fix: align-self:flex-start prevents the flex container (align-items
  // falls back to stretch after placeholder clear) from stretching bubbles full-width;
  // text-align:left keeps bubble text left-aligned per user request.
  b.style.cssText='margin:6px 0;padding:8px 12px;border-radius:8px;max-width:75%;white-space:pre-wrap;word-break:break-word;line-height:1.5;text-align:left;align-self:flex-start';
  if(who==='user'){b.style.background='var(--accent)';b.style.color='#fff';b.style.marginLeft='auto';}
  else{b.style.background='var(--bg)';b.style.border='1px solid var(--border)';}
  b.textContent=text||'';
  box.appendChild(b);box.scrollTop=box.scrollHeight;
  updateMockClearButton();
  return b;
}
function scrollMockDown(){var box=document.getElementById('mockChat');box.scrollTop=box.scrollHeight;}
function clearMockPanel(){
  // 有进行中会话时先确认：清空会丢弃进度且不生成记录。
  var hasActive = mockSession.active || (typeof rtWs!=='undefined' && rtWs && rtWs.readyState===1);
  var doClear=function(){
    if(mockMicOn){try{mockSTT&&mockSTT.stop();}catch(e){}mockMicOn=false;document.getElementById('mockMicBtn').textContent='🎤';sttFinal='';sttDone=0;}
    try{speechSynthesis&&speechSynthesis.cancel();}catch(e){}
    mockSession={id:null,active:false};
    mockLastJobId=null;mockLastMode=null;rtModeOverride='text';
    _rtGenerating=false;rtEndByUser=false;_endProgress=null;_oggChunks=[];_oggCollecting=false;
    if(typeof rtWs!=='undefined'&&rtWs){try{rtWs.close();}catch(e){}rtWs=null;}
    _mockShowPlaceholder();
    var st=document.getElementById('mockStatus');if(st)st.textContent='';
    var inp=document.getElementById('mockInput');if(inp){inp.value='';inp.disabled=true;inp.style.height='38px';}
    var sb=document.getElementById('mockSendBtn');if(sb)sb.disabled=true;
    var eb=document.getElementById('mockEndBtn');if(eb)eb.disabled=true;
    var dl=document.getElementById('mockDlBtn');if(dl)dl.disabled=true;
    var mb=document.getElementById('mockMicBtn');if(mb)mb.disabled=true;
    var js=document.getElementById('mockJobSel');if(js)js.value='';
    var fp=document.getElementById('mockFromPrep');if(fp)fp.checked=false;
    var fc=document.getElementById('mockFocus');if(fc)fc.value='';
    var df=document.getElementById('mockDifficulty');if(df)df.value='easy';
    var ms=document.getElementById('mockModeSel');if(ms)ms.value='text';
    var tt=document.getElementById('mockTTS');if(tt)tt.checked=false;
    setMockPlaceholder();updateMockHint();
    setMockStartState(false);
    lockMockConfig(false);
  };
  if(hasActive){
    showConfirm('清空将丢弃当前面试进度，不生成记录。确定清空吗？', function(){
      if(mockSession.id && mockSession.id!=='realtime'){
        fetch('/api/mock-interview/abandon',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:mockSession.id})}).catch(function(){});
      }
      if(typeof rtWs!=='undefined' && rtWs && rtWs.readyState===1){
        try{rtWs.send(JSON.stringify({type:'abandon'}));}catch(e){}
      }
      doClear();
    });
  } else {
    doClear();
  }
}
// --- Realtime voice interview (SC2.0 via WS proxy) ---
var rtConfig={enabled:false,ws_port:8766};
var rtWs=null,rtAudioCtx=null,rtMicStream=null,rtProcessor=null,rtPlayCtx=null;
var _rtGenerating=false;  // 2026-08-12: WS 断开时保留"正在生成"提示（generating 后断开不显示"连接断开"）
var _rtEnded=false;   // 2026-08-16: ended 已处理时，onclose 不得覆盖完成状态
var rtMicOn=false;
var rtEndByUser=false;
function updateMockClearButton(){
  // 清空按钮只在“确实有东西可清”时可用：已选职位/非默认配置/会话/聊天记录/结果。
  var cb=document.getElementById('mockClearBtn');if(!cb)return;
  var busy=mockSession.active||(typeof rtWs!=='undefined'&&rtWs&&(rtWs.readyState===0||rtWs.readyState===1));
  var js=document.getElementById('mockJobSel');
  var box=document.getElementById('mockChat');
  var dirty=busy
    || !!(js&&js.value)
    || !!((document.getElementById('mockFromPrep')||{}).checked)
    || ((document.getElementById('mockFocus')||{}).value||'')!==''
    || ((document.getElementById('mockDifficulty')||{}).value||'easy')!=='easy'
    || ((document.getElementById('mockModeSel')||{}).value||'text')!=='text'
    || !!((document.getElementById('mockTTS')||{}).checked)
    || !!mockLastJobId
    || !!_endProgress
    || !!(box&&box.querySelector('div'));
  cb.disabled=!dirty;
}
function setMockStartState(busy){
  var sb=document.getElementById('mockStartBtn');
  if(sb){
    var js=document.getElementById('mockJobSel');
    sb.disabled=busy||!(js&&js.value);
    sb.textContent=busy?'面试中...':'开始面试';
  }
  updateMockClearButton();
}
function updateMockControls(){
  var busy=mockSession.active||(typeof rtWs!=='undefined'&&rtWs&&(rtWs.readyState===0||rtWs.readyState===1));
  setMockStartState(busy);
}
function lockMockConfig(lock){
  ['mockJobSel','mockFromPrep','mockFocus','mockDifficulty','mockModeSel'].forEach(function(id){
    var el=document.getElementById(id);if(el)el.disabled=lock;
  });
  setMockStartState(lock);
}
var rtModeOverride='text',mockLastJobId=null,mockLastMode=null;
function resolveMockMode(){
  var o=rtModeOverride||'auto';
  if(o==='text')return 'text';
  if(o==='realtime')return rtConfig.enabled?'realtime':null;
  return rtConfig.enabled?'realtime':'text';
}
function updateMockHint(){
  var h=document.getElementById('mockVoiceHint');if(!h)return;
  var mode=resolveMockMode();
  var label=(mode==='realtime')?'实时语音(SC2.0) ✓':'文字面试';
  if(rtModeOverride==='auto')label+=' (自动)';
  else if(mode===null)label='文字面试 (实时未启用)';
  h.textContent='语音: '+label;
}
function onMockModeChange(){
  rtModeOverride=document.getElementById('mockModeSel').value;
  setMockPlaceholder();
  updateMockHint();
  updateMockClearButton();
}
function setMockPlaceholder(){
  var inp=document.getElementById('mockInput');if(!inp)return;
  if(!mockSession.active){inp.placeholder='开始面试后可输入...';return;}
  var mode=resolveMockMode();
  inp.placeholder=(mode==='realtime')?'语音模式中，切到文字可打字':'输入回复后回车发送...';
}
function downloadMockTranscript(){
  if(!mockLastJobId){showModal('暂无可下载的记录');return;}
  window.location.href='/api/mock-interview/latest-transcript?job_id='+encodeURIComponent(mockLastJobId)+'&mode='+(mockLastMode||'realtime');
}
function loadRealtimeConfig(){
  fetch('/api/realtime/config').then(function(r){return r.json()}).then(function(c){rtConfig=c;setMockPlaceholder();updateMockHint();}).catch(function(){});
}
var _rtIdleTimer=null;  // 实时语音空闲提醒计时器（火山 10 分钟无交互会断）
var _RT_IDLE_WARN_MS=8*60*1000;  // 8 分钟提醒（提前于火山 10 分钟断开）
function _rtIdleWarn(){showModal('提示：已 8 分钟没有语音交互，火山语音服务约 10 分钟无对话会自动断开。若还在面试，请点 🎤 开麦说话。');}
function _rtResetIdleTimer(){
  if(_rtIdleTimer){clearTimeout(_rtIdleTimer);}
  _rtIdleTimer=setTimeout(_rtIdleWarn,_RT_IDLE_WARN_MS);
}
function _rtClearIdleTimer(){if(_rtIdleTimer){clearTimeout(_rtIdleTimer);_rtIdleTimer=null;}}
var _rtReversePhase=false;  // 2026-08-16: 反问环节检测（结束语提示）
var _rtReverseHintTimer=null;
var _rtLastMicAt=0;         // 最近一次浏览器上行语音时间
var _rtLastAsrAt=0;         // 最近一次 ASR 返回时间
function _rtClearReverseHint(){
  _rtReversePhase=false;
  if(_rtReverseHintTimer){clearInterval(_rtReverseHintTimer);_rtReverseHintTimer=null;}
}
function _rtEnterReversePhase(){
  _rtReversePhase=true;
  var st=document.getElementById('mockStatus');
  if(st)st.textContent='反问环节：有疑问可直接说；没有请说“没有了”。若说完未结束，可点「结束面试」';
  if(_rtReverseHintTimer)clearInterval(_rtReverseHintTimer);
  _rtReverseHintTimer=setInterval(function(){
    if(_rtEnded||!rtWs||rtWs.readyState!==1){_rtClearReverseHint();return;}
    // 用户开麦说话后 6 秒仍没有 ASR 结果，提示再说一次/手动结束，避免干等
    if(_rtLastMicAt&&performance.now()-_rtLastMicAt>6000&&_rtLastAsrAt<_rtLastMicAt){
      var st2=document.getElementById('mockStatus');
      if(st2)st2.textContent='未听清您的回答：请再说一次“没有了”，或点「结束面试」';
      _rtLastMicAt=0;
    }
  },3000);
}
var _rtFileCheckTimer=null;
var _rtFileCheckTries=0;
function _rtTryCompleteFromFiles(){
  if(_rtEnded||!mockLastJobId)return Promise.resolve(false);
  return fetch('/api/files').then(function(r){return r.json()}).then(function(d){
    var items=d.items||[];
    var md=null,assessment=null;
    items.forEach(function(f){
      if(f.job_id===mockLastJobId&&f.type==='mock_interview'&&f.name&&f.name.indexOf('_realtime_mock')>=0){
        if(f.name.indexOf('_assessment.txt')>=0){assessment=f.name;}
        else if(f.name.toLowerCase().indexOf('.md')>=0){md=f.name;}
      }
    });
    if(!md)return false;
    _rtClearIdleTimer();_rtClearReverseHint();_rtEnded=true;_rtGenerating=false;rtWs=null;stopMicCapture();mockSession={id:null,active:false};setMockInputEnabled(false);document.getElementById('mockEndBtn').disabled=true;document.getElementById('mockStartBtn').disabled=false;lockMockConfig(false);document.getElementById('mockStatus').textContent='✅ 面试结束，记录文件已生成';var dlRt=document.getElementById('mockDlBtn');if(dlRt)dlRt.disabled=false;mockLastMode='realtime';updateEndProgress('done',{md:md,assessment:assessment});return true;
  }).catch(function(){return false;});
}
function _rtFileCheckTick(){
  if(_rtEnded){_rtFileCheckTimer=null;return;}
  _rtTryCompleteFromFiles().then(function(done){
    if(done){_rtFileCheckTimer=null;return;}
    _rtFileCheckTries++;
    if(_rtFileCheckTries<30){_rtFileCheckTimer=setTimeout(_rtFileCheckTick,2000);}
    else{_rtFileCheckTimer=null;}
  });
}
function _rtScheduleFileCheck(){
  if(_rtFileCheckTimer){clearTimeout(_rtFileCheckTimer);}
  _rtFileCheckTries=0;
  _rtFileCheckTimer=setTimeout(_rtFileCheckTick,3000);
}
function _rtClearFileCheck(){if(_rtFileCheckTimer){clearTimeout(_rtFileCheckTimer);_rtFileCheckTimer=null;}}
function startRealtimeInterview(jobId,fromPrep,difficulty,focus){
  _endProgress=null; // 2026-08-12: 重置进度弹窗状态——上次面试结束残留会导致本次 generating 不弹窗
  _rtClearReverseHint();_rtLastMicAt=0;_rtLastAsrAt=0;
  return new Promise(function(resolve){
    if(!rtConfig.enabled){resolve(false);return;}
    var wsUrl='ws://127.0.0.1:'+rtConfig.ws_port;
    try{rtWs=new WebSocket(wsUrl);}catch(e){resolve(false);return;}
    rtWs.binaryType='arraybuffer';
    rtWs.onopen=function(){rtWs.send(JSON.stringify({type:'start',job_id:jobId,from_prep:fromPrep,difficulty:difficulty||null,focus:focus||null}));resolve(true);};
    rtWs.onmessage=function(ev){
      if(ev.data instanceof ArrayBuffer){playPcm(ev.data);}
      else{var d=JSON.parse(ev.data);
        if(d.type==='started'){document.getElementById('mockStatus').textContent=(difficulty||'')+' 实时语音面试中... · 点🎤开麦说话';_mockClearPlaceholder();document.getElementById('mockEndBtn').disabled=false;setMockInputEnabled(false);var rtMic=document.getElementById('mockMicBtn');if(rtMic)rtMic.disabled=false;_rtResetIdleTimer();}
        else if(d.type==='asr'){_rtResetIdleTimer();_rtLastAsrAt=performance.now();addMockBubble('user',d.text);scrollMockDown();}
        else if(d.type==='hint'){var st=document.getElementById('mockStatus');if(st)st.textContent=d.text||'';}
        else if(d.type==='tts_new'){var b=addMockBubble('ai','');b.setAttribute('data-tts','1');scrollMockDown();}else if(d.type==='tts_chunk'){var last=document.getElementById('mockChat').lastElementChild;if(last&&last.getAttribute('data-tts')){last.textContent+=d.text;scrollMockDown();}else{var b2=addMockBubble('ai',d.text);b2.setAttribute('data-tts','1');scrollMockDown();}if(!_rtReversePhase&&last&&last.textContent.indexOf('我的问题问完了')>=0||(!_rtReversePhase&&last&&last.textContent.indexOf('你有什么想问我的吗')>=0)){_rtEnterReversePhase();}}
        else if(d.type==='tts_ogg_start'){_oggCollecting=true;_oggChunks=[];}
        else if(d.type==='tts_ogg_end'){_oggCollecting=false;playOggBatch();}
        else if(d.type==='generating'){_rtGenerating=true;var stg2=document.getElementById('mockStatus');if(stg2)stg2.textContent='⏳ 面试结束，正在生成面试记录文件...';if(!_endProgress)showEndProgress();if(d.stage==='assessing'){updateEndProgress('assessing');}_rtScheduleFileCheck();}
        else if(d.type==='ended'){_rtClearFileCheck();_rtClearIdleTimer();_rtClearReverseHint();_rtEnded=true;_rtGenerating=false;rtWs=null;stopMicCapture();mockSession={id:null,active:false};setMockInputEnabled(false);document.getElementById('mockEndBtn').disabled=true;document.getElementById('mockStartBtn').disabled=false;lockMockConfig(false);document.getElementById('mockStatus').textContent='✅ 面试结束，记录文件已生成';var dlRt=document.getElementById('mockDlBtn');if(dlRt)dlRt.disabled=false;mockLastMode='realtime';try{if(d.assessment){showRtAssessment(d.assessment);}}catch(e){console.warn('showRtAssessment failed',e);}updateEndProgress('done',{md:d.md_name,assessment:d.assessment_name});}
        else if(d.type==='error'){_rtClearIdleTimer();_rtClearReverseHint();showModal('实时语音错误: '+d.text);rtWs=null;stopMicCapture();}
      }
    };
    rtWs.onclose=function(){_rtClearIdleTimer();_rtClearReverseHint();stopMicCapture();rtWs=null;if(_rtEnded){return;}if(_rtGenerating){_rtScheduleFileCheck();}mockSession={id:null,active:false};document.getElementById('mockEndBtn').disabled=true;document.getElementById('mockStartBtn').disabled=false;lockMockConfig(false);setMockInputEnabled(false);document.getElementById('mockStatus').textContent=rtEndByUser?'面试结束':(_rtGenerating?'面试结束，正在生成面试记录文件...':'面试已结束（连接断开）');};
    rtWs.onerror=function(){resolve(false);};
    setTimeout(function(){resolve(rtWs&&rtWs.readyState===1);},3000);
  });
}
function startMicCapture(){
  try{
    rtAudioCtx=new AudioContext({sampleRate:16000});
    // Prefer CABLE Output (VB-Cable) when present so automated/TTS voice is
    // picked up; fall back to the system default mic otherwise.
    var audioConstraints={channelCount:1,echoCancellation:true,noiseSuppression:true};
    navigator.mediaDevices.enumerateDevices().then(function(devs){
      var cable=devs.find(function(d){return d.kind==='audioinput'&&/CABLE|VB-Audio/i.test(d.label||'')});
      if(cable){audioConstraints.deviceId={exact:cable.deviceId};}
      return navigator.mediaDevices.getUserMedia({audio:audioConstraints});
    }).catch(function(){return navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});})
    .then(function(stream){
      rtMicStream=stream;var src=rtAudioCtx.createMediaStreamSource(stream);
      rtProcessor=rtAudioCtx.createScriptProcessor(4096,1,1);
      rtProcessor.onaudioprocess=function(e){
        if(!rtWs||rtWs.readyState!==1)return;
        _rtLastMicAt=performance.now();
        var inp=e.inputBuffer.getChannelData(0);var pcm=new Int16Array(inp.length);
        for(var i=0;i<inp.length;i++){var v=Math.max(-1,Math.min(1,inp[i]));pcm[i]=v<0?v*0x8000:v*0x7FFF;}
        rtWs.send(pcm.buffer);
      };
      src.connect(rtProcessor);rtProcessor.connect(rtAudioCtx.destination);
    }).catch(function(e){showModal('麦克风获取失败: '+e.message);});
  }catch(e){showModal('音频初始化失败: '+e.message);}
}
function stopMicCapture(){
  rtMicOn=false;
  if(rtProcessor){rtProcessor.disconnect();rtProcessor=null;}
  if(rtMicStream){rtMicStream.getTracks().forEach(function(t){t.stop();});rtMicStream=null;}
  if(rtAudioCtx){try{rtAudioCtx.close();}catch(e){}rtAudioCtx=null;}
  var mb=document.getElementById('mockMicBtn');if(mb)mb.textContent='🎤';
}
var _oggChunks=[];var _oggCollecting=false;
function playPcm(buf){
  if(_oggCollecting){
    _oggChunks.push(new Uint8Array(buf));
    return;
  }
  // Fallback: try decodeAudioData on single chunk
  if(!rtPlayCtx)rtPlayCtx=new AudioContext();
  rtPlayCtx.decodeAudioData(buf.slice(0)).then(function(ab){
    var gain=rtPlayCtx.createGain();gain.gain.value=1;
    var src=rtPlayCtx.createBufferSource();src.buffer=ab;
    src.connect(gain);gain.connect(rtPlayCtx.destination);src.start();
  }).catch(function(){});
}
function playOggBatch(){
  if(!_oggChunks.length)return;
  if(!rtPlayCtx)rtPlayCtx=new AudioContext();
  var total=_oggChunks.reduce(function(s,c){return s+c.length},0);
  var merged=new Uint8Array(total);
  var off=0;
  _oggChunks.forEach(function(c){merged.set(c,off);off+=c.length;});
  _oggChunks=[];
  rtPlayCtx.decodeAudioData(merged.buffer).then(function(ab){
    var gain=rtPlayCtx.createGain();gain.gain.value=1;
    var src=rtPlayCtx.createBufferSource();src.buffer=ab;
    src.connect(gain);gain.connect(rtPlayCtx.destination);src.start();
  }).catch(function(e){console.warn('decodeAudioData failed:',e)});
}
function endRealtimeInterview(){
  // 2026-08-12: confirm before ending — manual end now generates an assessment,
  // so warn the user that an incomplete question bank degrades evaluation quality.
  showConfirm('请确认面试题库已经询问回答完毕，否则影响面试评估结果',function(){
    rtEndByUser=true;
    if(rtWs&&rtWs.readyState===1){rtWs.send(JSON.stringify({type:'end'}));}
    stopMicCapture();
    mockSession={id:null,active:false};
    document.getElementById('mockEndBtn').disabled=true;
    setMockInputEnabled(false);
    lockMockConfig(false);
  });
}
function showRtAssessment(a){
  var box=document.getElementById('mockChat');var sum=document.createElement('div');
  sum.style.cssText='margin:6px 0 0;padding:8px 12px;border-radius:8px;background:var(--card);border:1px dashed var(--border);font-size:.85rem';
  var html='<b>🎯 总分: '+(a.overall||'?')+'/10</b>';
  if(a.dimensions){html+='<div style="margin-top:4px">';Object.keys(a.dimensions).forEach(function(k){html+=escHtml(k)+': '+(a.dimensions[k].score||'?')+'/10 · ';});html+='</div>';}
  if(a.strengths){html+='<div style="margin-top:4px;color:#3d7a5a">优势: '+escHtml(a.strengths.join('、'))+'</div>';}
  if(a.improvements){html+='<div style="margin-top:4px;color:#c15a3a">改进: '+escHtml(a.improvements.join('、'))+'</div>';}
  sum.innerHTML=html;box.appendChild(sum);scrollMockDown();
}
// 2026-08-12: 面试结束进度弹窗（保存记录 → LLM 评估 → 完成 + 查看按钮）
var _endProgress=null;
function showEndProgress(){
  var html='<div style="padding:6px 2px;min-width:300px">'
    +'<div data-st="saving" style="display:flex;align-items:center;gap:8px;margin:6px 0"><span style="width:20px;text-align:center">⏳</span><span>正在保存面试记录...</span></div>'
    +'<div data-st="assessing" style="display:flex;align-items:center;gap:8px;margin:6px 0;opacity:.4"><span style="width:20px;text-align:center">⏳</span><span>LLM 正在生成评估（约15-30秒）...</span></div>'
    +'<div data-st="done" style="display:flex;align-items:center;gap:8px;margin:6px 0;opacity:.4"><span style="width:20px;text-align:center">⏳</span><span>面试记录与评估已生成</span></div>'
    +'<div data-st="actions" style="display:none;margin-top:14px;gap:8px">'
    +'<button data-act="viewEval" class="pgn-btn" style="font-size:.82rem;padding:5px 14px">📊 查看评估报告</button>'
    +'<button data-act="viewMd" class="pgn-btn" style="font-size:.82rem;padding:5px 14px">📝 查看面试记录</button>'
    +'</div></div>';
  showContentModal('⏳ 正在生成面试结果',html);
  _endProgress={stage:'saving',names:null};
  return _endProgress;
}
function updateEndProgress(stage,names){
  if(!_endProgress)return;
  if(names)_endProgress.names=names;
  var body=document.getElementById('contentModalBody');
  var order=['saving','assessing','done'];
  var doneTexts={saving:'面试记录已保存',assessing:'LLM 评估已生成',done:'面试记录与评估已生成'};
  var idx=order.indexOf(stage);
  if(idx<0)return;
  for(var i=0;i<order.length;i++){
    var row=body.querySelector('[data-st="'+order[i]+'"]');
    if(!row)continue;
    var ico=row.querySelector('span:first-child');
    var label=row.querySelector('span:nth-child(2)');
    if(i<idx){
      row.style.opacity=1;
      if(ico)ico.textContent='✅';
      if(label)label.textContent=doneTexts[order[i]];
    }
    else if(i===idx){
      row.style.opacity=1;
      if(stage==='done'){
        if(ico)ico.textContent='✅';
        if(label)label.textContent=doneTexts[order[i]];
      }
    }
    else{row.style.opacity=.4;}
  }
  if(stage==='done'){
    var acts=body.querySelector('[data-st="actions"]');
    if(acts){
      acts.style.display='flex';
      var ev2=acts.querySelector('[data-act="viewEval"]');if(ev2)ev2.style.display=(_endProgress.names&&_endProgress.names.assessment)?'':'none';
      var vm2=acts.querySelector('[data-act="viewMd"]');if(vm2)vm2.style.display=(_endProgress.names&&_endProgress.names.md)?'':'none';
    }
    var t=document.getElementById('contentModalTitle');
    if(t)t.textContent='✅ 面试结果已生成';
  }
}

function startMockInterview(){
  _endProgress=null; // 2026-08-12: 重置进度弹窗状态——上次面试结束残留会导致本次 generating 不弹窗
  var jobId=document.getElementById('mockJobSel').value;
  if(!jobId){showModal('请先选择职位');return;}
  var body={job_id:jobId,from_prep:document.getElementById('mockFromPrep').checked,focus:document.getElementById('mockFocus').value,difficulty:document.getElementById('mockDifficulty').value};
  setMockStartState(true);
  document.getElementById('mockStatus').textContent='连接中...';
  var dlStart=document.getElementById('mockDlBtn');if(dlStart)dlStart.disabled=true;
  mockLastJobId=jobId;
  var mode=resolveMockMode();
  if(mode===null){showModal('实时语音未启用（config.yaml realtime.enabled=false），已切到文字模式');mode='text';var msFallback=document.getElementById('mockModeSel');if(msFallback)msFallback.value='text';rtModeOverride='text';setMockPlaceholder();updateMockHint();}
  if(mode==='realtime'){startRealtimeInterview(jobId,body.from_prep,body.difficulty,body.focus).then(function(ok){if(!ok){lockMockConfig(false);document.getElementById('mockStatus').textContent='';}else{mockSession={id:'realtime',active:true};mockLastMode='realtime';lockMockConfig(true);}});return;}
  mockLastMode='text';
  fetch('/api/mock-interview/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json()}).then(function(d){
    lockMockConfig(false);
    if(!d.ok){document.getElementById('mockStatus').textContent='';showModal(d.message||'启动失败');return;}
    mockSession={id:d.session_id,active:true};
    lockMockConfig(true);
    document.getElementById('mockStatus').textContent=(d.job_title||'')+' @ '+(d.job_company||'')+(d.note?' · '+d.note:'');
    _mockClearPlaceholder();
    document.getElementById('mockEndBtn').disabled=false;
    setMockInputEnabled(false);
    streamMockReply(null);
  }).catch(function(e){lockMockConfig(false);showModal('启动失败：'+e.message);});
}
function sendMockMessage(){
  if(!mockSession.active){showModal('面试未开始或已结束');return;}
  var inp=document.getElementById('mockInput');var text=inp.value.trim();
  if(!text)return;
  inp.value='';sttFinal='';sttDone=0;addMockBubble('user',text);setMockInputEnabled(false);streamMockReply(text);
}
async function streamMockReply(text){
  var aiBubble=addMockBubble('ai','(思考中...)');
  var LF=String.fromCharCode(10);var SEP=LF+LF;
  try{
    var resp=await fetch('/api/mock-interview/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:mockSession.id,text:text})});
    if(!resp.ok){aiBubble.textContent='错误: '+(await resp.text());setMockInputEnabled(mockSession.active);return;}
    var reader=resp.body.getReader();var dec=new TextDecoder();var buf='';var firstDelta=true;
    while(true){
      var r=await reader.read();if(r.done)break;
      buf+=dec.decode(r.value,{stream:true});
      var idx;
      while((idx=buf.indexOf(SEP))>=0){
        var chunk=buf.slice(0,idx);buf=buf.slice(idx+2);
        if(chunk.indexOf('data: ')!==0)continue;
        var evt;try{evt=JSON.parse(chunk.slice(6));}catch(e){continue;}
        if(evt.type==='delta'){if(firstDelta){aiBubble.textContent='';firstDelta=false;}aiBubble.textContent+=evt.text;scrollMockDown();}
        else if(evt.type==='turn_end'){setMockInputEnabled(true);speakMock(aiBubble.textContent);}
        else if(evt.type==='generating'){var stg=document.getElementById('mockStatus');if(stg)stg.textContent='⏳ 面试结束，正在生成面试记录文件...';if(!_endProgress)showEndProgress();updateEndProgress('assessing');}
        else if(evt.type==='end'){
          mockSession.active=false;
          document.getElementById('mockEndBtn').disabled=true;
          setMockInputEnabled(false);
          lockMockConfig(false);
          var dlTxt=document.getElementById('mockDlBtn');if(dlTxt)dlTxt.disabled=false;mockLastMode='text';
          var rawEnd=aiBubble.textContent;var idxEnd=rawEnd.search(/以下是您的表现评估|```json/);if(idxEnd>=0)rawEnd=rawEnd.slice(0,idxEnd).trim();
          aiBubble.textContent=(rawEnd||'面试结束。')+' [面试结束]';
          var stE=document.getElementById('mockStatus');if(stE)stE.textContent='✅ 面试结束，记录文件已生成';
          var a=evt.assessment;
          if(a){
            var sum=document.createElement('div');
            sum.style.cssText='margin:6px 0 0;padding:8px 12px;border-radius:8px;background:var(--card);border:1px dashed var(--border);font-size:.85rem';
            var html='<b>🎯 总分: '+(a.overall||'?')+'/10</b>';
            if(a.dimensions){html+='<div style="margin-top:4px">';Object.keys(a.dimensions).forEach(function(k){var dv=a.dimensions[k];var sc=(dv&&typeof dv==='object')?(dv.score||'?'):dv;html+=escHtml(k)+': '+sc+'/10 · ';});html+='</div>';}
            if(a.strengths){html+='<div style="margin-top:4px;color:#3d7a5a">优势: '+escHtml(a.strengths.join('、'))+'</div>';}
            if(a.improvements){html+='<div style="margin-top:4px;color:#c15a3a">改进: '+escHtml(a.improvements.join('、'))+'</div>';}
            if(a.summary){html+='<div style="margin-top:4px;color:var(--muted)">'+escHtml(a.summary)+'</div>';}
            sum.innerHTML=html;
            document.getElementById('mockChat').appendChild(sum);
          }
          if(evt.md_name)updateEndProgress('done',{md:evt.md_name,assessment:evt.assessment_name});
          scrollMockDown();
        }else if(evt.type==='error'){aiBubble.textContent=evt.text||'面试官没有生成回复';setMockInputEnabled(mockSession.active);}
      }
    }
  }catch(e){aiBubble.textContent+=' [异常: '+e.message+']';setMockInputEnabled(mockSession.active);}
}
function endMockInterview(){
  // 2026-08-12: confirm before ending — manual end now generates an assessment
  // (marked 中途结束), so warn about incomplete question banks.
  if(rtWs){endRealtimeInterview();return;}
  if(!mockSession.id){return;}
  showConfirm('请确认面试题库已经询问回答完毕，否则影响面试评估结果',function(){
    var sid=mockSession.id;
    // 2026-08-12: 进度弹窗——保存记录 → 评估生成中（服务端同步完成）→ 完成
    showEndProgress();
    setTimeout(function(){if(_endProgress&&_endProgress.stage==='saving')updateEndProgress('assessing');},800);
    fetch('/api/mock-interview/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid})}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){addMockBubble('ai','(已结束面试，记录与评估已保存)');updateEndProgress('done',{md:d.md,assessment:d.assessment});}
      mockSession={id:null,active:false};
      document.getElementById('mockEndBtn').disabled=true;
      setMockInputEnabled(false);
      lockMockConfig(false);
      var dlTxt=document.getElementById('mockDlBtn');if(dlTxt)dlTxt.disabled=false;mockLastMode='text';
    }).catch(function(){});
  });
}
// --- Stage 4: voice STT (SpeechRecognition) + TTS (SpeechSynthesis), browser-native ---
var mockSTT=null, mockMicOn=false, mockTTSOk=false, sttFinal='', sttDone=0;
function initMockVoice(){
  if(mockSTT!==null)return;
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  var hint=document.getElementById('mockVoiceHint');
  if(SR){
    mockSTT=new SR();mockSTT.lang='zh-CN';mockSTT.continuous=true;mockSTT.interimResults=true;
    mockSTT.onresult=function(e){
      // SpeechRecognition's results list is a growing snapshot: an index that
      // was interim can later become final, and stays final afterwards. Only
      // commit each index ONCE (tracked by sttDone) so long speech never loses
      // earlier text nor duplicates committed segments. interim results are
      // appended live after the committed text.
      var interim='';
      for(var i=0;i<e.results.length;i++){
        if(i<sttDone){continue;}
        if(e.results[i].isFinal){sttFinal+=e.results[i][0].transcript;sttDone=i+1;}
        else{interim+=e.results[i][0].transcript;}
      }
      var inp=document.getElementById('mockInput');inp.value=sttFinal+interim;inp.dispatchEvent(new Event('input'));
    };
    mockSTT.onend=function(){
      // SpeechRecognition auto-ends after a long silence; keep the mic alive
      // unless the user manually stopped it (mockMicOn=false) or an error
      // fired (onerror also clears mockMicOn).
      if(mockMicOn){try{mockSTT.start();}catch(e){mockMicOn=false;document.getElementById('mockMicBtn').textContent='🎤';}}
      else{document.getElementById('mockMicBtn').textContent='🎤';}
    };
    mockSTT.onerror=function(){mockMicOn=false;document.getElementById('mockMicBtn').textContent='🎤';};
    if(hint)hint.textContent='语音: 识别✓';
  }else{if(hint)hint.textContent='语音: 识别✗ (建议Chrome)';}
  mockTTSOk=('speechSynthesis' in window);
  if(!mockTTSOk&&hint){hint.textContent=(hint.textContent?hint.textContent+' ':'')+'朗读✗';}
}
function toggleMockMic(){
    // 未开始面试时麦克风不可用（文字/实时模式统一拦截），避免在禁用输入框上
    // 开启语音识别或采集麦克风。2026-08-16 模拟面试 TAB 测试修复。
    if(!mockSession.active){showModal('请先开始面试');return;}
  var mode=resolveMockMode();
  if(mode==='realtime'){toggleRtMic();return;}
  if(!mockSTT){showModal('浏览器不支持语音识别，建议使用 Chrome');return;}
  if(mockMicOn){try{mockSTT.stop();}catch(e){}mockMicOn=false;document.getElementById('mockMicBtn').textContent='🎤';sttFinal='';sttDone=0;}
  else{try{mockSTT.start();mockMicOn=true;document.getElementById('mockMicBtn').textContent='⏹';}catch(e){mockMicOn=false;}}
}
function toggleRtMic(){
  if(rtMicOn){stopMicCapture();}
  else{startMicCapture();rtMicOn=true;document.getElementById('mockMicBtn').textContent='🔇';}
}
function speakMock(text){
  var cb=document.getElementById('mockTTS');
  if(!cb||!cb.checked)return;
  if(!mockTTSOk||!text)return;
  try{speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(text);u.lang='zh-CN';speechSynthesis.speak(u);}catch(e){}
}
// --- offer evaluation panel (file-driven table) ---
var _offerBusy=false;
function showModal(msg,title){var m=document.getElementById('globalModal');if(!m)return;var t=document.getElementById('globalModalTitle');var em=document.getElementById('globalModalMsg');var _msg=(''+msg);if(!title){if(_msg.indexOf('✅')>=0||_msg.indexOf('完成')>=0||_msg.indexOf('已保存')>=0||_msg.indexOf('已记录')>=0)title='完成';else title='';}if(t){if(title){t.style.display='';t.textContent=title;}else{t.style.display='none';}}if(em)em.textContent=_msg;m.style.display='flex';}
function closeGlobalModal(){var m=document.getElementById('globalModal');if(m)m.style.display='none';}
function showContentModal(title,html){var m=document.getElementById('contentModal');if(!m)return;document.getElementById('contentModalTitle').textContent=title||'';document.getElementById('contentModalBody').innerHTML=html||'';m.style.display='flex';}
function closeContentModal(){var m=document.getElementById('contentModal');if(m)m.style.display='none';}
function showConfirm(msg,onYes){var m=document.getElementById('confirmModal');if(!m)return;var _msg=(''+(msg||''));if(_msg.indexOf('提示：')!==0)_msg='提示：'+_msg;document.getElementById('confirmModalMsg').textContent=_msg;var y=document.getElementById('confirmModalYes');var n=document.getElementById('confirmModalNo');var close=function(){m.style.display='none';y.blur();};y.onclick=function(){close();if(onYes)onYes();};n.onclick=function(){close();};m.style.display='flex';n.focus();}
function _offerStatus(msg,isErr){var s=document.getElementById('offerStatus');if(s){s.textContent=msg;s.style.color=isErr?'#c15a3a':'var(--muted)';}}
function onUnifiedFilePicked(input){
  var files=input.files;if(!files||!files.length)return;
  var typeSel=document.getElementById('uploadTypeSel');var uploadType=typeSel?typeSel.value:'resume';
  var queue=Array.prototype.slice.call(files);var idx=0,total=queue.length,okR=0,okO=0,fail=0;
  function next(){
    if(idx>=queue.length){_invalidateUploadCache();switchUploadList();loadOfferTable();input.value='';return;}
    var file=queue[idx];idx++;
    if(file.size>5*1024*1024){fail++;next();return;}
    var reader=new FileReader();
    reader.onload=function(e){
      var content=e.target.result||'';var name=file.name||'file.txt';
      if(uploadType==='offer'){
        fetch('/api/offer/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,content:content})}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok)okO++;else fail++;}).catch(function(){fail++;}).finally(next);
      } else {
        fetch('/api/resume/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,content:content,set_default:(okR===0)})}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok)okR++;else fail++;}).catch(function(){fail++;}).finally(next);
      }
    };
    reader.onerror=function(){fail++;next();};
    reader.readAsText(file,'utf-8');
  }
  next();
}
function downloadOfferTemplate(){
  var a=document.createElement('a');a.href='/api/offer/template';a.download='offer_template.txt';
  document.body.appendChild(a);a.click();document.body.removeChild(a);
}
function onOfferFilePicked(input){
  var files=input.files;if(!files||!files.length)return;
  var status=document.getElementById('offerStatus');
  var queue=Array.prototype.slice.call(files);var idx=0,total=queue.length,ok=0,fail=0;
  function uploadNext(){
    if(idx>=queue.length){if(status)status.textContent='✅ 上传完成：'+ok+'/'+total+(fail?(' · '+fail+' 失败'):'');loadOfferTable();input.value='';return;}
    var file=queue[idx];idx++;
    var reader=new FileReader();
    reader.onload=function(e){
      var content=e.target.result||'';var name=file.name||'offer.txt';
      if(status)status.textContent='上传中… ('+idx+'/'+total+') '+name;
      fetch('/api/offer/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,content:content})})
        .then(function(r){return r.json()})
        .then(function(d){if(d&&d.ok){ok++}else{fail++}})
        .catch(function(){fail++})
        .finally(uploadNext);
    };
    reader.onerror=function(){fail++;uploadNext()};
    reader.readAsText(file,'utf-8');
  }
  uploadNext();
}
function loadOfferTable(){
  fetch('/api/offer/list').then(function(r){return r.json()}).then(function(d){
    var tb=document.getElementById('offerTb');var empty=document.getElementById('offerEmpty');if(!tb)return;
    var items=d.items||[];
    if(!items.length){tb.innerHTML='';if(empty)empty.style.display='block';return;}
    if(empty)empty.style.display='none';
    tb.innerHTML=items.map(function(o){
      var st=o.evaluated?('✅ 已评估'+(o.overall_score!=null?(' '+o.overall_score):'')):'<span style="color:var(--muted)">未评估</span>';
      var nameText=escHtml(o.name);
      return '<tr><td>'+o.no+'</td><td><input type="checkbox" class="offer-ck" value="'+escAttr(o.name)+'"></td><td title="'+escAttr(o.name)+'">📄 '+nameText+'</td><td style="font-size:.78rem">'+st+'</td><td><span class="file-actions"><a href="javascript:;" data-act="evalOffer" data-name="'+escAttr(o.name)+'" title="运行/刷新评估">评估</a><a href="javascript:;" data-act="previewOfferRes" data-name="'+escAttr(o.name)+'" title="查看已缓存结果">预览评估结果</a><a href="javascript:;" data-act="delOfferFile" data-name="'+escAttr(o.name)+'" class="delete-action">删除</a></span></td></tr>';
    }).join('');
  }).catch(function(){});
}
function offerToggleAll(src){document.querySelectorAll('#offerTb .offer-ck').forEach(function(c){c.checked=src.checked});}
function _checkedOfferNames(){var n=[];document.querySelectorAll('#offerTb .offer-ck:checked').forEach(function(c){n.push(c.value)});return n;}
function _checkedOfferNamesInUpload(){var n=[];document.querySelectorAll('#resumeTb .offer-ck:checked').forEach(function(c){n.push(c.value)});return n;}
function evalOfferRow(encName){
  if(_offerBusy){showModal('评估进行中，请稍候','提醒');return;}
  var name=decodeURIComponent(encName);
  var _disp=name.replace(/\.txt$/,'');
  _offerBusy=true;showContentModal(_disp+'——评估中：','<div style="text-align:center;padding:40px 20px;color:var(--muted)">⏳ 正在评估 '+escHtml(name)+'，请稍候…</div>');
  fetch('/api/offer/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_name:name})})
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(d){_offerCache[name]=d;showContentModal(_disp+'——评估结果：',renderOfferResult(d,name));loadOfferTable();})
    .catch(function(e){showModal('评估失败：'+e.message);})
    .finally(function(){_offerBusy=false;});
}
function previewOfferRow(encName){
  var name=decodeURIComponent(encName);
  var _disp=name.replace(/\.txt$/,'');
  showContentModal(_disp+'——评估结果：','<div style="text-align:center;padding:40px 20px;color:var(--muted)">加载中…</div>');
  fetch('/api/offer/preview?file_name='+encodeURIComponent(name)).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(d){_offerCache[name]=d;showContentModal(_disp+'——评估结果：',renderOfferResult(d,name));})
    .catch(function(e){showModal('预览失败：'+e.message);});
}
function batchEvalOffers(){
  var names=_checkedOfferNames();if(!names.length){showModal('请先勾选要评估的 Offer','提醒');return;}
  var i=0;var btn=document.getElementById('offerBatchBtn');if(btn)btn.disabled=true;
  showContentModal('批量评估','<div style="text-align:center;padding:40px 20px;color:var(--muted)">⏳ 批量评估中 (0/'+names.length+')…</div>');
  function next(){
    if(i>=names.length){showContentModal('批量评估完成','<div style="padding:24px">✅ 已完成 '+names.length+' 个 Offer 的评估。<br><br>结果已缓存。可在列表点「👁 预览」查看单份详情，或勾选 ≥2 个点「offer对比」生成对比分析。</div>');if(btn)btn.disabled=false;loadOfferTable();return;}
    var n=names[i];i++;
    showContentModal('批量评估','<div style="text-align:center;padding:40px 20px;color:var(--muted)">⏳ 批量评估中 ('+i+'/'+names.length+') '+escHtml(n)+'…</div>');
    fetch('/api/offer/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_name:n})})
      .then(function(r){return r.json()})
      .then(function(d){})
      .catch(function(){})
      .finally(next);
  }
  next();
}
var _lastCompareNames=[];
var _lastCompareData=null;
function compareOffers(){
  var names=_checkedOfferNames();
  if(names.length<2){showModal('请至少勾选 2 个 Offer 进行对比','提醒');return;}
  showContentModal('Offer 对比','<div style="text-align:center;padding:40px 20px;color:var(--muted)">⏳ 正在检查评估状态…</div>');
  fetch('/api/offer/list').then(function(r){return r.json()}).then(function(d){
    var items=d.items||[];var evMap={};items.forEach(function(o){evMap[o.name]=o.evaluated});
    var uneval=names.filter(function(n){return !evMap[n]});
    if(uneval.length){showModal('以下 Offer 尚未评估，请先评估后再对比：\n'+uneval.join('、'),'提示');return;}
    _lastCompareNames=names;
    showContentModal('Offer 对比','<div style="text-align:center;padding:40px 20px;color:var(--muted)">⏳ LLM 正在重新比对 '+names.length+' 份 Offer，请稍候…</div>');
    fetch('/api/offer/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_names:names})})
      .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
      .then(function(d){_lastCompareData=d;showContentModal('Offer 对比',renderOfferCompare(d,names));})
      .catch(function(e){showModal('对比失败：'+e.message);});
  }).catch(function(e){showModal('检查评估状态失败：'+e.message);});
}
function renderOfferResult(d,name){
  var res=d.result||{};var p=d.parsed||{};
  var scores={overall:Number(res.overall_score)||0,competitive:Number(res.competitive_score)||0,growth:Number(res.growth_score)||0,risk:Number(res.risk_score)||0,salary:Number(res.salary_score)||0,commute:Number(res.commute_score)||0,wlb:Number(res.wlb_score)||0,culture:Number(res.culture_score)||0,stability:Number(res.stability_score)||0};
  var radar=drawRadar(scores);
  var pros=res.pros||[],cons=res.cons||[],levers=res.negotiation_levers||[];
  var html='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><b style="font-size:.95rem">📄 '+escHtml((name||'Offer').replace(/\.txt$/,''))+'</b><span style="display:flex;gap:6px"><button data-act="saveOffer" data-name="'+escAttr(name||'')+'" class="pgn-btn" style="font-size:.72rem;padding:3px 10px;white-space:nowrap">💾 保存报告</button></span></div>';
  html+='<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start">';
  html+='<div style="flex:1 1 260px;min-width:240px">'+radar+'</div>';
  html+='<div style="flex:2 1 320px;min-width:280px">';
  html+='<div style="font-weight:700;margin-bottom:8px">综合评分：'+scores.overall+' / 10</div>';
  html+='<div style="font-size:.85rem;color:var(--muted);margin-bottom:12px;line-height:1.5">'+escHtml(res.summary||'')+'</div>';
  html+='<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:.78rem;margin-bottom:12px">';
  var cards=[['竞争力',scores.competitive],['成长性',scores.growth],['风险',scores.risk],['薪资满意度',scores.salary],['通勤便利',scores.commute],['工作生活平衡',scores.wlb],['文化匹配',scores.culture],['稳定性',scores.stability]];
  cards.forEach(function(c){html+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center"><div style="font-weight:700">'+c[1]+'</div><div style="color:var(--muted)">'+c[0]+'</div></div>';});
  html+='</div>';
  html+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">';
  html+='<div style="background:rgba(61,122,90,.12);border:1px solid rgba(61,122,90,.35);border-radius:6px;padding:10px"><div style="font-weight:700;color:#3d7a5a;margin-bottom:6px">优势</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';
  pros.forEach(function(x){html+='<li>'+escHtml(x)+'</li>';});if(!pros.length)html+='<li style="color:var(--muted)">暂无</li>';
  html+='</ul></div>';
  html+='<div style="background:rgba(193,90,58,.12);border:1px solid rgba(193,90,58,.35);border-radius:6px;padding:10px"><div style="font-weight:700;color:#c15a3a;margin-bottom:6px">风险 / 劣势</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';
  cons.forEach(function(x){html+='<li>'+escHtml(x)+'</li>';});if(!cons.length)html+='<li style="color:var(--muted)">暂无</li>';
  html+='</ul></div></div>';
  if(levers.length){html+='<div style="margin-top:12px;background:var(--card);border:1px dashed var(--border);border-radius:6px;padding:10px"><div style="font-weight:700;margin-bottom:6px">谈判杠杆</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';levers.forEach(function(x){html+='<li>'+escHtml(x)+'</li>';});html+='</ul></div>';}
  html+='</div></div>';
  return html;
}
var _mockAssessmentCache={};
function renderMockAssessment(d,name){
  var a=d.assessment||{};var dims=a.dimensions||{};
  // 5-dim radar: overall + technical/communication/logic/project/culture
  var scores={overall:Number(a.overall)||0,technical:Number((dims.technical&&(dims.technical.score!==undefined?dims.technical.score:dims.technical))||(dims.technical!==undefined&&typeof dims.technical==='number'?dims.technical:0))||0,communication:Number((dims.communication&&(dims.communication.score!==undefined?dims.communication.score:dims.communication))||(typeof dims.communication==='number'?dims.communication:0))||0,logic:Number((dims.logic&&(dims.logic.score!==undefined?dims.logic.score:dims.logic))||(typeof dims.logic==='number'?dims.logic:0))||0,project:Number((dims.project&&(dims.project.score!==undefined?dims.project.score:dims.project))||(typeof dims.project==='number'?dims.project:0))||0,culture:Number((dims.culture&&(dims.culture.score!==undefined?dims.culture.score:dims.culture))||(typeof dims.culture==='number'?dims.culture:0))||0};
  var radar=drawRadar5(scores);
  var strengths=a.strengths||[],improvements=a.improvements||[];
  var html='<div style="font-weight:700;font-size:.95rem;margin-bottom:8px">📄 '+escHtml(((name||'评估').replace(/\.txt$/,'')).replace(/_mock_interview_assessment$|_realtime_mock_assessment$/,''))+'</div>';
  html+='<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start">';
  html+='<div style="flex:1 1 260px;min-width:240px">'+radar+'</div>';
  html+='<div style="flex:2 1 320px;min-width:280px">';
  html+='<div style="font-weight:700;margin-bottom:8px">综合评分：'+scores.overall+' / 10</div>';
  if(a.summary){html+='<div style="font-size:.85rem;color:var(--muted);margin-bottom:12px;line-height:1.5">'+escHtml(a.summary)+'</div>';}
  html+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;font-size:.78rem;margin-bottom:12px">';
  var cards=[['技术能力',scores.technical],['沟通表达',scores.communication],['逻辑思维',scores.logic],['岗位匹配',scores.project],['文化匹配',scores.culture]];
  cards.forEach(function(c){html+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center"><div style="font-weight:700">'+c[1]+'</div><div style="color:var(--muted)">'+c[0]+'</div></div>';});
  html+='</div>';
  html+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">';
  html+='<div style="background:rgba(61,122,90,.12);border:1px solid rgba(61,122,90,.35);border-radius:6px;padding:10px"><div style="font-weight:700;color:#3d7a5a;margin-bottom:6px">优势</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';
  strengths.forEach(function(x){html+='<li>'+escHtml(x)+'</li>';});if(!strengths.length)html+='<li style="color:var(--muted)">暂无</li>';
  html+='</ul></div>';
  html+='<div style="background:rgba(193,90,58,.12);border:1px solid rgba(193,90,58,.35);border-radius:6px;padding:10px"><div style="font-weight:700;color:#c15a3a;margin-bottom:6px">改进点</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';
  improvements.forEach(function(x){html+='<li>'+escHtml(x)+'</li>';});if(!improvements.length)html+='<li style="color:var(--muted)">暂无</li>';
  html+='</ul></div></div>';
  if(a.dim_comments){html+='<div style="margin-top:12px;background:var(--card);border:1px dashed var(--border);border-radius:6px;padding:10px"><div style="font-weight:700;margin-bottom:6px">维度点评</div><ul style="margin:0;padding-left:16px;font-size:.82rem;line-height:1.6">';Object.keys(a.dim_comments).forEach(function(k){html+='<li>'+escHtml(k)+': '+escHtml(a.dim_comments[k])+'</li>';});html+='</ul></div>';}
  html+='</div></div>';
  return html;
}
function drawRadar5(scores){
  var size=280,cx=size/2,cy=size/2,r=90,levels=5;
  var axisNames={overall:'综合',technical:'技术能力',communication:'沟通表达',logic:'逻辑思维',project:'岗位匹配',culture:'文化匹配'};
  var order=['technical','communication','logic','project','culture'];
  var colors={overall:'#2563eb',technical:'#3d7a5a',communication:'#4a90e2',logic:'#d97706',project:'#7c3aed',culture:'#db2777'};
  var NL=String.fromCharCode(10);
  var svg='<svg width="'+size+'" height="'+size+'" viewBox="0 0 '+size+' '+size+'" xmlns="http://www.w3.org/2000/svg">'+NL;
  for(var i=1;i<=levels;i++){
    var rr=r*i/levels,pts=[];
    for(var j=0;j<5;j++){var a=-Math.PI/2+j*2*Math.PI/5;pts.push((cx+rr*Math.cos(a)).toFixed(2)+','+(cy+rr*Math.sin(a)).toFixed(2));}
    svg+='<polygon points="'+pts.join(' ')+'" fill="none" stroke="var(--border)" stroke-width="1"/>'+NL;
  }
  for(var j=0;j<5;j++){var a=-Math.PI/2+j*2*Math.PI/5;svg+='<line x1="'+cx+'" y1="'+cy+'" x2="'+(cx+r*Math.cos(a)).toFixed(2)+'" y2="'+(cy+r*Math.sin(a)).toFixed(2)+'" stroke="var(--border)" stroke-width="1"/>'+NL;}
  var dataPts=[],scorePts=[];
  for(var j=0;j<5;j++){
    var k=order[j];var v=Math.max(0,Math.min(10,Number(scores[k])||0));
    var a=-Math.PI/2+j*2*Math.PI/5;var rr=r*v/10;
    var px=cx+rr*Math.cos(a),py=cy+rr*Math.sin(a);
    dataPts.push(px.toFixed(2)+','+py.toFixed(2));scorePts.push({x:px,y:py,k:k,v:v,a:a});
  }
  svg+='<polygon points="'+dataPts.join(' ')+'" fill="rgba(37,99,235,0.15)" stroke="var(--accent)" stroke-width="2"/>'+NL;
  scorePts.forEach(function(p){
    svg+='<circle cx="'+p.x.toFixed(2)+'" cy="'+p.y.toFixed(2)+'" r="4" fill="'+(colors[p.k]||'#2563eb')+'"/>'+NL;
    var pad=22,tx=p.x+pad*Math.cos(p.a),ty=p.y+pad*Math.sin(p.a);
    if(Math.abs(Math.sin(p.a))>0.9){ty+=(p.a>0?10:-10);}
    var anchor='middle';
    if(Math.abs(Math.cos(p.a))>0.1){anchor=Math.cos(p.a)>0?'start':'end';}
    svg+='<text x="'+tx+'" y="'+ty+'" text-anchor="'+anchor+'" fill="var(--text)" font-size="11" font-weight="600">'+escHtml(axisNames[p.k])+' '+p.v+'</text>'+NL;
  });
  for(var i=1;i<=levels;i++){svg+='<text x="'+(cx+4)+'" y="'+(cy-r*i/levels+4)+'" fill="var(--muted)" font-size="9">'+(i*2)+'</text>'+NL;}
  svg+='</svg>';
  return svg;
}
var _offerCache={};
function saveOfferReport(encName){
  var name=decodeURIComponent(encName);if(!name){showModal('文件名缺失');return;}
  var status=document.getElementById('offerStatus');if(status)status.textContent='保存报告中…';
  // Ensure cache is populated (page refresh / direct save without eval loses
  // _offerCache). Fetch preview once; it returns cached eval or file parse.
  var _ensureCache=function(){
    if(_offerCache[name])return Promise.resolve(_offerCache[name]);
    return fetch('/api/offer/preview?file_name='+encodeURIComponent(name))
      .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
      .then(function(d){_offerCache[name]=d;return d;});
  };
  _ensureCache().then(function(cached){
    var p=cached.parsed||{};var res=cached.result||{};
    var body={file_name:name,company:p.company||'',title:p.title||'',location:p.location||'',salary:p.salary||'',bonus:p.bonus||'',benefits:p.benefits||'',level:p.level||'',notes:p.notes||'',overall_score:res.overall_score||0,competitive_score:res.competitive_score||0,growth_score:res.growth_score||0,risk_score:res.risk_score||0,salary_score:res.salary_score||0,commute_score:res.commute_score||0,wlb_score:res.wlb_score||0,culture_score:res.culture_score||0,stability_score:res.stability_score||0,summary:res.summary||'',pros:res.pros||[],cons:res.cons||[],negotiation_levers:res.negotiation_levers||[]};
    // 原封不动：把评估预览的完整 HTML（含雷达图 SVG + 卡片布局）一并保存，
    // 但去掉交互按钮（保存报告按钮在弹窗/静态 HTML 里无用）
    var _html=renderOfferResult(cached,name);
    _html=_html.replace(/<span style="display:flex;gap:6px"><button data-act="saveOffer"[^]*?<\/span>/, '');
    body.html_content=_html;
    return fetch('/api/offer/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  })
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(d){if(status)status.textContent='✅ 已保存：'+escHtml(d.file_name||'');})
    .catch(function(e){if(status)status.textContent='保存失败：'+e.message;});
}
function renderOfferCompare(d,names){
  var offers=d.offers||[];var best=d.best||null;
  var dims=[{k:'overall_score',n:'综合'},{k:'competitive_score',n:'竞争力'},{k:'growth_score',n:'成长性'},{k:'risk_score',n:'风险'},{k:'salary_score',n:'薪资满意度'},{k:'commute_score',n:'通勤便利'},{k:'wlb_score',n:'工作生活平衡'},{k:'culture_score',n:'文化匹配'},{k:'stability_score',n:'稳定性'}];
  var html='<div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px">';
  html+='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px"><b>Offer 对比</b><span style="display:flex;gap:6px"><button onclick="saveCompareReport()" class="pgn-btn" style="font-size:.72rem;padding:3px 10px">💾 保存对比报告</button></span></div>';
  if(best){var leadDims=[];dims.forEach(function(dim){if(dim.n==='综合')return;var bv=Number((best.result&&best.result[dim.k])||0);var mx2=Math.max.apply(null,offers.map(function(o){return Number((o.result&&o.result[dim.k])||0);}));if(bv>0&&bv===mx2)leadDims.push(dim.n);});html+='<div style="font-size:.82rem;color:var(--accent);margin-bottom:10px">🏆 推荐：'+escHtml(best.company||'未命名')+'（综合 '+((best.result&&best.result.overall_score)||'-')+' / 10）'+(leadDims.length?(' · 在「'+leadDims.slice(0,3).join('、')+'」领先'):'')+'</div>';}
  html+='<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.85rem">';
  html+='<thead><tr><th style="text-align:left;padding:6px;border-bottom:1px solid var(--border)">维度</th>';
  offers.forEach(function(o){html+='<th style="text-align:center;padding:6px;border-bottom:1px solid var(--border)">'+escHtml(o.company||'未命名')+'</th>';});
  html+='</tr></thead><tbody>';
  dims.forEach(function(dim){
    var vals=offers.map(function(o){return Number((o.result&&o.result[dim.k])||0);});
    var mx=Math.max.apply(null,vals);
    html+='<tr><td style="padding:6px;border-bottom:1px solid var(--border);font-weight:600">'+dim.n+'</td>';
    offers.forEach(function(o,i){var v=(o.result&&o.result[dim.k])||0;var win=(vals[i]===mx&&mx>0);html+='<td style="text-align:center;padding:6px;border-bottom:1px solid var(--border);'+(win?'font-weight:700;background:#eff6ff;color:var(--accent)':'')+'">'+v+(win?' 🏆':'')+'</td>';});
    html+='</tr>';
  });
  html+='</tbody></table></div>';
  if(d.analysis){html+='<div style="margin-top:12px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:6px"><b style="display:block;margin-bottom:8px;color:var(--accent)">🤖 LLM 对比分析</b><div class="md-body">'+safeMd(d.analysis)+'</div></div>';}
  html+='</div>';
  return html;
}
function saveCompareReport(){
  var names=_lastCompareNames||[];
  if(names.length<2){showModal('请先进行对比');return;}
  var status=document.getElementById('offerStatus');if(status)status.textContent='生成对比报告…';
  var offers=(_lastCompareData&&_lastCompareData.offers)||[];
  // 原封不动：把对比预览的完整 HTML（对比表格 + LLM 分析）一并保存，去掉保存按钮
  var _html=renderOfferCompare(_lastCompareData,names);
  _html=_html.replace(/<span style="display:flex;gap:6px"><button onclick="saveCompareReport\(\)"[^]*?<\/span>/, '');
  var body={offers:offers, html_content:_html};
  fetch('/api/offer/compare/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(d){if(status)status.textContent='✅ 已生成：'+escHtml(d.file_name||'');})
    .catch(function(e){if(status)status.textContent='生成失败：'+e.message;});
}
function deleteOfferFile(encName){
  var name=decodeURIComponent(encName);showConfirm('确定删除 Offer「'+name+'」？评估缓存也会清除。',function(){
    fetch('/api/offer?file_name='+encodeURIComponent(name),{method:'DELETE'}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok){loadOfferTable();var _ut=document.getElementById('uploadTypeSel');if(_ut&&_ut.value==='offer')loadOfferListInUploadTab();var sa=document.querySelector('#offer-panel thead input[type=checkbox]');if(sa)sa.checked=false;}}).catch(function(e){showModal('删除失败：'+e.message);});
});
}
function batchDeleteOffers(){
  if(_offerBusy){_offerStatus('评估进行中，请稍候',true);return;}
  var names=_checkedOfferNames();if(!names.length){showModal('提示：请先勾选要删除的 Offer');return;}
  var preview=names.length<=5?names.join('、'):names.slice(0,5).join('、')+' 等'+names.length+'个';
  showConfirm('确定删除以下 '+names.length+' 个 Offer？评估缓存也会清除：'+preview,function(){
  var i=0;var prog=document.getElementById('offerProgress');var btn=document.getElementById('offerDelBtn');
  if(btn)btn.disabled=true;if(prog){prog.style.display='block';prog.max=names.length;prog.value=0;}
  function next(){
    if(i>=names.length){_offerStatus('✅ 批量删除完成：'+names.length+' 个');if(prog)prog.style.display='none';if(btn)btn.disabled=false;loadOfferTable();var sa=document.querySelector('#offer-panel thead input[type=checkbox]');if(sa)sa.checked=false;return;}
    var n=names[i];i++;_offerStatus('批量删除 ('+i+'/'+names.length+') '+n);if(prog)prog.value=i;
    fetch('/api/offer?file_name='+encodeURIComponent(n),{method:'DELETE'}).then(function(r){return r.json()}).then(function(){next();}).catch(function(e){showModal('删除失败：'+e.message);if(btn)btn.disabled=false;if(prog)prog.style.display='none';});
  }
  next();
  });
}
function drawRadar(scores){
  var size=280,cx=size/2,cy=size/2,r=90,levels=5;
  var axisNames={overall:'综合',competitive:'竞争力',growth:'成长性',risk:'风险',salary:'薪资满意度',commute:'通勤便利',wlb:'工作生活平衡',culture:'文化匹配',stability:'稳定性'};
  var order=['competitive','growth','salary','culture','stability','risk','wlb','commute'];
  var colors={overall:'#2563eb',competitive:'#3d7a5a',growth:'#4a90e2',risk:'#c15a3a',salary:'#d97706',commute:'#7c3aed',wlb:'#0891b2',culture:'#db2777',stability:'#475569'};
  var NL=String.fromCharCode(10);
  var svg='<svg width="'+size+'" height="'+size+'" viewBox="0 0 '+size+' '+size+'" xmlns="http://www.w3.org/2000/svg">'+NL;
  for(var i=1;i<=levels;i++){
    var rr=r*i/levels,pts=[];
    for(var j=0;j<8;j++){var a=-Math.PI/2+j*2*Math.PI/8;pts.push((cx+rr*Math.cos(a))+','+(cy+rr*Math.sin(a)));}
    svg+='<polygon points="'+pts.join(' ')+'" fill="none" stroke="var(--border)" stroke-width="1"/>'+NL;
  }
  for(var j=0;j<8;j++){var a=-Math.PI/2+j*2*Math.PI/8;svg+='<line x1="'+cx+'" y1="'+cy+'" x2="'+(cx+r*Math.cos(a))+'" y2="'+(cy+r*Math.sin(a))+'" stroke="var(--border)" stroke-width="1"/>'+NL;}
  var dataPts=[],scorePts=[];
  for(var j=0;j<8;j++){
    var k=order[j];var v=Math.max(0,Math.min(10,Number(scores[k])||0));
    var a=-Math.PI/2+j*2*Math.PI/8;var rr=r*v/10;
    var px=cx+rr*Math.cos(a),py=cy+rr*Math.sin(a);
    dataPts.push(px+','+py);scorePts.push({x:px,y:py,k:k,v:v,a:a});
  }
  svg+='<polygon points="'+dataPts.join(' ')+'" fill="rgba(37,99,235,0.15)" stroke="var(--accent)" stroke-width="2"/>'+NL;
  scorePts.forEach(function(p){
    svg+='<circle cx="'+p.x+'" cy="'+p.y+'" r="4" fill="'+(colors[p.k]||'#2563eb')+'"/>'+NL;
    var pad=22,tx=p.x+pad*Math.cos(p.a),ty=p.y+pad*Math.sin(p.a);
    if(Math.abs(Math.sin(p.a))>0.9){ty+=(p.a>0?10:-10);}
    var anchor='middle';
    if(Math.abs(Math.cos(p.a))>0.1){anchor=Math.cos(p.a)>0?'start':'end';}
    svg+='<text x="'+tx+'" y="'+ty+'" text-anchor="'+anchor+'" fill="var(--text)" font-size="11" font-weight="600">'+escHtml(axisNames[p.k])+' '+p.v+'</text>'+NL;
  });
  for(var i=1;i<=levels;i++){svg+='<text x="'+(cx+4)+'" y="'+(cy-r*i/levels+4)+'" fill="var(--muted)" font-size="9">'+(i*2)+'</text>'+NL;}
  svg+='</svg>';
  return svg;
}
// --- salary advice panel ---
var LS_SALARY='jobagent_salary_advice';
var _lastSalaryResult=null;
function _readSalaryHistory(){try{var raw=localStorage.getItem(LS_SALARY);return raw?JSON.parse(raw):[];}catch(e){return [];}}
function _writeSalaryHistory(arr){if(arr.length>20)arr=arr.slice(0,20);localStorage.setItem(LS_SALARY,JSON.stringify(arr));}
// chip 语义缩写：公司去冗余后缀取核心名，职位去通用后缀取核心词，超长截断
function _shortCompany(c){
  if(!c)return'';
  var t=c.replace(/\(.*?\)|（.*?）/g,''); // 去括号内容（如（南通））
  // 去机构后缀（循环，可去掉"有限公司/股份/集团"等多层）
  var _suf=/(有限|股份|公司|集团|控股|实业)/g;
  t=t.replace(_suf,'');
  // 去常见地名（任意位置，品牌核心词通常在地名后）
  var _places=['北京','上海','天津','重庆','江苏','浙江','广东','山东','深圳市','深圳','广州市','广州','南京市','南京','常州市','常州','苏州市','苏州','南通','武汉市','武汉','成都市','成都','杭州市','杭州','合肥','无锡','宁波','西安市','西安','郑州市','郑州','长沙市','长沙','青岛市','青岛','大连'];
  for(var i=0;i<_places.length;i++){t=t.split(_places[i]).join('');}
  t=t.replace(/市$/,''); // 去残留的"市"（如"深圳市"去"深圳"后剩"市"）
  if(!t)t=c;
  // 完整词边界：若仍>8字，截断到常见行业词尾（避免切在词中间）
  if(t.length>8){
    var _tail=['药业','半导体','科技','技术','电子','新能源','智能','装备','材料','汽车','生物','通信','网络','软件','数据','机器人','光电','医疗','食品','金融','地产','能源','化工','制造'];
    var _cut=8;
    for(var j=0;j<_tail.length;j++){var _idx=t.indexOf(_tail[j]);if(_idx>0&&_idx+_tail[j].length>_cut){_cut=_idx+_tail[j].length;}}
    t=t.slice(0,_cut);
  }
  return t;
}
function _shortTitle(t){
  if(!t)return'';
  var s=t.replace(/(工程师|专员|经理|主管|总监|专家|负责人|助理)+$/,''); // 去通用职位后缀
  if(!s)s=t;
  return s.length>8?s.slice(0,8):s;
}
function _salaryDisplayName(o){var i=o.input||o;var v=o.version?'v'+o.version:'';var c=(i.company||'未命名').replace(/\s+/g,'');var t=(i.title||'岗位').replace(/\s+/g,'');return c+'-'+t+(v?'-'+v:'');}
function _salaryFullName(o){var i=o.input||o;var v=o.version?' · v'+o.version:'';var t=i.time?new Date(i.time).toLocaleString('zh-CN',{hour12:false}):'';return (i.company||'未命名')+' · '+(i.title||'岗位')+v+(t?' · '+t:'');}
function loadOfferImportOptions(){
  var sel=document.getElementById('importOfferSel');if(!sel)return;
  fetch('/api/offer/list').then(function(r){return r.json()}).then(function(d){
    var items=(d.items||[]).filter(function(x){return x.name});
    var opts='<option value="">📥 导入已评估Offer...</option>';
    items.forEach(function(x){opts+='<option value="'+escAttr(x.name)+'">'+escHtml(x.company||x.name)+'</option>';});
    sel.innerHTML=opts;
  }).catch(function(){});
}
function importOfferEval(name){
  if(!name)return;
  fetch('/api/offer/preview?file_name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
    var p=d.parsed||{};
    if(p.company)document.getElementById('salaryCompany').value=p.company;
    if(p.title)document.getElementById('salaryTitle').value=p.title;
    if(p.monthly_base)document.getElementById('salaryBase').value=p.monthly_base;
    if(p.pay_months)document.getElementById('salaryMonths').value=p.pay_months;
    if(p.annual_total)document.getElementById('salaryAnnual').value=p.annual_total;
    // 年包以 base×months 为准（两者都有值则重算），annual_total 仅作 fallback
    var _b=document.getElementById('salaryBase').value,_m=document.getElementById('salaryMonths').value;
    if(_b&&_m)calcSalaryAnnual();
    // 直接赋值不触发 input 事件，手动同步生成按钮状态（否则公司已填但按钮仍灰）
    _syncSalaryGenBtn();
    var st=document.getElementById('salaryStatus');if(st)st.textContent='已导入: '+(p.company||name);
  }).catch(function(e){var st=document.getElementById('salaryStatus');if(st)st.textContent='导入失败：'+e.message;});
}
function loadSalaryAdviceHistory(){
  var list=document.getElementById('salaryList');if(!list)return;
  var arr=_readSalaryHistory();var html='';
  if(!arr.length){html='<div style="color:var(--muted);text-align:center;padding:8px 0;font-size:.82rem">暂无记录，生成后自动保存</div>';}
  else{
    arr.forEach(function(o){
      // 当前正在查看的 chip 高亮 + 「● 当前」标识
      var _cur=(_lastSalaryResult&&_lastSalaryResult.id===o.id);
      var _chipStyle='display:inline-flex;align-items:center;gap:4px;padding:5px 8px 5px 10px;background:'+(_cur?'rgba(37,99,235,.1)':'var(--bg)')+';border:1px solid '+(_cur?'var(--accent)':'var(--border)')+';border-radius:14px;cursor:pointer;font-size:.78rem;max-width:none;white-space:nowrap;transition:border-color .2s,background .2s';
      var _curBadge=_cur?'<span style="background:var(--accent);color:#fff;border-radius:10px;padding:0 6px;font-size:.62rem;font-weight:700;line-height:16px">● 当前</span>':'';
      html+='<span data-sid="'+o.id+'" title="'+escHtml(_salaryFullName(o))+'" onclick="restoreSalaryClick(this)" class="salary-chip" style="'+_chipStyle+'" onmouseover="this.style.borderColor=\'var(--accent)\';this.style.background=\'rgba(37,99,235,.12)\';this.querySelector(\'.chip-del\').style.opacity=\'1\'" onmouseout="this.style.borderColor=\''+(_cur?'var(--accent)':'')+'\';this.style.background=\''+(_cur?'rgba(37,99,235,.1)':'')+'\';this.querySelector(\'.chip-del\').style.opacity=\'0\'">'+_curBadge+escHtml(_salaryDisplayName(o))+'<button data-sid="'+o.id+'" onclick="deleteSalaryClick(this);event.stopPropagation()" title="删除该条历史" class="chip-del" style="flex:none;background:#fef2f2;border:1px solid #fecaca;color:#c15a3a;border-radius:50%;width:16px;height:16px;line-height:14px;text-align:center;cursor:pointer;font-size:.62rem;padding:0;opacity:0;transition:opacity .15s">✕</button></span>';
    });
  }
  list.innerHTML=html;
}
function restoreSalaryClick(el){restoreSalary(el.getAttribute('data-sid'));}
function deleteSalaryClick(el){deleteSalary(el.getAttribute('data-sid'));}
function restoreSalary(id){
  var arr=_readSalaryHistory();var o=null;
  for(var i=0;i<arr.length;i++){if(arr[i].id===id){o=arr[i];break;}}
  if(!o)return;
  document.getElementById('salaryCompany').value=o.input.company||'';
  document.getElementById('salaryTitle').value=o.input.title||'';
  document.getElementById('salaryBase').value=o.input.monthly_base||'';
  document.getElementById('salaryMonths').value=o.input.pay_months||'';
  document.getElementById('salaryAnnual').value=o.input.annual_total||'';
  document.getElementById('salaryOffer').value=o.input.salary||'';
  document.getElementById('salaryTarget').value=o.input.target||'';
  document.getElementById('salaryFloor').value=o.input.floor||'';
  document.getElementById('salaryNegotiator').value=o.input.negotiator||'HR';
  document.getElementById('salaryStrengths').value=o.input.strengths||'';
  document.getElementById('salaryContext').value=o.input.context||'';
  _lastSalaryResult=o;
  renderSalaryResult(o.result);
  // 直接赋值不触发 input 事件，手动同步生成按钮状态
  _syncSalaryGenBtn();
  var saveBtn=document.getElementById('salarySaveBtn');if(saveBtn)saveBtn.style.display='inline-block';
  // 重渲染 chip 列表，让「● 当前」高亮跟随当前查看的 chip
  loadSalaryAdviceHistory();
}
function deleteSalary(id){showConfirm('确定删除这条策略记录？',function(){
  var arr=_readSalaryHistory().filter(function(o){return o.id!==id;});
  _writeSalaryHistory(arr);loadSalaryAdviceHistory();
  // 仅当删除的恰好是当前正在显示的记录时才清空页面 —— 删其他 chip 不影响当前内容
  if(_lastSalaryResult&&_lastSalaryResult.id===id){
    _lastSalaryResult=null;
    var _g2=function(i){return document.getElementById(i)};
    ['salaryCompany','salaryTitle','salaryBase','salaryMonths','salaryAnnual','salaryTarget','salaryFloor','salaryOffer','salaryStrengths','salaryContext'].forEach(function(i){_g2(i).value=''});
    var _sr=document.getElementById('salaryResult');if(_sr)_sr.innerHTML='';
    var _sb=document.getElementById('salarySaveBtn');if(_sb)_sb.style.display='none';
  }
});}
function calcSalaryAnnual(){var b=parseFloat(document.getElementById('salaryBase').value)||0;var m=parseFloat(document.getElementById('salaryMonths').value)||0;if(b&&m){document.getElementById('salaryAnnual').value=(b*m);}}
// 清空全部历史策略（带确认，仅清 localStorage，不影响已保存文件）
function clearSalaryHistory(){
  showConfirm('确定清空全部历史策略？此操作不可恢复（已保存的文件不受影响）。',function(){
    localStorage.removeItem(LS_SALARY);
    loadSalaryAdviceHistory();
  });
}
// 清空当前表单+结果+保存按钮（保留历史策略），回到初始态
function clearSalaryPanel(){
  showConfirm('确定清空当前薪资谈判内容？历史策略记录将保留。',function(){
    _lastSalaryResult=null;
    var _g=function(i){return document.getElementById(i)};
    ['salaryCompany','salaryTitle','salaryBase','salaryMonths','salaryAnnual','salaryTarget','salaryFloor','salaryOffer','salaryStrengths','salaryContext'].forEach(function(i){_g(i).value=''});
    var _sr=document.getElementById('salaryResult');if(_sr)_sr.innerHTML='<div style="color:var(--muted);font-size:.85rem;text-align:center;padding:48px 0"><div style="font-size:2.5rem;margin-bottom:10px">💰</div><div style="font-size:.95rem">填写上方谈判信息后点击「⚡ 生成建议」</div><div style="font-size:.78rem;margin-top:4px">输出锚定薪资 / 杠杆点 / 让步计划 / 话术</div></div>';
    var _sb=document.getElementById('salarySaveBtn');if(_sb)_sb.style.display='none';
    _syncSalaryGenBtn();
    var _st=document.getElementById('salaryStatus');if(_st)_st.textContent='';
    // 2026-08-12: 清空后立即重渲染 chip 列表，「● 当前」标识随 _lastSalaryResult=null 同步消失
    loadSalaryAdviceHistory();
  });
}
// 公司为空时禁用「生成建议」按钮（预校验，避免点到才弹窗）
function _syncSalaryGenBtn(){var b=document.getElementById('salaryGenBtn');if(!b)return;var c=document.getElementById('salaryCompany').value.trim();b.disabled=!c;b.style.opacity=c?'':'0.5';b.title=c?'':'请先填写公司';}
(function(){var c=document.getElementById('salaryCompany');if(c)c.addEventListener('input',_syncSalaryGenBtn);_syncSalaryGenBtn();})();
function genSalaryAdvice(){
  var company=document.getElementById('salaryCompany').value.trim();
  if(!company){showModal('请填写公司');return;}
  var btn=document.getElementById('salaryGenBtn');
  var status=document.getElementById('salaryStatus');
  btn.disabled=true;btn.textContent='生成中...';status.textContent='生成中...';var res=document.getElementById('salaryResult');if(res){res.style.opacity='.5';res.style.pointerEvents='none';}
  var _base=document.getElementById('salaryBase').value.trim();
  var _months=document.getElementById('salaryMonths').value.trim();
  var _annual=document.getElementById('salaryAnnual').value.trim();
  var _sal=document.getElementById('salaryOffer').value.trim();
  if(_base&&_months&&!_sal){_sal='月薪'+_base+'k x '+_months+'个月 = 年包'+_annual+'k';}
  var payload={company:company,title:document.getElementById('salaryTitle').value.trim(),salary:_sal,target:document.getElementById('salaryTarget').value.trim(),floor:document.getElementById('salaryFloor').value.trim(),negotiator:document.getElementById('salaryNegotiator').value,monthly_base:_base,pay_months:_months,annual_total:_annual,strengths:document.getElementById('salaryStrengths').value.trim(),context:document.getElementById('salaryContext').value.trim()};
  fetch('/api/salary-advice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
  .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
  .then(function(d){
    // 方案A：同一「公司+职位」覆盖旧记录（id/version 保留，内容+时间更新），否则新增
    var arr=_readSalaryHistory();
    var dupIdx=-1;
    for(var i=0;i<arr.length;i++){var _in=arr[i].input||{};if((_in.company||'')===payload.company&&(_in.title||'')===(payload.title||'')){dupIdx=i;break;}}
    var newId=Date.now().toString(36)+'_'+Math.random().toString(36).slice(2);
    var newRec={input:payload,result:d,time:Date.now(),id:newId,version:1};
    if(dupIdx>=0){
      newRec.id=arr[dupIdx].id;                    // 保留原 id
      newRec.version=(arr[dupIdx].version||1)+1;   // 版本号+1
      arr.splice(dupIdx,1);                        // 移除旧记录
    }
    arr.unshift(newRec);_writeSalaryHistory(arr);
    _lastSalaryResult=newRec;
    renderSalaryResult(d);status.textContent='';if(res){res.style.opacity='';res.style.pointerEvents='';}
    var saveBtn=document.getElementById('salarySaveBtn');if(saveBtn)saveBtn.style.display='inline-block';
    loadSalaryAdviceHistory();
  })
  .catch(function(e){status.textContent='生成失败：'+e.message;})
  .finally(function(){btn.disabled=false;btn.textContent='生成建议';if(res){res.style.opacity='';res.style.pointerEvents='';}});
}
function renderSalaryResult(d){
  var el=document.getElementById('salaryResult');if(!el)return;
  var confMap={high:['高','#3d7a5a'],medium:['中','#d97706'],low:['低','#c15a3a']};
  // Normalize LLM confidence: tolerate med/Medium/High/大写/空格 etc. Unknown -> '-'
  var _c=String(d.confidence||'').trim().toLowerCase();
  if(_c==='med')_c='medium';
  if(_c==='high'||_c==='medium'||_c==='low'){var conf=confMap[_c];}
  else{var conf=['-','#666'];}
  var _confTxt=conf[0], _confBg=conf[1];
  // 锚定薪资 hero 卡
  // Bento 布局：锚定薪资大卡（2/3）+ 置信度/对比小卡（1/3）
  var _inp=(_lastSalaryResult&&_lastSalaryResult.input)||{};
  // 单位解析 → 年包（千元）。支持: 纯数字(81200=81.2k)、万(11.9万=119k)、
  // k(30k=30k)、k*月数(12k*14=168k)、长文本(约11.9万税前=119k)
  function _toK(v){
    if(!v)return 0;
    if(typeof v==='number')return v>=1000?v/1000:v;
    var s=String(v).replace(/[,\s]/g,'');
    var m=s.match(/(\d+\.?\d*)\s*k\s*[×x*]\s*(\d+)/i);
    if(m)return parseFloat(m[1])*parseFloat(m[2]);       // 12k*14 → 168
    var m2=s.match(/(\d+\.?\d*)\s*k/i);
    if(m2)return parseFloat(m2[1]);                       // 30k → 30
    var m3=s.match(/(\d+\.?\d*)\s*万/i);
    if(m3)return parseFloat(m3[1])*10;                    // 11.9万 → 119
    var m4=s.match(/(\d+\.?\d*)/);
    if(m4){var n=parseFloat(m4[1]);return n>=1000?n/1000:n;}
    return 0;
  }
  function _parseK(t){if(!t)return 0;var s=String(t);if(/涨幅|%/.test(s))return 0;return _toK(s);}
  // 年包智能解析：支持纯数字(81200)、万(11.9万)、k(30k)、长文本(约11.9万税前...) —— _toK 返回千元单位
  var _curK=_toK(_inp.annual_total);var _tgt=_parseK(_inp.target);var _flr=_parseK(_inp.floor);
  var _bar=function(l,v,c){if(!v)return '';var _mx=Math.max(_curK,_tgt,_flr,1);return '<div style="display:flex;align-items:center;gap:6px;margin:3px 0"><span style="width:42px;font-size:.72rem;color:var(--muted)">'+l+'</span><div style="flex:1;height:12px;background:var(--bg);border:1px solid var(--border);border-radius:3px;overflow:hidden"><div style="width:'+Math.round(v/_mx*100)+'%;height:100%;background:'+c+'"></div></div><span style="font-size:.72rem;color:var(--muted)">'+(v/10).toFixed(1)+'w</span></div>';};
  var _diff=_tgt&&_curK?'<div style="font-size:.72rem;color:var(--muted);margin-top:4px">目标 vs 当前: '+(Math.round((_tgt-_curK)/_curK*1000)/10)+'%</div>':'';
  // 锚点短化：新数据 anchor 是简洁数字（≤18字），旧数据可能是 LLM 长文本 → 提取数字锚点短显，全文进折叠
  var _anchorRaw=(d.anchor||'').trim();
  function _anchorShort(a){
    if(!a)return'';
    if(a.length<=18)return a;
    var m=a.match(/\d[\d,.]*\s*[Kk万w]?\s*[×x*]?\s*\d*|\d[\d,.]*\s*[Kk万w]/);
    return m?m[0].trim():a.slice(0,18)+'…';
  }
  var _anchorDisplay=_anchorShort(_anchorRaw);
  var _rationaleText=(d.rationale||'') || (_anchorRaw.length>18?_anchorRaw:'');
  var html='<div style="display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px">';
  html+='<div style="background:linear-gradient(135deg,rgba(37,99,235,.08),rgba(61,122,90,.08));border:1px solid var(--border);border-radius:10px;padding:20px;display:flex;flex-direction:column;justify-content:center">';
  html+='<div style="font-size:.75rem;color:var(--muted);margin-bottom:6px">🎯 锚定薪资（建议开口）</div>';
  html+='<div style="font-size:2.5rem;font-weight:800;color:var(--text);line-height:1.2">'+escHtml(_anchorDisplay||'-')+'</div>';
  if(_rationaleText){html+='<details style="margin-top:6px"><summary style="cursor:pointer;font-size:.72rem;color:var(--muted)">锚定理由</summary><div style="font-size:.78rem;color:var(--muted);line-height:1.6;margin-top:4px;white-space:pre-wrap">'+escHtml(_rationaleText)+'</div></details>';}
  html+='</div>';
  html+='<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;display:flex;flex-direction:column;justify-content:center">';
  html+='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><span style="font-size:.75rem;color:var(--muted)">置信度</span><span style="display:inline-block;background:'+_confBg+';color:#fff;padding:3px 14px;border-radius:12px;font-weight:700;font-size:.8rem">'+escHtml(_confTxt)+'</span></div>';
  if(_curK)html+='<div style="font-size:.72rem;color:var(--muted);margin-bottom:4px">薪资对比（年包·万元）</div>'+_bar('底线',_flr,'#c15a3a')+_bar('当前',_curK,'#475569')+_bar('目标',_tgt,'#3d7a5a')+_diff;
  else html+='<div style="font-size:.75rem;color:var(--muted);text-align:center;padding:12px 0">填写薪酬信息后显示对比</div>';
  html+='</div></div>';
  function block(title,items,color,isScript,numbered){
    var h='<div style="background:'+color+'1a;border:1px solid '+color+'59;border-radius:8px;padding:12px;display:flex;flex-direction:column">';
    h+='<div style="font-weight:700;color:'+color+';margin-bottom:8px">'+title+'</div><ul style="margin:0;padding-left:14px;font-size:.82rem;line-height:1.6;flex:1">';
    (items||[]).forEach(function(x,idx){h+='<li style="display:flex;align-items:flex-start;gap:6px;margin-bottom:4px">'+(numbered?'<span style="flex:none;display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;background:'+color+';color:#fff;border-radius:50%;font-size:.68rem;margin-top:2px">'+(idx+1)+'</span>':'')+'<span style="flex:1">'+escHtml(typeof x==='object'?(x&&x.text?x.text:JSON.stringify(x)):x)+'</span>'+(isScript?'<button data-idx="'+idx+'" onclick="copySalaryScript(this)" title="复制话术" style="flex:none;background:transparent;border:1.5px solid '+color+'59;color:'+color+';border-radius:4px;padding:2px 8px;cursor:pointer;font-size:.72rem;font-weight:600;transition:background .2s,box-shadow .2s" onmouseover="this.style.background=\''+color+'22\';this.style.boxShadow=\'0 1px 4px rgba(0,0,0,.15)\'" onmouseout="this.style.background=\'transparent\';this.style.boxShadow=\'none\'">📋 复制</button>':'')+'</li>';});
    if(!(items&&items.length))h+='<li style="color:var(--muted)">暂无</li>';
    h+='</ul></div>';
    return h;
  }
  html+='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));grid-auto-rows:auto;gap:12px">';
  html+=block('🛡 杠杆点',d.leverage,'#3d7a5a');
  html+=block('🪜 让步计划',d.concessions,'#d97706',false,true);
  html+=block('💬 话术',d.scripts,'#2563eb',true);
  html+='</div>';
  el.innerHTML=html;
}
function copySalaryScript(btn){var idx=btn.getAttribute('data-idx');var s=(_lastSalaryResult&&_lastSalaryResult.result&&_lastSalaryResult.result.scripts)||[];var t=s[idx]||'';if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t);}else{var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);}btn.textContent='✓';setTimeout(function(){btn.textContent='📋';},1200);}
function saveSalaryAdvice(){
  if(!_lastSalaryResult){showModal('请先生成建议');return;}
  var status=document.getElementById('salaryStatus');if(status)status.textContent='保存中...';
  var res=_lastSalaryResult.result;var p=_lastSalaryResult.input;
  var payload={company:p.company,title:p.title,salary:p.salary,target:p.target,floor:p.floor||'',negotiator:p.negotiator||'',anchor:res.anchor||'',leverage:res.leverage||[],concessions:res.concessions||[],scripts:res.scripts||[],confidence:res.confidence||''};
  fetch('/api/salary-advice/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
  .then(function(resp){if(!resp.ok)throw new Error('HTTP '+resp.status);return resp.json();})
  .then(function(d){if(status)status.textContent='已保存: '+escHtml(d.file_name||'');})
  .catch(function(e){if(status)status.textContent='保存失败: '+e.message;});
}
</script></body></html>"""

# Inline the vendored markdown/sanitizer libs so the dashboard works fully
# offline with no third-party CDN dependency (and no CDN supply-chain surface).
# When a vendor file is missing the CDN <script> tag is kept as-is.
_marked_inline = _inline_vendor_js("marked.min.js")
_purify_inline = _inline_vendor_js("purify.min.js")
if _marked_inline:
    HTML = HTML.replace(
        '<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>',
        "<script>" + _marked_inline + "</script>",
    )
if _purify_inline:
    HTML = HTML.replace(
        '<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>',
        "<script>" + _purify_inline + "</script>",
    )

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
SwaggerUIBundle({url:"/api/openapi.json",dom_id:"#swagger-ui"});
</script>
</body></html>"""

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "JobAgent API",
        "description": (
            "Job tracking, LLM matching, materials, mock-interview, offer "
            "evaluation and salary negotiation API for the job-seeking AI "
            "agent. This spec is intentionally partial; the full route list "
            "lives in the Handler.do_GET/do_POST/do_DELETE dispatchers in "
            "serve.py (30+ endpoints)."
        ),
        "version": "1.0.0",
    },
    "servers": [{"url": "http://localhost:8765", "description": "Local dashboard server"}],
    "paths": {
        "/api/results": {
            "get": {
                "summary": "List jobs (paginated, filterable)",
                "description": "Return job listings. Without pagination params, returns flat array (legacy). With page/page_size, returns paginated envelope with all_platforms.",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                    {
                        "name": "page_size",
                        "in": "query",
                        "schema": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    {"name": "platform", "in": "query", "schema": {"type": "string"}},
                    {"name": "company", "in": "query", "schema": {"type": "string"}},
                    {"name": "title", "in": "query", "schema": {"type": "string"}},
                    {"name": "location", "in": "query", "schema": {"type": "string"}},
                    {
                        "name": "user_flag",
                        "in": "query",
                        "schema": {
                            "type": "string",
                            "enum": ["interested", "rejected", "unmarked"],
                        },
                    },
                ],
                "responses": {
                    "200": {"description": "Job list (flat array or paginated envelope)"},
                    "401": {"description": "Unauthorized (missing/invalid token)"},
                },
            }
        },
        "/api/flag/{job_id}": {
            "post": {
                "summary": "Flag a job as interested/rejected or clear flag",
                "description": "Manually mark a job for LLM matching (interested), skip (rejected), or clear. Only 'interested' jobs are fed to the LLM match stage when match_flagged_only is True.",
                "parameters": [
                    {
                        "name": "job_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "flag",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "enum": ["interested", "rejected", "clear"]},
                    },
                ],
                "responses": {
                    "200": {"description": "Flag updated"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/match/run": {
            "post": {
                "summary": "Run LLM matching on user-flagged (interested) jobs",
                "description": "Loads all jobs with user_flag='interested', runs match.match_jobs (max 30), persists to match_results. Returns flagged/matched/skipped counts.",
                "responses": {
                    "200": {"description": "Match summary"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/offer/evaluate": {
            "post": {
                "summary": "Evaluate a job offer",
                "description": "Mode 1: {file_name} reads offers/<file>, LLM-parses 17 fields, packs into evaluate(), caches to offer_evaluations. Mode 2: {company, title, ...} evaluates directly.",
                "responses": {
                    "200": {"description": "Evaluation result (8 scores + pros/cons/levers)"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/match": {
            "get": {
                "summary": "List LLM match results (paginated)",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                    {
                        "name": "page_size",
                        "in": "query",
                        "schema": {"type": "integer", "maximum": 500},
                    },
                    {
                        "name": "min_score",
                        "in": "query",
                        "schema": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                ],
                "responses": {
                    "200": {"description": "Paginated match results"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/jd/fetch": {
            "post": {
                "summary": "Fetch full JD for user-flagged (interested) jobs",
                "description": "Loads jobs with user_flag='interested' (max 20), calls each platform's fetch_full_jd, updates the description field.",
                "responses": {
                    "200": {"description": "{fetched, skipped, failed} summary"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/materials/generate": {
            "post": {
                "summary": "Generate resume + HR message + interview-prep drafts",
                "description": "Body {job_ids:[...]} (max 10). Each job: enrich JD, tailor resume, cover letter, predict interview questions. Drafts land in material_drafts (审核台), confirmed later via /api/materials/confirm.",
                "responses": {
                    "200": {"description": "{succeeded, failed, total}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/applications": {
            "get": {
                "summary": "List applications joined with job info",
                "responses": {
                    "200": {"description": "Application list"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/application/update": {
            "post": {
                "summary": "Update application status (with timeline audit)",
                "description": "Body {id, status, notes?}. Identifies by application primary key id, writes a timelines row when status changes.",
                "responses": {
                    "200": {"description": "{ok, id, status}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/resumes": {
            "get": {
                "summary": "List uploaded resume files with default marker",
                "responses": {
                    "200": {"description": "{items, default}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/resume/upload": {
            "post": {
                "summary": "Upload a resume text file",
                "description": "Body {name, content, set_default?}. Saves to resumes/, optionally registers as default direction in config.yaml.",
                "responses": {
                    "200": {"description": "{ok, name, size, registered_default}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/files": {
            "get": {
                "summary": "List generated files (catalog-driven)",
                "responses": {
                    "200": {"description": "Generated file list with type/job association"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/mock-interview/start": {
            "post": {
                "summary": "Start a mock interview session",
                "description": "Body {job_id, from_prep?, focus?, difficulty?}. Returns session_id; the opening turn is fetched via /api/mock-interview/reply.",
                "responses": {
                    "200": {"description": "{ok, session_id, note, job_title, job_company}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/mock-interview/reply": {
            "post": {
                "summary": "Stream one mock-interview turn (SSE)",
                "description": "Body {session_id, text?}. Returns text/event-stream with delta/turn_end/end/error events.",
                "responses": {
                    "200": {"description": "SSE event stream"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/mock-interview/end": {
            "post": {
                "summary": "End a mock interview session and save transcript/assessment",
                "description": "Body {session_id}.",
                "responses": {
                    "200": {"description": "{ok, md, assessment?}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/mock-interview/abandon": {
            "post": {
                "summary": "Abandon a mock interview session without saving files",
                "description": "Body {session_id}.",
                "responses": {
                    "200": {"description": "{ok}"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/salary-advice": {
            "post": {
                "summary": "Generate salary negotiation advice",
                "description": "Body {company, title?, salary?, target?, floor?, negotiator?, strengths?, context?, monthly_base?, pay_months?, annual_total?}.",
                "responses": {
                    "200": {
                        "description": "{anchor, rationale, leverage, concessions, scripts, confidence}"
                    },
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/openapi.json": {
            "get": {
                "summary": "OpenAPI specification (partial)",
                "responses": {"200": {"description": "OpenAPI 3.0 JSON spec"}},
            }
        },
    },
}
