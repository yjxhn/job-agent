"""Behavioral tests for the heavier POST/GET handlers in agent_core.server.serve.

This file intentionally focuses on offer evaluation/compare/save, salary advice,
materials generation/regeneration, mock interview endpoints, and dashboard
list/update endpoints.  All LLM/network/async work is mocked; each test uses a
temporary SQLite database and temporary working directory where the handler
writes files.
"""

import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

from agent_core.server import serve
from agent_core.storage.db import get_db, migrate

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _mk_handler(db_path, path="/api/x"):
    h = serve.Handler.__new__(serve.Handler)
    h.db_path = db_path
    h.path = path
    h.headers = {"Content-Length": "10"}
    h.wfile = io.BytesIO()
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    return h


def _body(h):
    return json.loads(h.wfile.getvalue())


def _seed_job(
    conn,
    job_id="j1",
    title="Engineer",
    company="ACME",
    description="JD description",
    urls='{"byd":"http://x"}',
    platforms='["byd"]',
    direction="default",
):
    conn.execute(
        "INSERT INTO jobs (id, title, company, company_normalized, location, direction, "
        "description, urls, platforms, first_seen, last_seen, security_id, lid) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            title,
            company,
            company,
            "Suzhou",
            direction,
            description,
            urls,
            platforms,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            "",
            "",
        ),
    )
    conn.commit()


def _seed_draft(
    conn,
    job_id="j1",
    resume_md="# Resume",
    hr_message="HR hello",
    status="draft",
    version=1,
    interview_prep_md=None,
    interview_confirmed=0,
    feedback="",
):
    conn.execute(
        "INSERT OR REPLACE INTO material_drafts "
        "(job_id, resume_md, hr_message, status, feedback, version, created_at, updated_at, "
        "interview_prep_md, interview_confirmed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            resume_md,
            hr_message,
            status,
            feedback,
            version,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
            interview_prep_md,
            interview_confirmed,
        ),
    )
    conn.commit()


def _seed_application(conn, app_id=1, job_id="j1", status="已投递", notes=""):
    conn.execute(
        "INSERT INTO applications (id, job_id, status, applied_at, updated_at, notes) "
        "VALUES (?,?,?,?,?,?)",
        (app_id, job_id, status, "2026-01-01T00:00:00", "2026-01-01T00:00:00", notes),
    )
    conn.commit()


def _seed_offer_eval(
    conn, file_name, company="ACME", title="Engineer", parsed=None, result=None, raw_text=""
):
    parsed = parsed or {"company": company, "title": title}
    result = result or {"overall_score": 7}
    conn.execute(
        "INSERT OR REPLACE INTO offer_evaluations "
        "(offer_file_name, offer_file_path, company, title, parsed_fields, eval_input, "
        "result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            file_name,
            "offers/" + file_name,
            company,
            title,
            json.dumps(parsed, ensure_ascii=False),
            json.dumps({"company": company, "title": title}, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()


def _db_patch(db):
    """Patch get_db to open a fresh connection to the same temp db each call."""
    return patch(
        "agent_core.storage.db.get_db",
        side_effect=lambda *args, **kwargs: get_db(db),
    )


def _make_prep_file(tmp_path, name="prep.md", text="# Interview Prep"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# /api/offer/compare
# --------------------------------------------------------------------------- #


def test_offer_compare_fewer_than_2_names(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with patch("agent_core.server.serve._read_json_body", return_value={"file_names": ["a.txt"]}):
        h._api_offer_compare()
    assert _body(h)["error"] == "至少需要 2 个 Offer 进行对比"


def test_offer_compare_evaluated_rows_success(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_offer_eval(
        conn,
        "a.txt",
        parsed={"company": "ACME", "title": "Engineer"},
        result={"overall_score": 7},
    )
    _seed_offer_eval(
        conn,
        "b.txt",
        parsed={"company": "Beta", "title": "Manager"},
        result={"overall_score": 9},
    )
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("公司名: ACME\n职位名: Engineer\n", encoding="utf-8")
    (offers / "b.txt").write_text("公司名: Beta\n职位名: Manager\n", encoding="utf-8")

    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"file_names": ["a.txt", "b.txt"]},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.offer_eval.compare",
            new=AsyncMock(return_value="## 对比分析"),
        ),
    ):
        h._api_offer_compare()

    d = _body(h)
    assert d["ok"] is True
    assert d["analysis"] == "## 对比分析"
    assert len(d["offers"]) == 2
    assert d["offers"][0]["raw_text"] == "公司名: ACME\n职位名: Engineer\n"
    assert d["best"]["file_name"] == "b.txt"


def test_offer_compare_unevaluated_rows_parse_text(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text(
        "公司名: ACME\n职位名: Engineer\n工作地点: 苏州\n月薪base: 15K\n年总包: 20万\n",
        encoding="utf-8",
    )
    (offers / "b.txt").write_text(
        "公司: Beta\n职位: Manager\n工作地点: 上海\n月薪: 18K\n年薪: 24万\n",
        encoding="utf-8",
    )

    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"file_names": ["a.txt", "b.txt"]},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.offer_eval.compare",
            new=AsyncMock(return_value="分析"),
        ),
    ):
        h._api_offer_compare()

    d = _body(h)
    assert d["ok"] is True
    assert d["offers"][0]["company"] == "ACME"
    assert d["offers"][0]["parsed"]["monthly_base"] == "15K"
    assert d["offers"][1]["company"] == "Beta"


