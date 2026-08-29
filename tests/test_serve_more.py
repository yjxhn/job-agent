"""Additional low-level helper and HTTP handler tests for serve.py.

These tests focus on previously under-covered helpers/methods:
offer eval packing/parsing, output scanning, platform cache, resume
management, JD fetch/view/manual, match feedback/listing, offer
template/preview/delete, file zip/delete/content, application delete,
and the background application reminder loop.
"""

import asyncio
import builtins
import io
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mk_handler(db_path=None, path="/api/x"):
    """Build a minimal Handler without invoking BaseHTTPRequestHandler init."""
    h = serve.Handler.__new__(serve.Handler)
    h.db_path = db_path
    h.path = path
    h.headers = {"Content-Length": "0"}
    h.rfile = io.BytesIO()
    h.wfile = io.BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    return h


def _body(h):
    return json.loads(h.wfile.getvalue())


def _temp_db(tmp_path, name="t.db"):
    db = str(tmp_path / name)
    conn = get_db(db)
    migrate(conn)
    conn.close()
    return db


def _seed_job(
    conn, job_id="j1", title="工程师", company="ACME", user_flag="", description="", platforms=None
):
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "first_seen, last_seen, platforms, urls, description, user_flag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            title,
            company,
            company,
            "苏州",
            "default",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            json.dumps(platforms if platforms is not None else ["boss_zhipin"]),
            "{}",
            description,
            user_flag,
        ),
    )
    conn.commit()


def _seed_application(conn, app_id=1, job_id="j1"):
    conn.execute(
        "INSERT INTO applications (id, job_id, status, applied_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (app_id, job_id, "已投递", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO timelines (application_id, from_status, to_status, created_at) "
        "VALUES (?, '未投递', '已投递', '2026-01-01T00:00:00')",
        (app_id,),
    )
    conn.commit()


def _project_cfg_path():
    return str(Path(serve.__file__).resolve().parent.parent.parent / "config.yaml")


class _CfgFile:
    """Minimal in-memory file stand-in for config.yaml read/write tests."""

    def __init__(self, text=""):
        self._buf = io.StringIO(text)
        self.written = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self._buf.read(size)

    def write(self, s):
        self.written = (self.written or "") + s
        return len(s)


