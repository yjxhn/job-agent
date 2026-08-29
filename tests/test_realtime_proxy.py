"""Realtime proxy exit-intent regression tests.

2026-08-16 bug: 候选人语音说“没有了”且面试官回复“面试结束。”后，会话不会触发
评估生成（火山 TTS_ENDED status_code 不总是 20000002，且“没有了”不在退出词表）。
"""

from types import SimpleNamespace

from agent_core.server.realtime_proxy import EVT_REPLY_ENDED, EVT_TTS_ENDED, RealtimeSession


def _make_session() -> RealtimeSession:
    job = SimpleNamespace(id="j1", title="设备工程师", company="测试公司")
    return RealtimeSession("rt_test", job, None, None, "manifest", None)


async def test_realtime_exit_keywords_include_natural_endings():
    sess = _make_session()
    for phrase in ("没有了", "没有了。", "没有问题了", "没有其他问题", "没别的问题了"):
        assert sess._is_exit_intent(phrase) is True


async def test_realtime_asr_wu_you_le_triggers_assessment():
    sess = _make_session()
    calls: dict[str, int] = {"assessment": 0, "force": 0}

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return False

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": 451, "payload": {"results": [{"text": "没有了。", "is_interim": False}]}},
        b"",
    )
    assert calls == {"assessment": 1, "force": 1}


async def test_realtime_asr_exit_keyword_forces_continue_when_questions_remain():
    sess = _make_session()
    calls: dict[str, int] = {"assessment": 0, "force": 0}

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return True

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": 451, "payload": {"results": [{"text": "没有了。", "is_interim": False}]}},
        b"",
    )
    assert calls == {"assessment": 0, "force": 1}


async def test_realtime_tts_ended_fallback_after_interviewer_says_end():
    """TTS_ENDED 状态码不是 20000002 时，面试官已说收尾也应触发评估。"""
    sess = _make_session()
    calls: dict[str, int] = {"assessment": 0, "force": 0}
    sess._reply_buf = "面试结束。"
    sess._reply_ended_exit_marker = True

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return False

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": EVT_TTS_ENDED, "payload": {"status_code": "20000000"}}, b""
    )
    assert calls == {"assessment": 1, "force": 1}


async def test_realtime_tts_ended_normal_status_does_not_end():
    sess = _make_session()
    calls: dict[str, int] = {"assessment": 0, "force": 0}
    sess._reply_buf = "下一个问题"
    sess._reply_ended_exit_marker = False

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return False

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": EVT_TTS_ENDED, "payload": {"status_code": "20000000"}}, b""
    )
    assert calls == {"assessment": 0, "force": 0}


async def test_realtime_tts_ended_does_not_end_during_reverse_pending():
    """反问环节候选人还没回应时，TTS_ENDED/结束语不能提前触发评估。"""
    sess = _make_session()
    sess.transcript += [
        "面试官: 请自我介绍" + chr(10),
        "你: 我叫张三" + chr(10),
        "面试官: 第一题" + chr(10),
        "你: 回答" + chr(10),
        "面试官: 我的问题问完了，你有什么想问我的吗？" + chr(10),
    ]
    sess._reply_buf = "我的问题问完了，你有什么想问我的吗？\n面试结束。"
    sess._reply_ended_exit_marker = True
    calls: dict[str, int] = {"assessment": 0, "force": 0}

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return False

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": EVT_TTS_ENDED, "payload": {"status_code": "20000002"}}, b""
    )
    assert calls == {"assessment": 0, "force": 0}


async def test_realtime_tts_ended_allows_end_after_candidate_reverse_response():
    """候选人回应反问后，面试官再说结束语才允许触发评估。"""
    sess = _make_session()
    sess.transcript += [
        "面试官: 请自我介绍" + chr(10),
        "你: 我叫张三" + chr(10),
        "面试官: 第一题" + chr(10),
        "你: 回答" + chr(10),
        "面试官: 我的问题问完了，你有什么想问我的吗？" + chr(10),
        "你: 我想问一下团队结构" + chr(10),
    ]
    sess._reply_buf = "面试结束。"
    sess._reply_ended_exit_marker = True
    calls: dict[str, int] = {"assessment": 0, "force": 0}

    async def _trigger_assessment():
        calls["assessment"] += 1

    async def _maybe_force_continue():
        calls["force"] += 1
        return False

    sess._trigger_assessment = _trigger_assessment
    sess._maybe_force_continue = _maybe_force_continue
    await sess._handle_volc_event(
        {"event": EVT_TTS_ENDED, "payload": {"status_code": "20000000"}}, b""
    )
    assert calls == {"assessment": 1, "force": 1}


async def test_realtime_count_questions_stops_at_reverse_phase():
    sess = _make_session()
    sess.transcript += [
        "面试官: 请自我介绍" + chr(10),
        "面试官: 第一题" + chr(10),
        "面试官: 我的问题问完了，你有什么想问我的吗？" + chr(10),
        "面试官: 这是反问回答，不应计数" + chr(10),
    ]
    assert sess._count_questions_asked() == 1


async def test_realtime_total_questions_uses_focus_filtered_count():
    sess = _make_session()
    sess.total_questions = 1
    assert sess._total_questions() == 1
    sess.total_questions = None
    sess.question_bank = {"rounds": [], "project_deep_dive": [{"q": "x"}]}
    assert sess._total_questions() == 1