def test_offer_compare_invalid_path(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"file_names": ["../secret.txt", "b.txt"]},
        ),
        _db_patch(db),
    ):
        h._api_offer_compare()
    assert _body(h)["error"] == "invalid file path"


def test_offer_compare_file_missing(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"file_names": ["a.txt", "missing.txt"]},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_offer_compare()
    assert _body(h)["error"] == "Offer 文件不存在：missing.txt"


def test_offer_compare_llm_exception(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_offer_eval(conn, "a.txt")
    _seed_offer_eval(conn, "b.txt")
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("A", encoding="utf-8")
    (offers / "b.txt").write_text("B", encoding="utf-8")
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"file_names": ["a.txt", "b.txt"]},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.offer_eval.compare",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ),
    ):
        h._api_offer_compare()
    assert _body(h)["error"] == "LLM 对比失败：llm down"


# --------------------------------------------------------------------------- #
# /api/offer/evaluate
# --------------------------------------------------------------------------- #


def test_offer_evaluate_missing_company_and_file(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with (
        patch("agent_core.server.serve._read_json_body", return_value={}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_offer_evaluate()
    assert _body(h)["error"] == "缺少 company 或 file_name"


def test_offer_evaluate_file_not_found(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(tmp_path / "offers"))
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"file_name": "nope.txt"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_offer_evaluate()
    assert _body(h)["error"] == "Offer 文件不存在：nope.txt"


def test_offer_evaluate_read_exception(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("content", encoding="utf-8")
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"file_name": "a.txt"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch("builtins.open", side_effect=OSError("read fail")),
    ):
        h._api_offer_evaluate()
    assert _body(h)["error"] == "读取失败: read fail"


def test_offer_evaluate_file_mode_success(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("公司名: ACME\n职位名: Engineer\n", encoding="utf-8")

    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    parsed = {
        "company": "ACME",
        "title": "Engineer",
        "location": "Suzhou",
        "monthly_base": "15K",
    }
    result = {"overall_score": 8, "pros": ["good"]}
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"file_name": "a.txt"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.server.serve._parse_offer_fields",
            new=AsyncMock(return_value=parsed),
        ),
        patch(
            "agent_core.pipeline.offer_eval.evaluate",
            new=AsyncMock(return_value=result),
        ),
    ):
        h._api_offer_evaluate()

    d = _body(h)
    assert d["ok"] is True
    assert d["parsed"]["company"] == "ACME"
    assert d["result"]["overall_score"] == 8

    conn = get_db(db)
    row = conn.execute(
        "SELECT company, result FROM offer_evaluations WHERE offer_file_name='a.txt'"
    ).fetchone()
    conn.close()
    assert row["company"] == "ACME"
    assert json.loads(row["result"])["overall_score"] == 8


def test_offer_evaluate_raw_field_mode_success(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    result = {"overall_score": 9, "summary": "good offer"}
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer", "salary": "15K"},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.offer_eval.evaluate",
            new=AsyncMock(return_value=result),
        ),
    ):
        h._api_offer_evaluate()
    assert _body(h) == result


def test_offer_evaluate_llm_exception(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME"},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.offer_eval.evaluate",
            new=AsyncMock(side_effect=RuntimeError("eval fail")),
        ),
    ):
        h._api_offer_evaluate()
    assert _body(h)["error"] == "评估失败: eval fail"


# --------------------------------------------------------------------------- #
# /api/offer/save
# --------------------------------------------------------------------------- #


def test_offer_save_missing_company(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"title": "Engineer"}):
        h._api_offer_save()
    assert _body(h)["error"] == "缺少 company"


def test_offer_save_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_offer_save()
    d = _body(h)
    assert d["ok"] is True
    assert d["file_name"] == "ACME_Engineer_offer_eval.md"
    assert (tmp_path / "output" / "ACME_Engineer_offer_eval.md").exists()
    mock_catalog.assert_called_once()


def test_offer_save_html(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={
                "company": "ACME",
                "title": "Engineer",
                "html_content": "<html>eval</html>",
            },
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_save()
    d = _body(h)
    assert d["file_name"] == "ACME_Engineer_offer_eval.html"
    assert (tmp_path / "output" / "ACME_Engineer_offer_eval.html").read_text(
        encoding="utf-8"
    ) == "<html>eval</html>"


def test_offer_save_duplicate_filename_counter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "ACME_Engineer_offer_eval.md").write_text("old", encoding="utf-8")
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_save()
    d = _body(h)
    assert d["file_name"] == "ACME_Engineer_offer_eval_1.md"
    assert (tmp_path / "output" / "ACME_Engineer_offer_eval_1.md").exists()


