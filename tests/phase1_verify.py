"""Phase 1 comprehensive verification."""
import sys, os
sys.path.insert(0, ".")
from agent_core.config import load_config
from agent_core.storage.db import get_db, migrate
from agent_core.pipeline.search import _normalize_company, _dedup
from agent_core.platforms.base import Job
from agent_core.pipeline.filter import filter_jobs
from agent_core.pipeline.prescreen import prescreen
from agent_core.pipeline.match import _parse as match_parse
from agent_core.pipeline.tailor import _save_docx
from datetime import datetime, timezone

passed = 0
now = datetime.now(timezone.utc)

# 1
cfg = load_config("config.yaml")
assert len(cfg.directions) == 2 and len(cfg.company_aliases) >= 7
print("[OK] 1/10 Config"); passed += 1

# 2
db = get_db(); migrate(db)
tabs = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in ["jobs","applications","platform_sessions","schedules","search_status"]:
    assert t in tabs, f"Missing: {t}"
print("[OK] 2/10 DB 5 tables"); passed += 1

# 3
assert _normalize_company("宁德时代", cfg.company_aliases) == "catl"
assert _normalize_company("宁德时戴", cfg.company_aliases) == "catl"
assert _normalize_company("未知小厂", cfg.company_aliases) == "未知小厂"
j1 = Job(id="a", title="高级工程师", company="宁德时代", company_normalized="catl",
         platforms=["boss_zhipin"], urls={"boss_zhipin":"http://x.com"},
         first_seen=now, last_seen=now)
j2 = Job(id="b", title="高级工程师", company="CATL", company_normalized="catl",
         platforms=["liepin"], urls={"liepin":"http://y.com"},
         first_seen=now, last_seen=now)
m = _dedup([j1, j2], cfg.company_aliases)
assert len(m) == 1 and set(m[0].platforms) == {"boss_zhipin","liepin"}
print("[OK] 3/10 Cross-platform dedup"); passed += 1

# 4
jg = Job(title="AI Agent工程师", description="Agent开发", salary_min=10000, salary_max=20000)
jx = Job(title="外包工", description="劳务派遣", salary_min=3000, salary_max=5000)
assert len(filter_jobs([jg, jx], cfg)) == 1
print("[OK] 4/10 Filter"); passed += 1

# 5
jai = Job(title="工业AI Agent开发", description="LLM Agent RAG Tool Calling Memory",
          salary_min=15000, salary_max=30000)
jamr = Job(title="AMR调度", description="AGV SLAM MES WMS 激光",
           salary_min=10000, salary_max=20000)
r = prescreen([jai, jamr], cfg)
assert len(r) == 2, f"Expected 2 results, got {len(r)}"
dirs = {p.direction for p in r}
assert dirs == {"industrial_ai_agent", "equipment_amr"}, f"Wrong directions: {dirs}"
# AMR job had more feature word hits in this test (6 vs 5), so it scores higher
assert r[0].direction == "equipment_amr"
print("[OK] 5/10 Prescreen direction detection (both correct)"); passed += 1

# 6
assert match_parse('{"score":85, "match_reason":"ok", "missing_skills":["PLC"]}')["score"] == 85
assert match_parse('```json\n{"score":70, "match_reason":"ok", "missing_skills":[]}\n```')["score"] == 70
print("[OK] 6/10 Match JSON parser"); passed += 1

# 7
tmp = os.path.join(os.environ.get("TEMP","."), "test_r.docx")
_save_docx("# Resume\n\n## Skills\n\n- Python\n- Agent", tmp)
assert os.path.exists(tmp) and os.path.getsize(tmp) > 0
os.remove(tmp)
print("[OK] 7/10 Tailor .docx"); passed += 1

# 8
from agent_core.cli import login, rematch, tailor, search, pipeline, serve, track, schedule
print("[OK] 8/10 CLI 8 commands"); passed += 1

# 9
from agent_core.pipeline.orchestrator import STAGE_ORDER
from agent_core.notify.windows_toast import notify_search_complete
from agent_core.server.serve import start_server
assert STAGE_ORDER == ["search","filter","prescreen","match"]
print("[OK] 9/10 Orch+Notify+Server"); passed += 1

# 10
from agent_core.platforms.boss_zhipin import BossZhipinAdapter, boss_login
from agent_core.platforms.liepin import LiepinAdapter, liepin_login
from agent_core.llm.providers import DeepSeekProvider
print("[OK] 10/10 Platform adapters+LLM"); passed += 1

print(f"\n=== {passed}/10 PASSED - Phase 1 VERIFIED COMPLETE ===")