def _install_fake_config(monkeypatch, cfg_text):
    """Patch config.yaml existence + open() so helper methods touch no real file.

    Returns a dict whose 'last' item is the most recently opened fake file and
    'written' mirrors the latest write-mode file content.
    """
    cfg_path = _project_cfg_path()
    real_isfile = os.path.isfile
    real_open = builtins.open
    state = {"last": None, "written": None}

    def fake_isfile(path):
        if path == cfg_path:
            return True
        return real_isfile(path)

    def fake_open(file, mode="r", encoding=None, **kwargs):
        if file == cfg_path:
            if "w" in mode or "a" in mode or "+" in mode:
                f = _CfgFile("")
                state["written"] = None
            else:
                f = _CfgFile(cfg_text)
            state["last"] = f
            return f
        return real_open(file, mode, encoding=encoding, **kwargs)

    monkeypatch.setattr(serve.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(builtins, "open", fake_open)
    return state


def _make_offers(tmp_path):
    offers = tmp_path / "offers"
    offers.mkdir(exist_ok=True)
    return offers


# ---------------------------------------------------------------------------
# _pack_offer_eval_input
# ---------------------------------------------------------------------------


def test_pack_offer_eval_input_partial():
    parsed = {"company": "ACME", "monthly_base": "15K"}
    out = serve._pack_offer_eval_input(parsed)
    assert out["company"] == "ACME"
    assert out["salary"] == "月薪base=15K"
    assert out["bonus"] == ""
    assert out["benefits"] == ""
    assert out["notes"] == ""


def test_pack_offer_eval_input_full():
    parsed = {
        "company": "ACME",
        "title": "工程师",
        "location": "苏州",
        "offer_type": "正式",
        "level": "P6",
        "join_date": "2026-03-01",
        "monthly_base": "15K",
        "pay_months": "12",
        "annual_total": "30W",
        "year_end_months": "3",
        "sign_bonus": "5W",
        "equity": "1000股",
        "social_insurance": "全额",
        "probation": "6个月",
        "work_mode": "现场",
        "overtime_travel": "少",
        "non_compete": "1年",
        "notice_period": "30天",
        "perks": "餐补",
        "hr_contact": "HR",
        "notes": "备注",
    }
    out = serve._pack_offer_eval_input(parsed)
    assert out["company"] == "ACME"
    assert out["title"] == "工程师"
    assert out["location"] == "苏州"
    assert out["salary"] == "月薪base=15K, 发放12个月, 年总包=30W"
    assert out["bonus"] == "年终奖3个月, 签字费=5W, 期权/RSU=1000股"
    assert out["benefits"] == "五险一金:全额; 福利:餐补"
    assert "Offer类型:正式" in out["notes"]
    assert "入职日期:2026-03-01" in out["notes"]
    assert "试用期:6个月" in out["notes"]
    assert "工作模式:现场" in out["notes"]
    assert "加班/出差/调岗:少" in out["notes"]
    assert "竞业协议:1年" in out["notes"]
    assert "离职通知期:30天" in out["notes"]
    assert "HR联系方式:HR" in out["notes"]
    assert out["notes"].endswith(" | 备注")


# ---------------------------------------------------------------------------
# _parse_offer_fields
# ---------------------------------------------------------------------------


async def _run_parse_offer_fields(txt, llm_response):
    provider = MagicMock()
    config = SimpleNamespace(llm=SimpleNamespace(max_tokens=123))

    # The function imports call_llm_with_retry inside itself, so patch the
    # module attribute directly.
    async def fake_call(*args, **kwargs):
        return llm_response

    with patch("agent_core.llm.providers.call_llm_with_retry", side_effect=fake_call):
        return await serve._parse_offer_fields(provider, config, txt)


def test_parse_offer_fields_json_fence():
    result = asyncio.run(
        _run_parse_offer_fields(
            "ACME 15K",
            '```json\n{"company":"ACME","title":"工程师","monthly_base":"15K",}\n```',
        )
    )
    assert result["company"] == "ACME"
    assert result["title"] == "工程师"
    assert result["monthly_base"] == "15K"
    assert result["location"] == ""


def test_parse_offer_fields_plain_fence():
    result = asyncio.run(
        _run_parse_offer_fields(
            "ACME",
            '```\n{"company":"ACME","notes":"hello",}\n```',
        )
    )
    assert result["company"] == "ACME"
    assert result["notes"] == "hello"
    assert result["title"] == ""


# ---------------------------------------------------------------------------
# _scan_output_dir
# ---------------------------------------------------------------------------


def test_scan_output_dir_catalog_existing(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "cat.db")
    out = tmp_path / "output"
    out.mkdir()
    (out / "a.md").write_text("# hi", encoding="utf-8")
    conn = get_db(db)
    _seed_job(conn, job_id="j1")
    conn.execute(
        "INSERT INTO generated_files (job_id, file_type, file_name, file_path, size, created_at, "
        "direction, company, job_title) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "j1",
            "cover_letter",
            "a.md",
            str(out / "a.md"),
            5,
            "2026-01-01 00:00:00",
            "d",
            "ACME",
            "工程师",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    items = serve._scan_output_dir(str(out))
    assert len(items) == 1
    assert items[0]["name"] == "a.md"
    assert items[0]["type"] == "cover_letter"
    assert items[0]["job_id"] == "j1"


def test_scan_output_dir_catalog_missing_falls_back(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "cat_missing.db")
    out = tmp_path / "output"
    out.mkdir()
    (out / "b.md").write_text("# hi", encoding="utf-8")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO generated_files (job_id, file_type, file_name, file_path, size, created_at, "
        "direction, company, job_title) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            None,
            "tailor_resume",
            "ghost.md",
            str(tmp_path / "output" / "ghost.md"),
            5,
            "2026-01-01 00:00:00",
            "",
            "",
            "",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    items = serve._scan_output_dir(str(out))
    assert len(items) == 1
    assert items[0]["name"] == "b.md"
    assert items[0]["type"] == "tailor_resume"


def test_scan_output_dir_fallback_directory_scan(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "empty_cat.db")
    out = tmp_path / "output"
    out.mkdir()
    (out / "b_cover.md").write_text("# cover", encoding="utf-8")
    monkeypatch.setattr(serve.Handler, "db_path", db)
    items = serve._scan_output_dir(str(out))
    assert len(items) == 1
    assert items[0]["name"] == "b_cover.md"
    assert items[0]["type"] == "cover_letter"
    assert items[0]["job_id"] is None


def test_scan_output_dir_non_existent_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(serve.Handler, "db_path", None)
    assert serve._scan_output_dir(str(tmp_path / "nope")) == []


def test_scan_output_dir_oserror(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(serve.Handler, "db_path", None)
    monkeypatch.setattr(serve.os, "listdir", lambda _p: (_ for _ in ()).throw(OSError("boom")))
    assert serve._scan_output_dir(str(out)) == []


# ---------------------------------------------------------------------------
# _infer_file_type
# ---------------------------------------------------------------------------


def test_infer_file_type_mock_interview():
    assert serve._infer_file_type("job_mock_interview.md") == "mock_interview"


def test_infer_file_type_cover_letter():
    assert serve._infer_file_type("job_cover_letter.md") == "cover_letter"


def test_infer_file_type_interview_prep():
    assert serve._infer_file_type("job_interview_prep.md") == "interview_prep"


def test_infer_file_type_tailor_resume():
    assert serve._infer_file_type("job_resume.md") == "tailor_resume"


# ---------------------------------------------------------------------------
# _cached_all_platforms
# ---------------------------------------------------------------------------


def _reset_platforms_cache():
    serve._platforms_cache = None


def test_cached_all_platforms_cache_hit(monkeypatch):
    _reset_platforms_cache()
    serve._platforms_cache = {"boss"}
    try:
        assert serve._cached_all_platforms() == {"boss"}
    finally:
        _reset_platforms_cache()


def test_cached_all_platforms_list_parse(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "plat_list.db")
    conn = get_db(db)
    _seed_job(conn, job_id="p1", platforms=["boss_zhipin", "liepin"])
    _seed_job(conn, job_id="p2", platforms=["boss_zhipin"])
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    _reset_platforms_cache()
    assert serve._cached_all_platforms() == {"boss_zhipin", "liepin"}
    assert serve._cached_all_platforms() == {"boss_zhipin", "liepin"}  # cached
    _reset_platforms_cache()


def test_cached_all_platforms_string_parse(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "plat_str.db")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "first_seen, last_seen, platforms, urls) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("s1", "T", "C", "C", "L", "d", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "boss", "{}"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    _reset_platforms_cache()
    assert serve._cached_all_platforms() == {"boss"}
    _reset_platforms_cache()


def test_cached_all_platforms_invalid_json(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "plat_bad.db")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "first_seen, last_seen, platforms, urls) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "bad1",
            "T",
            "C",
            "C",
            "L",
            "d",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "???",
            "{}",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    _reset_platforms_cache()
    assert serve._cached_all_platforms() == {"???"}
    _reset_platforms_cache()


def test_cached_all_platforms_exception(monkeypatch):
    _reset_platforms_cache()
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    with patch.object(serve.logger, "warning") as mock_warn:
        assert serve._cached_all_platforms() == set()
    assert mock_warn.called
    assert serve._platforms_cache is None
    _reset_platforms_cache()


def test_cached_all_platforms_empty_not_cached(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "plat_empty.db")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "first_seen, last_seen, platforms, urls) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("e1", "T", "C", "C", "L", "d", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "[]", "{}"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(serve.Handler, "db_path", db)
    _reset_platforms_cache()
    assert serve._cached_all_platforms() == set()
    assert serve._platforms_cache is None
    _reset_platforms_cache()


# ---------------------------------------------------------------------------
# _api_clear_results / _api_clear_match
# ---------------------------------------------------------------------------


def test_api_clear_results_success(tmp_path):
    db = _temp_db(tmp_path, "clear_results.db")
    conn = get_db(db)
    _seed_job(conn, job_id="c1")
    conn.execute(
        "INSERT INTO search_status (search_id, platform, status, created_at) VALUES ('s','p','done','2026-01-01')"
    )
    conn.execute(
        "INSERT INTO pipeline_runs (stage, job_count, created_at) VALUES ('search', 1, '2026-01-01')"
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/results")
    h._api_clear_results()
    assert _body(h)["ok"] is True
    conn = get_db(db)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM search_status").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 0
    conn.close()


def test_api_clear_results_exception(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    with patch.object(serve, "sqlite3") as mock_sqlite3:
        mock_sqlite3.connect.side_effect = RuntimeError("db down")
        h._api_clear_results()
    d = _body(h)
    assert d["error"] == "Clear failed: db down"


def test_api_clear_match_success(tmp_path):
    db = _temp_db(tmp_path, "clear_match.db")
    conn = get_db(db)
    _seed_job(conn, job_id="m1")
    conn.execute(
        "INSERT INTO match_results (job_id, match_score, created_at) VALUES ('m1', 90, '2026-01-01')"
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/match")
    h._api_clear_match()
    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] == 1
    conn = get_db(db)
    assert conn.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 0
    conn.close()


def test_api_clear_match_exception(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    with patch.object(serve, "sqlite3") as mock_sqlite3:
        mock_sqlite3.connect.side_effect = RuntimeError("db down")
        h._api_clear_match()
    assert _body(h)["error"] == "Clear failed: db down"


# ---------------------------------------------------------------------------
# _api_list_resumes
# ---------------------------------------------------------------------------


def test_api_list_resumes_dir_listing(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.md").write_text("a", encoding="utf-8")
    (resumes / "b.txt").write_text("b", encoding="utf-8")
    (resumes / "ignored.docx").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resumes")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_read_default_resume_name", lambda: "b.txt")
    h._api_list_resumes()
    d = _body(h)
    assert [i["name"] for i in d["items"]] == ["a.md", "b.txt"]
    assert d["default"] == "b.txt"


def test_api_list_resumes_default_from_config(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.md").write_text("a", encoding="utf-8")
    (resumes / "b.txt").write_text("b", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resumes")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_read_default_resume_name", lambda: "b.txt")
    h._api_list_resumes()
    assert _body(h)["default"] == "b.txt"


def test_api_list_resumes_missing_default_falls_back(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.md").write_text("a", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resumes")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_read_default_resume_name", lambda: "missing.txt")
    h._api_list_resumes()
    assert _body(h)["default"] == "a.md"


def test_api_list_resumes_empty(tmp_path, monkeypatch):
    resumes = tmp_path / "empty_resumes"
    resumes.mkdir()
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resumes")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_read_default_resume_name", lambda: None)
    h._api_list_resumes()
    assert _body(h) == {"items": [], "default": None}


# ---------------------------------------------------------------------------
# _read_default_resume_name
# ---------------------------------------------------------------------------


def test_read_default_resume_name_with_config(monkeypatch):
    cfg = """
search:
  directions:
    default:
      resume_file: resumes/default.txt
"""
    state = _install_fake_config(monkeypatch, cfg)
    h = _mk_handler()
    assert h._read_default_resume_name() == "default.txt"
    assert state["last"] is not None


def test_read_default_resume_name_without_config(monkeypatch):
    cfg_path = _project_cfg_path()
    monkeypatch.setattr(
        serve.os.path, "isfile", lambda p: False if p == cfg_path else os.path.isfile(p)
    )
    h = _mk_handler()
    assert h._read_default_resume_name() is None


def test_read_default_resume_name_missing_file(monkeypatch):
    # "missing file" is the no-config branch; config.yaml absent returns None.
    monkeypatch.setattr(serve.os.path, "isfile", lambda p: False)
    h = _mk_handler()
    assert h._read_default_resume_name() is None


def test_read_default_resume_name_yaml_import_error(monkeypatch):
    _install_fake_config(monkeypatch, "search: {}\n")
    monkeypatch.setitem(sys.modules, "yaml", None)
    h = _mk_handler()
    assert h._read_default_resume_name() is None


# ---------------------------------------------------------------------------
# _api_delete_resume
# ---------------------------------------------------------------------------


def test_api_delete_resume_missing_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_delete_resume("/api/resume", {})
    assert _body(h)["error"] == "Missing 'name' query param"


def test_api_delete_resume_invalid_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_delete_resume("/api/resume", {"name": [".."]})
    assert _body(h)["error"] == "Invalid filename"


def test_api_delete_resume_delete_existing(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resume")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_clear_default_resume_if_matches", lambda filename: None)
    h._api_delete_resume("/api/resume", {"name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] is True
    assert not (resumes / "a.txt").exists()


def test_api_delete_resume_not_exists(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resume")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_clear_default_resume_if_matches", lambda filename: None)
    h._api_delete_resume("/api/resume", {"name": ["ghost.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] is False


def test_api_delete_resume_config_cleanup_exception(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/resume")
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))

    def boom(filename):
        raise RuntimeError("config fail")

    monkeypatch.setattr(h, "_clear_default_resume_if_matches", boom)
    with patch.object(serve.logger, "warning") as mock_warn:
        h._api_delete_resume("/api/resume", {"name": ["a.txt"]})
    assert _body(h)["ok"] is True
    assert mock_warn.called


# ---------------------------------------------------------------------------
# _clear_default_resume_if_matches
# ---------------------------------------------------------------------------


def test_clear_default_resume_if_matches_yaml_missing(monkeypatch):
    cfg_path = _project_cfg_path()
    monkeypatch.setattr(
        serve.os.path, "isfile", lambda p: False if p == cfg_path else os.path.isfile(p)
    )
    h = _mk_handler()
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(Path("unused")))
    # Should simply return without raising.
    assert h._clear_default_resume_if_matches("a.txt") is None


def test_clear_default_resume_if_matches_match_with_remaining(tmp_path, monkeypatch):
    cfg = """
search:
  directions:
    default:
      resume_file: resumes/a.txt
"""
    state = _install_fake_config(monkeypatch, cfg)
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "b.md").write_text("b", encoding="utf-8")
    h = _mk_handler()
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    h._clear_default_resume_if_matches("a.txt")
    assert state["last"].written is not None
    assert "b.md" in state["last"].written


def test_clear_default_resume_if_matches_match_no_remaining(tmp_path, monkeypatch):
    cfg = """
search:
  directions:
    default:
      resume_file: resumes/a.txt
"""
    state = _install_fake_config(monkeypatch, cfg)
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    h = _mk_handler()
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    h._clear_default_resume_if_matches("a.txt")
    assert state["last"].written is not None
    assert "default" not in state["last"].written


def test_clear_default_resume_if_matches_no_match(tmp_path, monkeypatch):
    cfg = """
search:
  directions:
    default:
      resume_file: resumes/b.md
"""
    state = _install_fake_config(monkeypatch, cfg)
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("a", encoding="utf-8")
    h = _mk_handler()
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    h._clear_default_resume_if_matches("a.txt")
    assert state["written"] is None


# ---------------------------------------------------------------------------
# _api_resume_preview
# ---------------------------------------------------------------------------


def test_api_resume_preview_missing_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_resume_preview({})
    assert _body(h)["error"] == "Missing 'name' query param"


def test_api_resume_preview_invalid(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_resume_preview({"name": [".."]})
    assert _body(h)["error"] == "Invalid filename"


def test_api_resume_preview_not_found(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    h = _mk_handler(str(tmp_path / "x.db"))
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    h._api_resume_preview({"name": ["nope.txt"]})
    assert _body(h)["error"] == "Resume not found"


def test_api_resume_preview_read_exception(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    with patch("builtins.open", side_effect=OSError("read fail")):
        h._api_resume_preview({"name": ["a.txt"]})
    assert _body(h)["error"] == "Read failed: read fail"


def test_api_resume_preview_success(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("我的简历", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    h._api_resume_preview({"name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["content"] == "我的简历"
    assert d["size"] == 4


# ---------------------------------------------------------------------------
# _api_resume_set_default
# ---------------------------------------------------------------------------


def test_api_resume_set_default_invalid_length(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "0"
    h._api_resume_set_default()
    assert _body(h)["error"] == "Invalid content length"


def test_api_resume_set_default_invalid_json(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_resume_set_default()
    assert _body(h)["error"] == "Invalid JSON body"


def test_api_resume_set_default_missing_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"name": "   "}):
        h._api_resume_set_default()
    assert _body(h)["error"] == "Missing 'name'"


def test_api_resume_set_default_sanitize_extension(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_register_resume_in_config", lambda name: True)
    with patch("agent_core.server.serve._read_json_body", return_value={"name": "a"}):
        h._api_resume_set_default()
    d = _body(h)
    assert d["ok"] is True
    assert d["default"] == "a.txt"


def test_api_resume_set_default_not_found(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    with patch("agent_core.server.serve._read_json_body", return_value={"name": "missing.txt"}):
        h._api_resume_set_default()
    assert _body(h)["error"] == "Resume not found"


def test_api_resume_set_default_config_exception(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))

    def boom(name):
        raise RuntimeError("cfg boom")

    monkeypatch.setattr(h, "_register_resume_in_config", boom)
    with patch("agent_core.server.serve._read_json_body", return_value={"name": "a.txt"}):
        h._api_resume_set_default()
    assert _body(h)["error"] == "Config update failed: cfg boom"


def test_api_resume_set_default_success(tmp_path, monkeypatch):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    (resumes / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(resumes))
    monkeypatch.setattr(h, "_register_resume_in_config", lambda name: True)
    with patch("agent_core.server.serve._read_json_body", return_value={"name": "a.txt"}):
        h._api_resume_set_default()
    d = _body(h)
    assert d["ok"] is True
    assert d["registered"] is True


# ---------------------------------------------------------------------------
# _api_resume_upload
# ---------------------------------------------------------------------------


def test_api_resume_upload_invalid_length(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "0"
    h._api_resume_upload()
    assert _body(h)["error"] == "Invalid content length (1B-5MB allowed)"


def test_api_resume_upload_missing_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"content": "hello"}):
        h._api_resume_upload()
    assert _body(h)["error"] == "Missing 'name'"


def test_api_resume_upload_missing_content(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"name": "a.txt", "content": "  "}
    ):
        h._api_resume_upload()
    assert _body(h)["error"] == "Missing 'content'"


def test_api_resume_upload_sanitize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(tmp_path / "resumes"))
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"name": "a", "content": "hello"}
    ):
        h._api_resume_upload()
    d = _body(h)
    assert d["ok"] is True
    assert d["name"] == "a.txt"
    assert (tmp_path / "resumes" / "a.txt").exists()


def test_api_resume_upload_set_default_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(tmp_path / "resumes"))
    monkeypatch.setattr(h, "_register_resume_in_config", lambda name: True)
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"name": "a.txt", "content": "hello", "set_default": True},
    ):
        h._api_resume_upload()
    d = _body(h)
    assert d["registered_default"] is True


def test_api_resume_upload_set_default_config_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    monkeypatch.setattr(h, "_resumes_dir", lambda: str(tmp_path / "resumes"))

    def boom(name):
        raise RuntimeError("cfg boom")

    monkeypatch.setattr(h, "_register_resume_in_config", boom)
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"name": "a.txt", "content": "hello", "set_default": True},
    ):
        h._api_resume_upload()
    d = _body(h)
    assert d["ok"] is True
    assert d["registered_default"] is False


# ---------------------------------------------------------------------------
# _register_resume_in_config
# ---------------------------------------------------------------------------


def test_register_resume_in_config_success(monkeypatch):
    cfg = "search: {}\n"
    state = _install_fake_config(monkeypatch, cfg)
    h = _mk_handler()
    assert h._register_resume_in_config("new.txt") is True
    assert state["last"].written is not None
    assert "resumes/new.txt" in state["last"].written


def test_register_resume_in_config_missing_config(monkeypatch):
    cfg_path = _project_cfg_path()
    monkeypatch.setattr(
        serve.os.path, "isfile", lambda p: False if p == cfg_path else os.path.isfile(p)
    )
    h = _mk_handler()
    assert h._register_resume_in_config("new.txt") is False


def test_register_resume_in_config_import_error(monkeypatch):
    _install_fake_config(monkeypatch, "search: {}\n")
    monkeypatch.setitem(sys.modules, "yaml", None)
    h = _mk_handler()
    assert h._register_resume_in_config("new.txt") is False


# ---------------------------------------------------------------------------
# _api_jd_fetch
# ---------------------------------------------------------------------------


def _patch_get_db(monkeypatch, db):
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: get_db(db))


def _patch_jd_fetch_deps(monkeypatch, enrich=None, config=None):
    if config is None:
        config = MagicMock()
    monkeypatch.setattr("agent_core.config.load_config", lambda: config)
    if enrich is not None:
        monkeypatch.setattr("agent_core.pipeline.enrichment.enrich_job_jd", enrich)


def test_api_jd_fetch_no_rows(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_no.db")
    _patch_get_db(monkeypatch, db)
    _patch_jd_fetch_deps(monkeypatch)
    h = _mk_handler(db, path="/api/jd/fetch")
    h._api_jd_fetch()
    d = _body(h)
    assert d["ok"] is True
    assert d["fetched"] == 0
    assert d["failed"] == 0


def test_api_jd_fetch_too_many_rows(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_many.db")
    conn = get_db(db)
    for i in range(21):
        _seed_job(conn, job_id=f"j{i:02d}", user_flag="interested")
    conn.close()
    _patch_get_db(monkeypatch, db)
    _patch_jd_fetch_deps(monkeypatch)
    h = _mk_handler(db, path="/api/jd/fetch")
    h._api_jd_fetch()
    d = _body(h)
    assert d["error"] == "单次最多抓取 20 个岗位的 JD，当前 21 个，请减少标记后再试"


def test_api_jd_fetch_query_exception(tmp_path, monkeypatch):
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("query fail")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: conn)
    monkeypatch.setattr("agent_core.config.load_config", lambda: MagicMock())
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/jd/fetch")
    h._api_jd_fetch()
    assert _body(h)["error"] == "Failed to query jobs"


def test_api_jd_fetch_skip_when_already_full(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_skip.db")
    conn = get_db(db)
    long_desc = "JD: " + "x" * 300
    _seed_job(conn, job_id="full1", user_flag="interested", description=long_desc)
    conn.close()
    _patch_get_db(monkeypatch, db)
    called = []

    async def should_not_call(*args, **kwargs):
        called.append(True)
        return SimpleNamespace(description="longer")

    _patch_jd_fetch_deps(monkeypatch, enrich=should_not_call)
    h = _mk_handler(db, path="/api/jd/fetch")
    h._api_jd_fetch()
    d = _body(h)
    assert d["fetched"] == 0
    assert d["skipped"] == 1
    assert d["failed"] == 0
    assert called == []


def test_api_jd_fetch_success(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_ok.db")
    conn = get_db(db)
    _seed_job(conn, job_id="ok1", user_flag="interested", description="short")
    conn.close()
    _patch_get_db(monkeypatch, db)
    long_desc = "JD: " + "full JD text " * 20

    async def enrich(job, config):
        return SimpleNamespace(description=long_desc)

    _patch_jd_fetch_deps(monkeypatch, enrich=enrich)
    h = _mk_handler(db, path="/api/jd/fetch")
    h._api_jd_fetch()
    d = _body(h)
    assert d["fetched"] == 1
    assert d["failed"] == 0
    conn = get_db(db)
    row = conn.execute("SELECT description FROM jobs WHERE id='ok1'").fetchone()
    conn.close()
    assert row["description"] == long_desc


def test_api_jd_fetch_exception(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_fail.db")
    conn = get_db(db)
    _seed_job(conn, job_id="fail1", user_flag="interested", description="short")
    conn.close()
    _patch_get_db(monkeypatch, db)

    async def boom(job, config):
        raise RuntimeError("enrich fail")

    _patch_jd_fetch_deps(monkeypatch, enrich=boom)
    h = _mk_handler(db, path="/api/jd/fetch")
    h._api_jd_fetch()
    d = _body(h)
    assert d["fetched"] == 0
    assert d["failed"] == 1


# ---------------------------------------------------------------------------
# _api_jd_view
# ---------------------------------------------------------------------------


def test_api_jd_view_success(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_view.db")
    conn = get_db(db)
    _seed_job(conn, job_id="v1", user_flag="interested", description="JD: 详细JD")
    conn.close()
    _patch_get_db(monkeypatch, db)
    h = _mk_handler(db, path="/api/jd/view")
    h._api_jd_view()
    d = _body(h)
    assert d["ok"] is True
    assert d["jobs"][0]["jd"] == "详细JD"


def test_api_jd_view_query_exception(tmp_path, monkeypatch):
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("query fail")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: conn)
    h = _mk_handler(str(tmp_path / "x.db"), path="/api/jd/view")
    h._api_jd_view()
    assert _body(h)["error"] == "Failed to query jobs"


# ---------------------------------------------------------------------------
# _api_jd_manual
# ---------------------------------------------------------------------------


def test_api_jd_manual_invalid_length(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "0"
    h._api_jd_manual()
    assert _body(h)["error"] == "Invalid content length"


def test_api_jd_manual_invalid_json(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_jd_manual()
    assert _body(h)["error"] == "Invalid JSON"


def test_api_jd_manual_missing_fields(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}):
        h._api_jd_manual()
    assert _body(h)["error"] == "缺少 job_id 或 JD 内容"


def test_api_jd_manual_job_not_found(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_manual_missing.db")
    _patch_get_db(monkeypatch, db)
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"job_id": "nope", "jd": "JD"}
    ):
        h._api_jd_manual()
    assert _body(h)["error"] == "岗位不存在: nope"


def test_api_jd_manual_db_exception(tmp_path, monkeypatch):
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("db fail")
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda: conn)
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"job_id": "j1", "jd": "JD"}
    ):
        h._api_jd_manual()
    assert _body(h)["error"] == "保存失败: db fail"


def test_api_jd_manual_success(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "jd_manual_ok.db")
    conn = get_db(db)
    _seed_job(conn, job_id="m1")
    conn.close()
    _patch_get_db(monkeypatch, db)
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"job_id": "m1", "jd": "完整JD"}
    ):
        h._api_jd_manual()
    d = _body(h)
    assert d["ok"] is True
    conn = get_db(db)
    row = conn.execute("SELECT description FROM jobs WHERE id='m1'").fetchone()
    conn.close()
    assert row["description"] == "JD: 完整JD"


# ---------------------------------------------------------------------------
# _api_match_feedback
# ---------------------------------------------------------------------------


def test_api_match_feedback_invalid_feedback(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"job_id": "j1", "feedback_type": "bad"},
    ):
        h._api_match_feedback()
    assert _body(h)["error"] == "feedback_type must be too_high or too_low"


def test_api_match_feedback_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body", return_value={"feedback_type": "too_high"}
    ):
        h._api_match_feedback()
    assert _body(h)["error"] == "job_id is required"


def test_api_match_feedback_invalid_length(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "0"
    h._api_match_feedback()
    assert _body(h)["error"] == "Invalid content length"


def test_api_match_feedback_success(tmp_path):
    db = _temp_db(tmp_path, "feedback.db")
    conn = get_db(db)
    _seed_job(conn, job_id="f1", user_flag="interested")
    conn.close()
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"job_id": "f1", "feedback_type": "too_low", "note": "低估"},
    ):
        h._api_match_feedback()
    d = _body(h)
    assert d["ok"] is True
    assert d["total_feedback"] == 1
    conn = get_db(db)
    row = conn.execute("SELECT feedback_type, direction FROM match_feedback").fetchone()
    conn.close()
    assert row["feedback_type"] == "too_low"
    assert row["direction"] == "default"


def test_api_clear_match_feedback_empty(tmp_path):
    db = _temp_db(tmp_path, "clear_feedback_empty.db")
    h = _mk_handler(db)
    h._api_clear_match_feedback()
    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] == 0


def test_api_clear_match_feedback_success(tmp_path):
    db = _temp_db(tmp_path, "clear_feedback.db")
    conn = get_db(db)
    _seed_job(conn, job_id="f1", user_flag="interested")
    conn.execute(
        "INSERT INTO match_feedback (job_id, direction, feedback_type, note, created_at) "
        "VALUES ('f1', 'default', 'too_low', '低估', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO match_feedback (job_id, direction, feedback_type, note, created_at) "
        "VALUES ('f1', 'default', 'too_high', '高估', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    h = _mk_handler(db)
    h._api_clear_match_feedback()
    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] == 2

    conn = get_db(db)
    n = conn.execute("SELECT COUNT(*) FROM match_feedback").fetchone()[0]
    conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# _api_match
# ---------------------------------------------------------------------------


def _seed_match(conn, job_id, score, missing_skills="[]", strengths="[]"):
    conn.execute(
        "INSERT INTO match_results (job_id, match_score, missing_skills, strengths, created_at) "
        "VALUES (?,?,?,?,?)",
        (job_id, score, missing_skills, strengths, "2026-01-01T00:00:00"),
    )
    conn.commit()


def test_api_match_empty(tmp_path):
    db = _temp_db(tmp_path, "match_empty.db")
    h = _mk_handler(db, path="/api/match?page=1&page_size=10")
    h._api_match({"page": ["1"], "page_size": ["10"]})
    d = _body(h)
    assert d["items"] == []
    assert d["total"] == 0


def test_api_match_with_rows(tmp_path):
    db = _temp_db(tmp_path, "match_rows.db")
    conn = get_db(db)
    _seed_job(conn, job_id="r1")
    _seed_match(conn, "r1", 88, '["python"]', '["沟通"]')
    conn.close()
    h = _mk_handler(db, path="/api/match?page=1&page_size=10")
    h._api_match({"page": ["1"], "page_size": ["10"]})
    d = _body(h)
    assert d["total"] == 1
    assert d["items"][0]["missing_skills"] == ["python"]
    assert d["items"][0]["strengths"] == ["沟通"]


def test_api_match_min_score_filter(tmp_path):
    db = _temp_db(tmp_path, "match_min.db")
    conn = get_db(db)
    _seed_job(conn, job_id="hi")
    _seed_job(conn, job_id="lo")
    _seed_match(conn, "hi", 90)
    _seed_match(conn, "lo", 50)
    conn.close()
    h = _mk_handler(db, path="/api/match?page=1&page_size=10")
    h._api_match({"page": ["1"], "page_size": ["10"], "min_score": ["60"]})
    d = _body(h)
    assert d["total"] == 1
    assert d["items"][0]["job_id"] == "hi"


def test_api_match_invalid_json_fields(tmp_path):
    db = _temp_db(tmp_path, "match_badjson.db")
    conn = get_db(db)
    _seed_job(conn, job_id="bj")
    _seed_match(conn, "bj", 70, "not-json", "also-bad")
    conn.close()
    h = _mk_handler(db, path="/api/match?page=1&page_size=10")
    h._api_match({"page": ["1"], "page_size": ["10"]})
    d = _body(h)
    assert d["items"][0]["missing_skills"] == []
    assert d["items"][0]["strengths"] == []


# ---------------------------------------------------------------------------
# _api_offer_template / preview / delete
# ---------------------------------------------------------------------------


def test_api_offer_template_headers_and_body():
    h = _mk_handler()
    h._api_offer_template()
    h.send_response.assert_called_once_with(200)
    h.send_header.assert_any_call("Content-Type", "text/plain; charset=utf-8")
    h.send_header.assert_any_call(
        "Content-Disposition", 'attachment; filename="offer_template.txt"'
    )
    assert h.wfile.getvalue() == serve.OFFER_TEMPLATE_TXT.encode("utf-8")


def test_api_offer_preview_missing_file_name(tmp_path, monkeypatch):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_offer_preview({})
    assert _body(h)["error"] == "missing file_name"


def test_api_offer_preview_invalid_path(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_invalid.db")
    offers = _make_offers(tmp_path)
    h = _mk_handler(db, path="/api/offer/preview?file_name=../x")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_preview({"file_name": ["../x"]})
    assert _body(h)["error"] == "invalid file path"


def test_api_offer_preview_cached_row(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_cache.db")
    offers = _make_offers(tmp_path)
    (offers / "a.txt").write_text("公司名: ACME\n职位名: 工程师\n", encoding="utf-8")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO offer_evaluations (offer_file_name, offer_file_path, company, title, "
        "parsed_fields, eval_input, result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "a.txt",
            str(offers / "a.txt"),
            "ACME",
            "工程师",
            '{"company":"ACME"}',
            '{"salary":"15K"}',
            '{"overall_score":8}',
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/offer/preview?file_name=a.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_preview({"file_name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["parsed"] == {"company": "ACME"}
    assert d["eval_input"] == {"salary": "15K"}
    assert d["result"] == {"overall_score": 8}
    assert "公司名" in d["raw_text"]


def test_api_offer_preview_no_cached_row_with_file(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_parse.db")
    offers = _make_offers(tmp_path)
    (offers / "a.txt").write_text("公司名: ACME\n职位名: 工程师\n月薪bas: 15K\n", encoding="utf-8")
    h = _mk_handler(db, path="/api/offer/preview?file_name=a.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_preview({"file_name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["parsed"]["company"] == "ACME"
    assert d["parsed"]["title"] == "工程师"
    assert d["parsed"]["monthly_base"] == "15K"


def test_api_offer_preview_no_file(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_nofile.db")
    offers = _make_offers(tmp_path)
    h = _mk_handler(db, path="/api/offer/preview?file_name=ghost.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_preview({"file_name": ["ghost.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["parsed"] == {}
    assert d["raw_text"] == ""


def test_api_offer_delete_missing_file_name(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_offer_delete({})
    assert _body(h)["error"] == "missing file_name"


def test_api_offer_delete_invalid_path(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_del_invalid.db")
    offers = _make_offers(tmp_path)
    h = _mk_handler(db, path="/api/offer?file_name=../x")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_delete({"file_name": ["../x"]})
    assert _body(h)["error"] == "invalid file path"


def test_api_offer_delete_success(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "offer_del.db")
    offers = _make_offers(tmp_path)
    (offers / "a.txt").write_text("x", encoding="utf-8")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO offer_evaluations (offer_file_name, offer_file_path, company, title, "
        "parsed_fields, eval_input, result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "a.txt",
            str(offers / "a.txt"),
            "",
            "",
            "{}",
            "{}",
            "{}",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/offer?file_name=a.txt")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    _patch_get_db(monkeypatch, db)
    h._api_offer_delete({"file_name": ["a.txt"]})
    assert _body(h)["ok"] is True
    assert not (offers / "a.txt").exists()
    conn = get_db(db)
    n = conn.execute("SELECT COUNT(*) FROM offer_evaluations").fetchone()[0]
    conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# _api_files_zip
# ---------------------------------------------------------------------------


def test_api_files_zip_missing_names(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"names": []}):
        h._api_files_zip()
    assert _body(h)["error"] == "缺少 names"


def test_api_files_zip_valid_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.txt").write_text("hello", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"names": ["a.txt"]}):
        h._api_files_zip()
    data = h.wfile.getvalue()
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["a.txt"]


def test_api_files_zip_traversal_skip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h.headers["Content-Length"] = "10"
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"names": ["../secret.txt", "a.txt"]},
    ):
        h._api_files_zip()
    data = h.wfile.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["a.txt"]


# ---------------------------------------------------------------------------
# _api_delete_application
# ---------------------------------------------------------------------------


def test_api_delete_application_missing_id(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_delete_application({})
    assert _body(h)["error"] == "Missing id"


def test_api_delete_application_success(tmp_path, monkeypatch):
    db = _temp_db(tmp_path, "app_del.db")
    conn = get_db(db)
    _seed_job(conn, job_id="a1")
    _seed_application(conn, app_id=1, job_id="a1")
    conn.close()
    h = _mk_handler(db, path="/api/application")
    _patch_get_db(monkeypatch, db)
    h._api_delete_application({"id": ["1"]})
    d = _body(h)
    assert d["ok"] is True
    conn = get_db(db)
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM timelines").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# _api_delete_file
# ---------------------------------------------------------------------------


def test_api_delete_file_missing_path(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_delete_file({})
    assert _body(h)["error"] == "Missing path"


def test_api_delete_file_denied(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_delete_file({"path": ["../secret"]})
    assert _body(h)["error"] == "Access denied"


def test_api_delete_file_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.md").write_text("# hi", encoding="utf-8")
    db = _temp_db(tmp_path, "file_del.db")
    conn = get_db(db)
    conn.execute(
        "INSERT INTO generated_files (job_id, file_type, file_name, file_path, size, created_at) "
        "VALUES (NULL,'tailor_resume','a.md',?,5,'2026-01-01')",
        (str(tmp_path / "output" / "a.md"),),
    )
    conn.commit()
    conn.close()
    h = _mk_handler(db, path="/api/file")
    _patch_get_db(monkeypatch, db)
    h._api_delete_file({"path": ["a.md"]})
    assert _body(h)["ok"] is True
    assert not (tmp_path / "output" / "a.md").exists()
    conn = get_db(db)
    assert conn.execute("SELECT COUNT(*) FROM generated_files").fetchone()[0] == 0
    conn.close()


def test_api_delete_file_oserror(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.md").write_text("# hi", encoding="utf-8")
    db = _temp_db(tmp_path, "file_del_err.db")
    h = _mk_handler(db, path="/api/file")
    _patch_get_db(monkeypatch, db)
    with (
        patch.object(serve.os, "remove", side_effect=OSError("locked")),
        patch.object(serve.logger, "warning") as mock_warn,
    ):
        h._api_delete_file({"path": ["a.md"]})
    assert _body(h)["ok"] is True
    assert mock_warn.called


# ---------------------------------------------------------------------------
# _api_file_content
# ---------------------------------------------------------------------------


def test_api_file_content_missing_path(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": [""]})
    assert _body(h)["error"] == "Missing path parameter"


def test_api_file_content_denied(tmp_path):
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["../secret"]})
    assert _body(h)["error"] == "Access denied"


def test_api_file_content_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["ghost.md"]})
    assert _body(h)["error"] == "File not found"


def test_api_file_content_md_normal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.md").write_text("# hi\nline2\n", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.md"]})
    d = _body(h)
    assert d["path"] == "a.md"
    assert d["content"] == "# hi\nline2\n"


def test_api_file_content_md_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.md").write_text("# hi\nline2\n", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.md"], "download": ["1"]})
    assert h.wfile.getvalue() == b"# hi\r\nline2\r\n"
    assert h.send_response.called


def test_api_file_content_html_normal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.html").write_text("<html></html>", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.html"]})
    d = _body(h)
    assert d["is_html"] is True
    assert "<html></html>" in d["content"]


def test_api_file_content_html_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.html").write_text("<html></html>", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.html"], "download": ["1"]})
    assert h.wfile.getvalue() == b"<html></html>"
    assert h.send_response.called


def test_api_file_content_txt_normal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.txt").write_text("plain", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.txt"]})
    d = _body(h)
    assert d["content"] == "plain"


def test_api_file_content_txt_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.txt").write_text("plain", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.txt"], "download": ["1"]})
    assert h.wfile.getvalue() == b"plain"
    assert h.send_response.called