def test_offer_save_appends_raw_offer_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("公司名: ACME\n原始条款\n", encoding="utf-8")
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer", "file_name": "a.txt"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_save()
    md = (tmp_path / "output" / "ACME_Engineer_offer_eval.md").read_text(encoding="utf-8")
    assert "原始条款" in md


def test_offer_save_missing_raw_offer_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(h, "_offers_dir", lambda: str(tmp_path / "offers"))
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_save()
    md = (tmp_path / "output" / "ACME_Engineer_offer_eval.md").read_text(encoding="utf-8")
    assert "（未找到原始 Offer 文件）" in md


def test_offer_save_write_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"company": "ACME"}),
        _db_patch(db),
        patch("builtins.open", side_effect=OSError("disk full")),
    ):
        h._api_offer_save()
    assert _body(h)["error"] == "保存失败: disk full"


def test_offer_save_catalog_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_offer_save()
    assert mock_catalog.call_count == 1
    args, kwargs = mock_catalog.call_args
    assert args[2] == "offer_eval"
    assert args[3].endswith("ACME_Engineer_offer_eval.md")
    assert kwargs["company"] == "ACME"


# --------------------------------------------------------------------------- #
# /api/offer/compare/save
# --------------------------------------------------------------------------- #


def test_offer_compare_save_fewer_than_2(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch(
        "agent_core.server.serve._read_json_body",
        return_value={"offers": [{"company": "ACME"}]},
    ):
        h._api_offer_compare_save()
    assert _body(h)["error"] == "至少需要 2 个 Offer 进行对比"


def test_offer_compare_save_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    offers = [
        {"company": "ACME", "result": {"overall_score": 7, "pros": ["a"]}},
        {"company": "Beta", "result": {"overall_score": 9, "pros": ["b"]}},
    ]
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"offers": offers}),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_compare_save()
    d = _body(h)
    assert d["ok"] is True
    assert d["file_name"] == "offer_compare_1.md"
    content = (tmp_path / "output" / "offer_compare_1.md").read_text(encoding="utf-8")
    assert "# 多 Offer 对比报告" in content
    assert "Beta" in content


def test_offer_compare_save_html(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    offers = [
        {"company": "ACME", "result": {"overall_score": 7}},
        {"company": "Beta", "result": {"overall_score": 9}},
    ]
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"offers": offers, "html_content": "<html>compare</html>"},
        ),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file"),
    ):
        h._api_offer_compare_save()
    d = _body(h)
    assert d["file_name"] == "offer_compare_1.html"
    assert (tmp_path / "output" / "offer_compare_1.html").read_text(
        encoding="utf-8"
    ) == "<html>compare</html>"


def test_offer_compare_save_write_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    offers = [
        {"company": "ACME", "result": {"overall_score": 7}},
        {"company": "Beta", "result": {"overall_score": 9}},
    ]
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"offers": offers}),
        _db_patch(db),
        patch("builtins.open", side_effect=OSError("no space")),
    ):
        h._api_offer_compare_save()
    assert _body(h)["error"] == "保存失败: no space"


def test_offer_compare_save_catalog_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    offers = [
        {"company": "ACME", "result": {"overall_score": 7}},
        {"company": "Beta", "result": {"overall_score": 9}},
    ]
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"offers": offers}),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_offer_compare_save()
    assert mock_catalog.call_count == 1
    args, _kwargs = mock_catalog.call_args
    assert args[2] == "offer_compare"


# --------------------------------------------------------------------------- #
# /api/salary-advice
# --------------------------------------------------------------------------- #


def test_salary_advice_missing_company(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"title": "Engineer"}):
        h._api_salary_advice()
    assert _body(h)["error"] == "缺少 company"


def test_salary_advice_success(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    result = {"anchor": "28K*16", "leverage": ["market data"]}
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"company": "ACME", "title": "Engineer"},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.salary_advice.get_advice",
            new=AsyncMock(return_value=result),
        ),
    ):
        h._api_salary_advice()
    assert _body(h) == result


def test_salary_advice_llm_exception(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"company": "ACME"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.salary_advice.get_advice",
            new=AsyncMock(side_effect=RuntimeError("advice fail")),
        ),
    ):
        h._api_salary_advice()
    assert _body(h)["error"] == "建议生成失败: advice fail"


# --------------------------------------------------------------------------- #
# /api/salary-advice/save
# --------------------------------------------------------------------------- #


def test_salary_advice_save_missing_company(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"title": "Engineer"}):
        h._api_salary_advice_save()
    assert _body(h)["error"] == "缺少 company"