async def test_realtime_natural_end_phrase_is_not_substring_match():
    sess = _make_session()
    assert sess._is_exit_intent("没有了。") is True
    assert sess._is_exit_intent("这个项目我参与不多，暂时没有了") is False
    assert sess._is_exit_intent("这个方案没有其他问题") is False


class _FakeWs:
    def __init__(self):
        self.state = 1
        self.closed = 0

    async def close(self):
        self.closed += 1
        self.state = 3


async def test_realtime_abandon_closes_without_saving():
    sess = _make_session()
    sess.volc_ws = _FakeWs()
    sess.browser_ws = _FakeWs()
    await sess._abandon()
    assert sess.ended is True
    assert sess.volc_ws.closed == 1
    assert sess.browser_ws.closed == 1


def test_realtime_artifact_names():
    sess = _make_session()
    sess.job = SimpleNamespace(company="测试公司", title="设备工程师")
    md, asc = sess._artifact_names()
    assert md == "测试公司_设备工程师_realtime_mock.md"
    assert asc == "测试公司_设备工程师_realtime_mock_assessment.txt"


async def test_realtime_close_connections():
    sess = _make_session()
    sess.volc_ws = _FakeWs()
    sess.browser_ws = _FakeWs()
    await sess._close_connections()
    assert sess.volc_ws.closed == 1
    assert sess.browser_ws.closed == 1


async def test_realtime_end_session_manual_success(monkeypatch):
    sess = _make_session()
    sess.ended = False
    sess.browser_ws = _FakeWs()
    sent = []

    async def fake_send(data):
        sent.append(data)

    sess._send_browser = fake_send

    async def fake_assessment(*a, **k):
        return {"overall": 7, "dimensions": {}}

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_assessment,
    )
    sess._save_artifacts = lambda _t, _a, interrupted=False: None
    sess._artifact_names = lambda: ("md.md", "asc.txt")
    sess._send_finish_session = lambda: _noop()
    sess._close_connections = lambda: _noop()

    await sess._end_session(manual=True)
    assert sess.ended is True
    assert any(d.get("type") == "ended" for d in sent)


async def test_realtime_trigger_assessment_success(monkeypatch):
    sess = _make_session()
    sess.ended = False
    sess.browser_ws = _FakeWs()
    sess.transcript = ["记录" + chr(10)]
    sent = []

    async def fake_send(data):
        sent.append(data)

    sess._send_browser = fake_send

    async def fake_assessment(*a, **k):
        return {"overall": 8, "dimensions": {}}

    monkeypatch.setattr(
        "agent_core.pipeline.interview_prep.generate_assessment_from_transcript",
        fake_assessment,
    )
    sess._save_artifacts = lambda _t, _a, interrupted=False: None
    sess._send_finish_session = lambda: _noop()
    sess._close_connections = lambda: _noop()

    await sess._trigger_assessment()
    assert sess.ended is True
    assert any(d.get("type") == "ended" for d in sent)


async def _noop():
    return None


def test_realtime_save_artifacts_without_assessment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from pathlib import Path

    from agent_core.storage.db import get_db, migrate

    db = str(tmp_path / "a.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()

    sess = _make_session()
    sess.job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    sess.db_path = db
    cataloged = []

    def fake_catalog(_db, _job_id, _file_type, path, **kw):
        cataloged.append(path)

    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", fake_catalog)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: get_db(path or db))

    sess._save_artifacts("记录", None)
    assert Path("output/测试公司_设备工程师_realtime_mock.md").exists()
    assert not Path("output/测试公司_设备工程师_realtime_mock_assessment.txt").exists()
    assert cataloged == ["output/测试公司_设备工程师_realtime_mock.md"]


def test_realtime_save_artifacts_with_assessment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from pathlib import Path

    from agent_core.storage.db import get_db, migrate

    db = str(tmp_path / "b.db")
    conn = get_db(db)
    migrate(conn)
    conn.close()

    sess = _make_session()
    sess.job = SimpleNamespace(id="j2", company="测试公司", title="设备工程师")
    sess.db_path = db
    cataloged = []

    def fake_catalog(_db, _job_id, _file_type, path, **kw):
        cataloged.append(path)

    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", fake_catalog)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda path=None: get_db(path or db))

    sess._save_artifacts("记录", {"overall": 8, "dimensions": {}})
    assert Path("output/测试公司_设备工程师_realtime_mock.md").exists()
    assert Path("output/测试公司_设备工程师_realtime_mock_assessment.txt").exists()
    assert len(cataloged) == 2


async def test_realtime_late_asr_inserted_before_next_interviewer_turn():
    """2026-08-16 实测：ASR 片段晚于面试官下一题到达，曾导致评估乱序扣分。"""
    sess = _make_session()
    sess.browser_ws = _FakeWs()
    sess._reply_buf = "第一题"
    await sess._handle_volc_event({"event": EVT_REPLY_ENDED, "payload": {}}, b"")
    sess._reply_buf = "第二题"
    await sess._handle_volc_event({"event": EVT_REPLY_ENDED, "payload": {}}, b"")
    # 晚到的第一题回答，必须插到第二题之前
    await sess._handle_volc_event(
        {"event": 451, "payload": {"results": [{"text": "第一题的回答", "is_interim": False}]}},
        b"",
    )
    joined = "".join(sess.transcript)
    assert joined.index("你: 第一题的回答") < joined.index("面试官: 第二题")
    assert joined.index("面试官: 第一题") < joined.index("你: 第一题的回答")