def test_api_file_content_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.docx").write_bytes(b"\x50\x4b\x03\x04binary")
    h = _mk_handler(str(tmp_path / "x.db"))
    h._api_file_content({"path": ["a.docx"]})
    assert h.wfile.getvalue() == b"\x50\x4b\x03\x04binary"
    assert h.send_response.called


# ---------------------------------------------------------------------------
# _application_reminder_loop / thread starter
# ---------------------------------------------------------------------------


def test_application_reminder_loop_one_iteration(tmp_path, monkeypatch):
    mock_config = MagicMock()
    mock_conn = MagicMock()
    check_calls = []
    monkeypatch.setattr("agent_core.config.load_config", lambda: mock_config)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: mock_conn)

    def fake_check(config, conn):
        check_calls.append((config, conn))

    monkeypatch.setattr("agent_core.scheduler.scheduler.check_application_reminders", fake_check)
    monkeypatch.setattr(serve.time, "sleep", lambda _s: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        serve._application_reminder_loop(str(tmp_path / "app.db"))
    assert len(check_calls) == 1
    assert mock_conn.close.called


def test_application_reminder_loop_exception_path(tmp_path, monkeypatch):
    mock_config = MagicMock()
    mock_conn = MagicMock()
    monkeypatch.setattr("agent_core.config.load_config", lambda: mock_config)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **k: mock_conn)

    def fake_check(config, conn):
        raise RuntimeError("reminder boom")

    monkeypatch.setattr("agent_core.scheduler.scheduler.check_application_reminders", fake_check)
    monkeypatch.setattr(serve.time, "sleep", lambda _s: (_ for _ in ()).throw(SystemExit()))
    with patch.object(serve.logger, "warning") as mock_warn:
        with pytest.raises(SystemExit):
            serve._application_reminder_loop(str(tmp_path / "app.db"))
    assert mock_warn.called
    assert mock_conn.close.called


def test_start_application_reminder_thread(monkeypatch):
    started = []
    fake_thread = MagicMock()
    fake_thread.start.side_effect = lambda: started.append(True)

    class FakeThread:
        def __init__(self, target=None, args=None, name=None, daemon=None):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append(True)

    monkeypatch.setattr(serve.threading, "Thread", FakeThread)
    serve._start_application_reminder_thread("data/agent.db")
    assert started == [True]