def test_salary_advice_save_success_with_lists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    body = {
        "company": "ACME",
        "title": "Engineer",
        "anchor": "28K*16",
        "leverage": ["market data"],
        "concessions": ["base 27K"],
        "scripts": ["你好，期望 28K"],
        "confidence": "high",
    }
    with (
        patch("agent_core.server.serve._read_json_body", return_value=body),
        _db_patch(db),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_salary_advice_save()
    d = _body(h)
    assert d["ok"] is True
    assert d["file_name"] == "ACME_salary_advice.md"
    content = (tmp_path / "output" / "ACME_salary_advice.md").read_text(encoding="utf-8")
    assert "28K*16" in content
    assert "market data" in content
    assert "你好，期望 28K" in content
    mock_catalog.assert_called_once()


def test_salary_advice_save_write_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"company": "ACME"}),
        _db_patch(db),
        patch("builtins.open", side_effect=OSError("write fail")),
    ):
        h._api_salary_advice_save()
    assert _body(h)["error"] == "保存失败: write fail"


# --------------------------------------------------------------------------- #
# /api/materials/generate
# --------------------------------------------------------------------------- #


def test_materials_generate_no_job_ids(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is False
    assert "未选择职位" in d["message"]


def test_materials_generate_too_many_job_ids(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    job_ids = [f"j{i}" for i in range(11)]
    with patch("agent_core.server.serve._read_json_body", return_value={"job_ids": job_ids}):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is False
    assert "最多生成 10" in d["message"]


def test_materials_generate_no_rows(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["nope"]}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "职位未找到"


def test_materials_generate_some_missing_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body", return_value={"job_ids": ["j1", "missing"]}
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd", new=AsyncMock(return_value="enriched")
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="resume_md")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="hr_msg"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.predict_questions",
            new=AsyncMock(return_value="questions"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.save_interview_prep",
            return_value=_make_prep_file(tmp_path),
        ),
    ):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is True
    assert d["succeeded"] == 1
    assert any(item["job_id"] == "missing" for item in d["failed"])


def test_materials_generate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    conn.close()
    h = _mk_handler(db)
    prep_path = _make_prep_file(tmp_path, "prep.md", "# Prep")
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["j1"]}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd", new=AsyncMock(return_value="enriched")
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="resume_md")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="hr_msg"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.predict_questions",
            new=AsyncMock(return_value="questions"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.save_interview_prep",
            return_value=prep_path,
        ),
    ):
        h._api_materials_generate()

    d = _body(h)
    assert d["ok"] is True
    assert d["succeeded"] == 1
    assert d["failed"] == []

    conn = get_db(db)
    row = conn.execute(
        "SELECT resume_md, hr_message, interview_prep_md FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    conn.close()
    assert row["resume_md"] == "resume_md"
    assert row["hr_message"] == "hr_msg"
    assert row["interview_prep_md"] == "# Prep"


def test_materials_generate_interview_prep_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["j1"]}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd", new=AsyncMock(return_value="enriched")
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="resume_md")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="hr_msg"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.predict_questions",
            new=AsyncMock(side_effect=[RuntimeError("prep fail"), RuntimeError("prep fail 2")]),
        ),
    ):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is True
    assert d["succeeded"] == 1
    assert d["interview_prep_failed"][0]["job_id"] == "j1"


def test_materials_generate_retry_failure_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["j1"]}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd",
            new=AsyncMock(side_effect=[RuntimeError("gen fail"), RuntimeError("gen fail 2")]),
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="resume_md")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="hr_msg"),
        ),
    ):
        h._api_materials_generate()
    d = _body(h)
    assert d["ok"] is True
    assert d["succeeded"] == 0
    assert d["failed"][0]["job_id"] == "j1"
    assert "gen fail 2" in d["failed"][0]["error"]


# --------------------------------------------------------------------------- #
# /api/materials/regenerate
# --------------------------------------------------------------------------- #


def test_materials_regenerate_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_materials_regenerate()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 job_id"


def test_materials_regenerate_job_not_found(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "nope"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_materials_regenerate()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "职位未找到"


def test_materials_regenerate_success_version_update(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    _seed_draft(conn, job_id="j1", resume_md="old", hr_message="old hr", version=1)
    conn.close()
    h = _mk_handler(db)
    prep_path = _make_prep_file(tmp_path, "prep.md", "# New Prep")
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"job_id": "j1", "feedback": "更突出项目"},
        ),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd", new=AsyncMock(return_value="enriched")
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="new_resume")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="new_hr"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.predict_questions",
            new=AsyncMock(return_value="questions"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.save_interview_prep",
            return_value=prep_path,
        ),
    ):
        h._api_materials_regenerate()

    d = _body(h)
    assert d["ok"] is True
    assert d["job_id"] == "j1"
    assert d["version"] == 2

    conn = get_db(db)
    row = conn.execute(
        "SELECT resume_md, hr_message, version, interview_prep_md FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    conn.close()
    assert row["resume_md"] == "new_resume"
    assert row["hr_message"] == "new_hr"
    assert row["version"] == 2
    assert row["interview_prep_md"] == "# New Prep"


def test_materials_regenerate_interview_prep_failure_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    _seed_draft(conn, job_id="j1", version=1)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.enrichment.enrich_job_jd", new=AsyncMock(return_value="enriched")
        ),
        patch("agent_core.pipeline.tailor.tailor_resume", new=AsyncMock(return_value="new_resume")),
        patch(
            "agent_core.pipeline.cover_letter.generate_cover_letter",
            new=AsyncMock(return_value="new_hr"),
        ),
        patch(
            "agent_core.pipeline.interview_prep.predict_questions",
            new=AsyncMock(side_effect=[RuntimeError("prep fail"), RuntimeError("prep fail 2")]),
        ),
    ):
        h._api_materials_regenerate()
    d = _body(h)
    assert d["ok"] is True
    assert d["version"] == 2
    assert d["interview_prep_failed"][0]["job_id"] == "j1"


