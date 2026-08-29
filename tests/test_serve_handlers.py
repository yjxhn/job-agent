"""Behavioral tests for serve POST handlers (T5-1).

Covers /api/flag/{job_id} (real DB update) and /api/materials/confirm
(confirm -> save + catalog + auto-create application), which previously had
no handler-level tests (only bare-SQL replicas).
"""

import io
import json
from unittest.mock import MagicMock, patch

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate


def _mk_handler(db_path, path="/api/x"):
    h = serve.Handler.__new__(serve.Handler)
    h.db_path = db_path
    h.path = path
    h.headers = {"Content-Length": "0"}
    h.wfile = io.BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    return h


def _seed_job(conn, job_id="j1", title="工程师", company="ACME"):
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "first_seen, last_seen, platforms, urls) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            title,
            company,
            company,
            "苏州",
            "default",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            '["byd"]',
            '{"byd":"http://x"}',
        ),
    )
    conn.commit()


def _body(h):
    return json.loads(h.wfile.getvalue())


# ---------------------------------------------------------------- flag -------


def test_flag_job_interested(tmp_path):
    db = str(tmp_path / "f.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    conn.close()

    h = _mk_handler(db, path="/api/flag/j1?flag=interested")
    h._api_flag_job("/api/flag/j1")
    assert _body(h)["ok"] is True

    conn = get_db(db)
    row = conn.execute("SELECT user_flag FROM jobs WHERE id='j1'").fetchone()
    conn.close()
    assert row["user_flag"] == "interested"


def test_flag_job_rejected_then_clear(tmp_path):
    db = str(tmp_path / "f2.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    conn.close()

    h = _mk_handler(db, path="/api/flag/j1?flag=rejected")
    h._api_flag_job("/api/flag/j1")
    h2 = _mk_handler(db, path="/api/flag/j1?flag=clear")
    h2._api_flag_job("/api/flag/j1")

    conn = get_db(db)
    row = conn.execute("SELECT user_flag FROM jobs WHERE id='j1'").fetchone()
    conn.close()
    assert row["user_flag"] == ""


def test_flag_job_invalid_flag_rejected(tmp_path):
    db = str(tmp_path / "f3.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    conn.close()

    h = _mk_handler(db, path="/api/flag/j1?flag=bogus")
    h._api_flag_job("/api/flag/j1")
    assert _body(h)["error"] == "flag must be one of: interested, rejected, clear"


# ------------------------------------------------------- materials confirm ---


def test_materials_confirm_creates_application(tmp_path):
    """Confirm -> status confirmed, resume+hr cataloged, application auto-created."""
    db = str(tmp_path / "m.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="m1")
    conn.execute(
        "INSERT INTO material_drafts (job_id, resume_md, hr_message, status, version, "
        "created_at, updated_at) VALUES ('m1', '# 简历', 'HR你好', 'draft', 1, "
        "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    h = _mk_handler(db)
    with (
        patch("agent_core.storage.db.get_db", return_value=get_db(db)),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "m1"}),
        patch(
            "agent_core.pipeline.tailor.save_resume",
            return_value={"md": "o/m1.md", "docx": "o/m1.docx"},
        ),
        patch(
            "agent_core.pipeline.cover_letter.save_cover_letter",
            return_value="o/m1_hrmsg.md",
        ),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_materials_confirm()
        conn = get_db(db)
        draft = conn.execute("SELECT status FROM material_drafts WHERE job_id='m1'").fetchone()
        app = conn.execute("SELECT status FROM applications WHERE job_id='m1'").fetchone()
        conn.close()

    assert draft["status"] == "confirmed"
    assert app is not None and app["status"] == "待投递"
    # 2x tailored (md+docx) + 1x cover letter; interview branch skipped (no prep md)
    assert mock_catalog.call_count == 3


def test_materials_confirm_missing_draft_ok_false(tmp_path):
    db = str(tmp_path / "m2.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="m2")
    conn.close()

    h = _mk_handler(db)
    with (
        patch("agent_core.storage.db.get_db", return_value=get_db(db)),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "m2"}),
    ):
        h._api_materials_confirm()
    assert _body(h)["ok"] is False


# ------------------------------------------------- application update / reminder ---


def _seed_application(conn, app_id=1, job_id="j1", status="已投递"):
    conn.execute(
        "INSERT INTO applications (id, job_id, status, applied_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (app_id, job_id, status, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()


def test_application_update_writes_status_and_timeline(tmp_path):
    db = str(tmp_path / "app.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    _seed_application(conn)
    conn.close()

    h = _mk_handler(db)
    with (
        patch("agent_core.storage.db.get_db", return_value=get_db(db)),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"id": 1, "status": "HR已读"},
        ),
    ):
        h._api_application_update()

    assert _body(h)["ok"] is True
    conn = get_db(db)
    row = conn.execute("SELECT status FROM applications WHERE id=1").fetchone()
    tl = conn.execute("SELECT COUNT(*) AS c FROM timelines WHERE application_id=1").fetchone()
    conn.close()
    assert row["status"] == "HR已读"
    assert tl["c"] == 1


def test_application_update_missing_fields(tmp_path):
    db = str(tmp_path / "app2.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    _seed_application(conn)
    conn.close()

    h = _mk_handler(db)
    with patch("agent_core.server.serve._read_json_body", return_value={"id": 1}):
        h._api_application_update()
    assert _body(h)["ok"] is False


def test_application_reminder_saves_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler("unused")
    with patch("agent_core.server.serve._read_json_body", return_value={"days": 5}):
        h._api_application_reminder()
    assert _body(h)["ok"] is True
    state = json.loads((tmp_path / "data" / "scheduler_state.json").read_text(encoding="utf-8"))
    assert state["reminder_days"] == 5


def test_materials_progress_state_roundtrip():
    """生成求职材料进度存储可写入并复位，前端轮询不会读到陈旧 running 状态。"""
    serve._set_materials_progress(
        running=True,
        done=1,
        total=3,
        current="设备工程师 @ 测试公司",
        status="正在生成简历/HR消息...",
    )
    assert serve._MATERIALS_PROGRESS["running"] is True
    assert serve._MATERIALS_PROGRESS["done"] == 1
    assert serve._MATERIALS_PROGRESS["total"] == 3
    serve._set_materials_progress(running=False, done=0, total=0, current="", status="")
    assert serve._MATERIALS_PROGRESS["running"] is False
    assert serve._MATERIALS_PROGRESS["done"] == 0


# ------------------------------------------------------- more GET handlers ---


def test_api_files_returns_empty_list(tmp_path, monkeypatch):
    db = str(tmp_path / "files.db")
    h = _mk_handler(db, path="/api/files")
    monkeypatch.setattr(serve, "_scan_output_dir", lambda: [])
    h._api_files()
    assert _body(h) == {"items": [], "total": 0}


def test_api_realtime_config_returns_config(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/realtime/config")
    h._api_realtime_config()
    d = _body(h)
    assert "enabled" in d
    assert "ws_port" in d


def test_api_materials_jobs_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "materials_jobs.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/materials/jobs")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_materials_jobs()
    assert _body(h) == []


def test_api_pipeline_returns_summary(tmp_path, monkeypatch):
    db = str(tmp_path / "pipeline.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="p1", title="设备工程师", company="测试公司")
    conn.execute(
        "INSERT INTO pipeline_runs (stage, job_count, created_at) VALUES ('search', 1, ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/pipeline")
    monkeypatch.setattr(serve, "_scan_output_dir", lambda: [])
    h._api_pipeline()
    d = _body(h)
    assert d["stages"]["search"]["count"] == 1
    assert "search_status" in d


def test_api_materials_delete_removes_draft(tmp_path, monkeypatch):
    db = str(tmp_path / "mat_delete.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="md1", title="工程师", company="ACME")
    conn.execute(
        "INSERT INTO material_drafts (job_id, status, version, created_at, updated_at) "
        "VALUES ('md1', 'draft', 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    with patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["md1"]}):
        h._api_materials_delete()
    assert _body(h)["deleted"] == 1
    conn = get_db(db)
    n = conn.execute("SELECT COUNT(*) FROM material_drafts WHERE job_id='md1'").fetchone()[0]
    conn.close()
    assert n == 0


def test_api_flag_batch_updates_jobs(tmp_path):
    db = str(tmp_path / "flag_batch.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="f1")
    _seed_job(conn, job_id="f2")
    conn.close()
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"ids": ["f1", "f2"], "flag": "interested"},
    ):
        h._api_flag_batch()
    assert _body(h)["ok"] is True
    conn = get_db(db)
    rows = conn.execute("SELECT user_flag FROM jobs WHERE id IN ('f1','f2')").fetchall()
    conn.close()
    assert all(r[0] == "interested" for r in rows)


def test_api_flag_batch_invalid_flag(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"ids": ["f1"], "flag": "bad"}
    ):
        h._api_flag_batch()
    assert _body(h)["error"] == "flag must be interested, rejected, or clear"


def test_api_offer_preview_parses_file(tmp_path, monkeypatch):
    db = str(tmp_path / "offer_preview.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("公司名: ACME\n职位名: 工程师\n月薪base: 15K\n", encoding="utf-8")
    h = _mk_handler(db, path="/api/offer/preview?file_name=a.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_offer_preview({"file_name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["parsed"]["company"] == "ACME"


def test_api_offer_delete_ok(tmp_path, monkeypatch):
    db = str(tmp_path / "offer_delete.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(db, path="/api/offer?file_name=a.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_offer_delete({"file_name": ["a.txt"]})
    assert _body(h)["ok"] is True
    assert not (offers / "a.txt").exists()


def test_api_offer_upload_ok(tmp_path, monkeypatch):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_offers_dir", lambda: str(tmp_path / "offers"))
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"name": "a.txt", "content": "hello"},
    ):
        h._api_offer_upload()
    d = _body(h)
    assert d["ok"] is True
    assert (tmp_path / "offers" / "a.txt").exists()


def test_api_offer_upload_missing_name(tmp_path, monkeypatch):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"content": "hello"}):
        h._api_offer_upload()
    assert _body(h)["error"] == "Missing 'name'"


def test_api_file_content_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "output"
    out.mkdir()
    (out / "a.md").write_text("# hi", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/file?path=a.md")
    h._api_file_content({"path": ["a.md"]})
    d = _body(h)
    assert d["path"] == "a.md"
    assert "# hi" in d["content"]


def test_api_file_content_missing_path(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/file")
    h._api_file_content({"path": [""]})
    assert _body(h)["error"] == "Missing path parameter"


def test_api_file_content_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/file?path=../secret")
    h._api_file_content({"path": ["../secret"]})
    assert _body(h)["error"] == "Access denied"


def test_api_materials_jobs_with_row(tmp_path, monkeypatch):
    db = str(tmp_path / "materials_jobs2.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="mj1", title="工程师", company="ACME")
    conn.execute(
        "INSERT INTO material_drafts (job_id, status, version, created_at, updated_at) "
        "VALUES ('mj1', 'draft', 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/materials/jobs")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_materials_jobs()
    items = _body(h)
    assert len(items) == 1
    assert items[0]["id"] == "mj1"


def test_api_materials_drafts_with_row(tmp_path, monkeypatch):
    db = str(tmp_path / "drafts2.db")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="d1", title="工程师", company="ACME")
    conn.execute(
        "INSERT INTO material_drafts (job_id, status, version, created_at, updated_at) "
        "VALUES ('d1', 'draft', 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=draft")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_materials_drafts()
    d = _body(h)
    assert d["ok"] is True
    assert len(d["items"]) == 1


def test_api_materials_drafts_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "drafts.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=draft")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_materials_drafts()
    d = _body(h)
    assert d["ok"] is True
    assert d["items"] == []


def test_api_applications_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "apps.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/applications")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_applications()
    d = _body(h)
    assert d["ok"] is True
    assert d["items"] == []


def test_api_match_empty(tmp_path):
    db = str(tmp_path / "match.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/match?page=1&page_size=10")
    h._api_match({"page": ["1"], "page_size": ["10"]})
    d = _body(h)
    assert d["items"] == []
    assert d["total"] == 0


def test_api_results_empty_paginated(tmp_path, monkeypatch):
    db = str(tmp_path / "results.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/results?page=1&page_size=10")
    monkeypatch.setattr(serve, "_cached_all_platforms", lambda: set())
    h._api_results({"page": ["1"], "page_size": ["10"]})
    d = _body(h)
    assert d["items"] == []
    assert d["total"] == 0


def test_api_offer_list_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "offer_list.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/offer/list")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(tmp_path / "offers"))
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))
    h._api_offer_list()
    d = _body(h)
    assert d["items"] == []