# --------------------------------------------------------------------------- #
# /api/materials/delete
# --------------------------------------------------------------------------- #


def test_materials_delete_missing_job_ids(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_materials_delete()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "job_ids 不能为空"


def test_materials_delete_success_removes_draft_and_prep_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_draft(conn, job_id="j1")
    conn.execute(
        "INSERT INTO generated_files (job_id, file_type, file_name, file_path, created_at) "
        "VALUES ('j1', 'interview_prep', 'ACME_Engineer_interview.md', 'output/ACME_Engineer_interview.md', ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "ACME_Engineer_interview.md").write_text("md", encoding="utf-8")
    (tmp_path / "output" / "ACME_Engineer_interview.json").write_text("{}", encoding="utf-8")

    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_ids": ["j1"]}),
    ):
        h._api_materials_delete()

    d = _body(h)
    assert d["ok"] is True
    assert d["deleted"] == 1
    conn = get_db(db)
    assert conn.execute("SELECT COUNT(*) FROM material_drafts WHERE job_id='j1'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM generated_files WHERE job_id='j1'").fetchone()[0] == 0
    conn.close()
    assert not (tmp_path / "output" / "ACME_Engineer_interview.md").exists()
    assert not (tmp_path / "output" / "ACME_Engineer_interview.json").exists()


# --------------------------------------------------------------------------- #
# /api/materials/confirm
# --------------------------------------------------------------------------- #


def test_materials_confirm_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_materials_confirm()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 job_id"


def test_materials_confirm_missing_draft(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}),
    ):
        h._api_materials_confirm()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "职位或草稿不存在"


def test_materials_confirm_success_rebuilds_interview_prep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_draft(conn, job_id="j1", interview_prep_md="# Interview Prep", interview_confirmed=0)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}),
        patch(
            "agent_core.pipeline.tailor.save_resume",
            return_value={"md": "out/j1.md", "docx": "out/j1.docx"},
        ),
        patch("agent_core.pipeline.cover_letter.save_cover_letter", return_value="out/j1_hr.md"),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_materials_confirm()

    d = _body(h)
    assert d["ok"] is True
    assert (tmp_path / "output" / "ACME_Engineer_interview.md").read_text(
        encoding="utf-8"
    ) == "# Interview Prep"
    conn = get_db(db)
    row = conn.execute(
        "SELECT status, interview_confirmed FROM material_drafts WHERE job_id='j1'"
    ).fetchone()
    conn.close()
    assert row["status"] == "confirmed"
    assert row["interview_confirmed"] == 1
    types = [call.args[2] for call in mock_catalog.call_args_list]
    assert "interview_prep" in types


def test_materials_confirm_no_interview_prep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_draft(conn, job_id="j1", interview_prep_md=None, interview_confirmed=0)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}),
        patch(
            "agent_core.pipeline.tailor.save_resume",
            return_value={"md": "out/j1.md", "docx": "out/j1.docx"},
        ),
        patch("agent_core.pipeline.cover_letter.save_cover_letter", return_value="out/j1_hr.md"),
        patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
    ):
        h._api_materials_confirm()
    assert _body(h)["ok"] is True
    types = [call.args[2] for call in mock_catalog.call_args_list]
    assert "interview_prep" not in types


# --------------------------------------------------------------------------- #
# /api/mock-interview/start
# --------------------------------------------------------------------------- #


def test_mock_interview_start_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_mock_interview_start()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 job_id"


def test_mock_interview_start_job_not_found(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "nope"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
    ):
        h._api_mock_interview_start()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "职位未找到"


def test_mock_interview_start_success(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "j1"}),
        patch("agent_core.config.load_config", return_value=MagicMock()),
        patch("agent_core.llm.providers.create_provider", return_value=MagicMock()),
        patch(
            "agent_core.pipeline.interview_prep.start_mock_session",
            return_value={"session_id": "s1", "ok": True},
        ),
    ):
        h._api_mock_interview_start()
    assert _body(h) == {"session_id": "s1", "ok": True}


# --------------------------------------------------------------------------- #
# /api/mock-interview/reply
# --------------------------------------------------------------------------- #


def test_mock_interview_reply_missing_session_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_mock_interview_reply()
    assert _body(h)["error"] == "缺少 session_id"


async def _stream_events(*args, **kwargs):
    yield {"type": "delta", "text": "你好"}
    yield {"type": "end", "assessment": None}


async def _stream_then_error(*args, **kwargs):
    yield {"type": "delta", "text": "partial"}
    raise RuntimeError("stream broke")


def test_mock_interview_reply_stream_success(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with (
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"session_id": "s1", "text": "hi"},
        ),
        patch("agent_core.pipeline.interview_prep.stream_mock_turn", new=_stream_events),
    ):
        h._api_mock_interview_reply()
    raw = h.wfile.getvalue().decode("utf-8")
    assert 'data: {"type": "delta", "text": "你好"}' in raw
    assert '"type": "end"' in raw


def test_mock_interview_reply_stream_exception(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"session_id": "s1"}),
        patch("agent_core.pipeline.interview_prep.stream_mock_turn", new=_stream_then_error),
    ):
        h._api_mock_interview_reply()
    raw = h.wfile.getvalue().decode("utf-8")
    assert '"type": "error"' in raw
    assert "流式中断: stream broke" in raw


# --------------------------------------------------------------------------- #
# /api/mock-interview/end & abandon
# --------------------------------------------------------------------------- #


def test_mock_interview_end_missing_session_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_mock_interview_end()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 session_id"


def test_mock_interview_end_success_dict(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    result = {"ok": True, "md": "out/transcript.md", "assessment": "out/assessment.json"}
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"session_id": "s1"}),
        patch(
            "agent_core.pipeline.interview_prep.end_mock_session",
            new=AsyncMock(return_value=result),
        ),
    ):
        h._api_mock_interview_end()
    assert _body(h) == result


def test_mock_interview_abandon_missing_session_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={}):
        h._api_mock_interview_abandon()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 session_id"


def test_mock_interview_abandon_success(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with (
        patch("agent_core.server.serve._read_json_body", return_value={"session_id": "s1"}),
        patch(
            "agent_core.pipeline.interview_prep.abandon_mock_session",
            return_value=True,
        ),
    ):
        h._api_mock_interview_abandon()
    assert _body(h) == {"ok": True}


# --------------------------------------------------------------------------- #
# /api/mock-interview/latest-transcript
# --------------------------------------------------------------------------- #


def test_mock_latest_transcript_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h._api_mock_latest_transcript({"job_id": [""]})
    assert _body(h)["error"] == "缺少 job_id"


def test_mock_latest_transcript_job_not_found(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with _db_patch(db):
        h._api_mock_latest_transcript({"job_id": ["nope"]})
    assert _body(h)["error"] == "职位未找到"


def test_mock_latest_transcript_no_transcript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    conn.close()
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with _db_patch(db):
        h._api_mock_latest_transcript({"job_id": ["j1"]})
    assert _body(h)["error"] == "暂无对话记录"


def test_mock_latest_transcript_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    conn.close()
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "ACME_Engineer_realtime_mock.md").write_text(
        "line1\nline2\n", encoding="utf-8"
    )
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with _db_patch(db):
        h._api_mock_latest_transcript({"job_id": ["j1"], "mode": ["realtime"]})
    body = h.wfile.getvalue().decode("utf-8")
    assert "line1\r\nline2\r\n" in body
    assert any(
        call.args[0] == "Content-Disposition" and "ACME_Engineer_realtime_mock.txt" in call.args[1]
        for call in h.send_header.call_args_list
    )


def test_mock_latest_transcript_path_traversal_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    conn.close()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    h = _mk_handler(db)
    monkeypatch.setattr(serve.Handler, "db_path", db)
    with (
        _db_patch(db),
        patch("glob.glob", return_value=[str(outside)]),
    ):
        h._api_mock_latest_transcript({"job_id": ["j1"]})
    assert _body(h)["error"] == "Access denied"


# --------------------------------------------------------------------------- #
# /api/mock-assessment/preview
# --------------------------------------------------------------------------- #


def test_mock_assessment_preview_missing_name(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h._api_mock_assessment_preview({"name": [""]})
    assert _body(h)["error"] == "缺少 name"


def test_mock_assessment_preview_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve.os.path.realpath", return_value=str(tmp_path / "outside")):
        h._api_mock_assessment_preview({"name": ["any.txt"]})
    assert _body(h)["error"] == "Access denied"


def test_mock_assessment_preview_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h._api_mock_assessment_preview({"name": ["missing.txt"]})
    assert _body(h)["error"] == "评估文件未找到"


def test_mock_assessment_preview_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.json").write_text(
        json.dumps({"overall": 9, "dimensions": {"tech": 8}}), encoding="utf-8"
    )
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h._api_mock_assessment_preview({"name": ["a.json"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["name"] == "a.json"
    assert d["assessment"]["overall"] == 9


def test_mock_assessment_preview_plain_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    content = (
        "总分: 8.5/10\n"
        "【维度评分】\n"
        "技术能力(tech): 8/10\n"
        "沟通能力(comm): 7/10\n"
        "【优势】\n"
        "- 项目经验丰富\n"
        "- 快速学习\n"
        "【改进点】\n"
        "- 需要更多系统设计\n"
    )
    (tmp_path / "output" / "a.txt").write_text(content, encoding="utf-8")
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h._api_mock_assessment_preview({"name": ["a.txt"]})
    d = _body(h)
    assert d["ok"] is True
    assert d["assessment"]["overall"] == 8.5
    assert d["assessment"]["dimensions"]["tech"] == 8
    assert "项目经验丰富" in d["assessment"]["strengths"]
    assert "需要更多系统设计" in d["assessment"]["improvements"]


# --------------------------------------------------------------------------- #
# /api/applications
# --------------------------------------------------------------------------- #


def test_applications_empty(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/applications")
    with _db_patch(db):
        h._api_applications()
    d = _body(h)
    assert d["ok"] is True
    assert d["items"] == []


def test_applications_with_rows(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_application(conn, job_id="j1", status="已投递")
    conn.close()
    h = _mk_handler(db, path="/api/applications")
    with _db_patch(db):
        h._api_applications()
    d = _body(h)
    assert d["ok"] is True
    assert len(d["items"]) == 1
    assert d["items"][0]["job_title"] == "Engineer"
    assert d["items"][0]["company"] == "ACME"


# --------------------------------------------------------------------------- #
# /api/application  (手动新增)
# --------------------------------------------------------------------------- #


def test_application_create_success(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    conn.close()
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"job_id": "j1", "status": "已投递"},
        ),
    ):
        h._api_application_create()
    d = _body(h)
    assert d["ok"] is True
    conn = get_db(db)
    row = conn.execute("SELECT status FROM applications WHERE job_id='j1'").fetchone()
    conn.close()
    assert row["status"] == "已投递"


def test_application_create_missing_job_id(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    h.headers["Content-Length"] = "10"
    with patch("agent_core.server.serve._read_json_body", return_value={"status": "已投递"}):
        h._api_application_create()
    d = _body(h)
    assert d["error"] == "缺少 job_id"


def test_application_create_job_not_found(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db)
    h.headers["Content-Length"] = "10"
    with (
        _db_patch(db),
        patch("agent_core.server.serve._read_json_body", return_value={"job_id": "nope"}),
    ):
        h._api_application_create()
    d = _body(h)
    assert d["error"] == "岗位不存在: nope"


# --------------------------------------------------------------------------- #
# /api/application/update
# --------------------------------------------------------------------------- #


def test_application_update_missing_id_or_status(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"id": 1}):
        h._api_application_update()
    d = _body(h)
    assert d["ok"] is False
    assert d["message"] == "缺少 id 或 status"


def test_application_update_app_not_found(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body", return_value={"id": 999, "status": "已读"}
        ),
    ):
        h._api_application_update()
    d = _body(h)
    assert d["ok"] is False
    assert "不存在" in d["message"]


def test_application_update_with_notes(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    _seed_application(conn, status="已投递", notes="old")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"id": 1, "status": "HR已读", "notes": "new note"},
        ),
    ):
        h._api_application_update()
    assert _body(h)["ok"] is True
    conn = get_db(db)
    row = conn.execute("SELECT status, notes FROM applications WHERE id=1").fetchone()
    tl = conn.execute("SELECT COUNT(*) AS c FROM timelines WHERE application_id=1").fetchone()
    conn.close()
    assert row["status"] == "HR已读"
    assert row["notes"] == "new note"
    assert tl["c"] == 1


def test_application_update_without_notes_preserves_notes(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    _seed_application(conn, status="已投递", notes="keep me")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"id": 1, "status": "HR已读"},
        ),
    ):
        h._api_application_update()
    assert _body(h)["ok"] is True
    conn = get_db(db)
    row = conn.execute("SELECT notes FROM applications WHERE id=1").fetchone()
    conn.close()
    assert row["notes"] == "keep me"


def test_application_update_same_status_no_timeline(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn)
    _seed_application(conn, status="已投递")
    conn.close()
    h = _mk_handler(db)
    with (
        _db_patch(db),
        patch(
            "agent_core.server.serve._read_json_body",
            return_value={"id": 1, "status": "已投递"},
        ),
    ):
        h._api_application_update()
    assert _body(h)["ok"] is True
    conn = get_db(db)
    tl = conn.execute("SELECT COUNT(*) AS c FROM timelines WHERE application_id=1").fetchone()
    conn.close()
    assert tl["c"] == 0


# --------------------------------------------------------------------------- #
# /api/application/reminder
# --------------------------------------------------------------------------- #


def test_application_reminder_normal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"days": 5}):
        h._api_application_reminder()
    d = _body(h)
    assert d["ok"] is True
    assert d["reminder_days"] == 5
    state = json.loads((tmp_path / "data" / "scheduler_state.json").read_text(encoding="utf-8"))
    assert state["reminder_days"] == 5


def test_application_reminder_days_less_than_1_clamps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"days": 0}):
        h._api_application_reminder()
    d = _body(h)
    assert d["ok"] is True
    assert d["reminder_days"] == 1


def test_application_reminder_invalid_json_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "scheduler_state.json").write_text("{broken", encoding="utf-8")
    h = _mk_handler(str(tmp_path / "db.sqlite"))
    with patch("agent_core.server.serve._read_json_body", return_value={"days": 2}):
        h._api_application_reminder()
    d = _body(h)
    assert d["ok"] is True
    assert d["reminder_days"] == 2
    state = json.loads((tmp_path / "data" / "scheduler_state.json").read_text(encoding="utf-8"))
    assert state["reminder_days"] == 2


# --------------------------------------------------------------------------- #
# /api/materials/drafts & jobs
# --------------------------------------------------------------------------- #


def test_materials_drafts_invalid_status_falls_back_to_draft(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="d1", title="Engineer", company="ACME")
    _seed_job(conn, job_id="c1", title="Manager", company="Beta")
    _seed_draft(conn, job_id="d1", status="draft")
    _seed_draft(conn, job_id="c1", status="confirmed")
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=bogus")
    with _db_patch(db):
        h._api_materials_drafts()
    d = _body(h)
    assert d["ok"] is True
    assert [x["job_id"] for x in d["items"]] == ["d1"]


def test_materials_drafts_status_all(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="d1", title="Engineer", company="ACME")
    _seed_job(conn, job_id="c1", title="Manager", company="Beta")
    _seed_draft(conn, job_id="d1", status="draft")
    _seed_draft(conn, job_id="c1", status="confirmed")
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=all")
    with _db_patch(db):
        h._api_materials_drafts()
    d = _body(h)
    assert len(d["items"]) == 2


def test_materials_drafts_status_confirmed(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="d1", title="Engineer", company="ACME")
    _seed_job(conn, job_id="c1", title="Manager", company="Beta")
    _seed_draft(conn, job_id="d1", status="draft")
    _seed_draft(conn, job_id="c1", status="confirmed")
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=confirmed")
    with _db_patch(db):
        h._api_materials_drafts()
    d = _body(h)
    assert [x["job_id"] for x in d["items"]] == ["c1"]


def test_materials_drafts_includes_interview_fields(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_draft(
        conn, job_id="j1", status="draft", interview_prep_md="# Prep", interview_confirmed=1
    )
    conn.close()
    h = _mk_handler(db, path="/api/materials/drafts?status=all")
    with _db_patch(db):
        h._api_materials_drafts()
    d = _body(h)
    assert d["items"][0]["interview_prep_md"] == "# Prep"
    assert d["items"][0]["interview_confirmed"] == 1


def test_materials_jobs_with_rows(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_job(conn, job_id="j1", title="Engineer", company="ACME")
    _seed_draft(conn, job_id="j1")
    conn.close()
    h = _mk_handler(db, path="/api/materials/jobs")
    with _db_patch(db):
        h._api_materials_jobs()
    d = _body(h)
    assert len(d) == 1
    assert d[0]["id"] == "j1"
    assert d[0]["title"] == "Engineer"


# --------------------------------------------------------------------------- #
# /api/offer/list
# --------------------------------------------------------------------------- #


def test_offer_list_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.close()
    h = _mk_handler(db, path="/api/offer/list")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(tmp_path / "offers"))
    with _db_patch(db):
        h._api_offer_list()
    d = _body(h)
    assert d["items"] == []


def test_offer_list_with_file_and_eval_row(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    _seed_offer_eval(conn, "a.txt", result={"overall_score": 8})
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "a.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(db, path="/api/offer/list")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with _db_patch(db):
        h._api_offer_list()
    d = _body(h)
    assert len(d["items"]) == 1
    assert d["items"][0]["name"] == "a.txt"
    assert d["items"][0]["evaluated"] is True
    assert d["items"][0]["overall_score"] == 8


def test_offer_list_with_invalid_result_json(tmp_path, monkeypatch):
    db = str(tmp_path / "db.sqlite")
    conn = get_db(db)
    migrate(conn)
    conn.execute(
        "INSERT INTO offer_evaluations "
        "(offer_file_name, offer_file_path, company, title, parsed_fields, eval_input, "
        "result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "bad.txt",
            "offers/bad.txt",
            "ACME",
            "Engineer",
            "{}",
            "{}",
            "{bad json",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()
    offers = tmp_path / "offers"
    offers.mkdir()
    (offers / "bad.txt").write_text("x", encoding="utf-8")
    h = _mk_handler(db, path="/api/offer/list")
    monkeypatch.setattr(h, "_offers_dir", lambda: str(offers))
    with _db_patch(db):
        h._api_offer_list()
    d = _body(h)
    assert d["items"][0]["evaluated"] is True
    assert d["items"][0]["overall_score"] is None


# --------------------------------------------------------------------------- #
# /api/realtime/config
# --------------------------------------------------------------------------- #


def test_realtime_config(tmp_path):
    h = _mk_handler(str(tmp_path / "db.sqlite"), path="/api/realtime/config")
    h._api_realtime_config()
    d = _body(h)
    assert "enabled" in d
    assert "ws_port" in d
