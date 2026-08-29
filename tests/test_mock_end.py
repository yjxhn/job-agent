"""Tests for mock interview early-ending fix (A+B+C+D).

Covers:
- A: MOCK_SYSTEM prompt injects total_questions count
- C: only the unique ending phrase "以下是您的表现评估" ends the interview
- D: server-side count guard forces continue when LLM ends early
- terminal mock_interview: total_questions initialized for free-form (no prep)
"""

import asyncio
import re
from types import SimpleNamespace

import pytest

from agent_core.pipeline import interview_prep as ip

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Streams a canned reply; supports chat_stream + generate_assessment."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def chat_stream(self, messages, temperature=0.7, max_tokens=1024):
        self.calls += 1
        reply = self._replies.pop(0) if self._replies else "问题一"
        for chunk in reply:
            yield chunk

    async def generate_assessment_from_transcript(self, *a, **kw):
        return {"overall": 7, "dimensions": {}}


def _job():
    return SimpleNamespace(
        id="testjob",
        title="测试工程师",
        company="测试公司",
        description="岗位职责：测试",
        direction="default",
        location="北京",
    )


def _cfg():
    return SimpleNamespace(llm=SimpleNamespace(max_tokens=16384))


def _make_session(msgs, total_questions, reply="问题一", provider=None):
    """Insert a session directly into the pool, bypassing LLM opening turn."""
    sid = f"mock_test_{len(ip._mock_sessions)}"
    with ip._mock_lock:
        ip._mock_sessions[sid] = {
            "msgs": msgs,
            "transcript": ["文字面试记录\n"],
            "job": _job(),
            "config": _cfg(),
            "provider": provider if provider is not None else _FakeProvider([reply]),
            "question_bank": "",
            "total_questions": total_questions,
            "created_at": 0,
            "ended": False,
        }
    return sid


def _pop_session(sid):
    with ip._mock_lock:
        ip._mock_sessions.pop(sid, None)


def _stream(sid, user_text=None):
    """Collect all events from stream_mock_turn."""
    return asyncio.run(_collect(sid, user_text))


async def _collect(sid, user_text):
    return [e async for e in ip.stream_mock_turn(sid, user_text=user_text)]


# ---------------------------------------------------------------------------
# A: prompt injects total_questions
# ---------------------------------------------------------------------------


def test_mock_system_mentions_total_questions():
    """The prompt should contain the {total_questions} placeholder count."""
    assert "{total_questions}" in ip.MOCK_SYSTEM
    # and the early-ending ban
    assert "不允许提前结束" in ip.MOCK_SYSTEM


def test_mock_system_bank_strict_no_new_followup_scenarios():
    """题库模式禁止把题库外的“如果/假设”场景包装成追问。"""
    assert "题库非空时禁止任何追问" in ip.MOCK_SYSTEM
    assert "禁止任何追问" in ip._BANK_ABSOLUTE_RULE
    manifest = ip.build_character_manifest(
        SimpleNamespace(company="测试公司", title="测试工程师", location="北京"),
        _cfg(),
        question_bank={"rounds": [], "project_deep_dive": [], "reverse_questions": []},
    )
    assert "禁止任何追问" in manifest


def test_empty_stream_retries_once_then_recovers():
    """LLM 第一次返回空流时应自动重试；第二次有内容则正常返回 delta。"""
    provider = _FakeProvider(["", "下一题"])
    msgs = [
        {
            "role": "system",
            "content": ip.MOCK_SYSTEM.format(
                company="测试公司",
                title="测试工程师",
                resume_summary="简历",
                jd_summary="JD",
                question_bank="",
                reverse_questions="",
                total_questions=0,
                difficulty_hint="",
            ),
        }
    ]
    sid = _make_session(msgs, 0, provider=provider)
    try:
        events = _stream(sid, user_text="回答")
        assert provider.calls == 2
        deltas = [e["text"] for e in events if e.get("type") == "delta"]
        assert "".join(deltas) == "下一题"
        assert any(e.get("type") == "turn_end" for e in events)
    finally:
        _pop_session(sid)


def test_empty_stream_retries_exhausted_returns_error():
    """LLM 连续两次返回空流时返回可恢复 error，而不是空 turn_end。"""
    provider = _FakeProvider(["", ""])
    msgs = [{"role": "system", "content": "system"}]
    sid = _make_session(msgs, 0, provider=provider)
    try:
        events = _stream(sid, user_text="回答")
        assert provider.calls == 2
        assert any(e.get("type") == "error" for e in events)
        assert not any(e.get("type") == "turn_end" for e in events)
    finally:
        _pop_session(sid)


# ---------------------------------------------------------------------------
# C: only the unique ending phrase ends the interview
# ---------------------------------------------------------------------------


def test_mention_of_assessment_does_not_end():
    """Mentioning '表现评估' mid-question must NOT end the interview."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "请开始"},
        {"role": "assistant", "content": "先做下自我介绍"},
        {"role": "user", "content": "我叫张三"},
        # LLM replies mentioning the phrase but NOT ending
        {"role": "assistant", "content": "好的，面试结束后我们会给出表现评估。"},
    ]
    sess = _make_session(msgs, total_questions=10, reply="下一个问题：讲下项目经历")
    try:
        # next turn: interviewer asks a normal question, no ending phrase
        events = _stream(sess, user_text="继续")
        kinds = [e.get("type") for e in events]
        assert "turn_end" in kinds, f"expected turn_end, got {kinds}"
        assert "end" not in kinds, "should not have ended"
    finally:
        _pop_session(sess)


def test_unique_ending_phrase_ends(monkeypatch):
    """Only '以下是您的表现评估' triggers the end."""
    monkeypatch.setattr(ip, "_save_mock_transcript", lambda *a, **k: None)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "请开始"},
        {"role": "assistant", "content": "先自我介绍"},
        {"role": "user", "content": "我叫张三"},
    ]
    sess = _make_session(msgs, total_questions=1, reply="面试结束。以下是您的表现评估：{...}")
    try:
        events = _stream(sess, user_text="继续")
        kinds = [e.get("type") for e in events]
        assert "end" in kinds, f"expected end, got {kinds}"
    finally:
        _pop_session(sess)


# ---------------------------------------------------------------------------
# D: server-side count guard
# ---------------------------------------------------------------------------


def test_early_end_forces_continue():
    """LLM ends early (before all questions) -> forced continue, not end."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "请开始"},
        {"role": "assistant", "content": "自我介绍"},
        {"role": "user", "content": "我叫张三"},
        # candidate has answered 1 question; total is 5 -> LLM ends early
        {"role": "assistant", "content": "面试结束。以下是您的表现评估：{...}"},
    ]
    sess = _make_session(msgs, total_questions=5)
    try:
        events = _stream(sess, user_text="继续")
        kinds = [e.get("type") for e in events]
        assert "end" not in kinds, f"early end should be forced, got {kinds}"
        assert "turn_end" in kinds, f"expected turn_end, got {kinds}"
    finally:
        _pop_session(sess)


def test_full_count_allows_end(monkeypatch):
    """Candidate answered all questions -> ending allowed."""
    monkeypatch.setattr(ip, "_save_mock_transcript", lambda *a, **k: None)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "请开始"},
        {"role": "assistant", "content": "自我介绍"},
        {"role": "user", "content": "我叫张三"},
        # 1 answer so far; total 1 -> allowed to end
        {"role": "assistant", "content": "面试结束。以下是您的表现评估：{...}"},
    ]
    sess = _make_session(msgs, total_questions=1, reply="面试结束。以下是您的表现评估：{...}")
    try:
        events = _stream(sess, user_text="继续")
        kinds = [e.get("type") for e in events]
        assert "end" in kinds, f"expected end, got {kinds}"
    finally:
        _pop_session(sess)


def test_reverse_phase_does_not_end_same_turn(monkeypatch):
    """面试官进入反问环节时，即使同一轮带了结束语，也必须等候选人回应。"""
    monkeypatch.setattr(ip, "_save_mock_transcript", lambda *a, **k: None)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "请开始"},
        {"role": "assistant", "content": "自我介绍"},
        {"role": "user", "content": "我叫张三"},
    ]
    sess = _make_session(
        msgs,
        total_questions=1,
        reply="我的问题问完了，你有什么想问我的吗？\n面试结束。以下是您的表现评估：{...}",
    )
    try:
        events = _stream(sess, user_text="继续")
        kinds = [e.get("type") for e in events]
        assert "turn_end" in kinds, f"expected turn_end, got {kinds}"
        assert "end" not in kinds, f"reverse phase must not end same turn, got {kinds}"
    finally:
        _pop_session(sess)


# ---------------------------------------------------------------------------
# realtime voice: count guard (A' + D')
# ---------------------------------------------------------------------------


def _make_realtime_session(transcript_lines, question_bank):
    from agent_core.server.realtime_proxy import RealtimeSession

    sess = RealtimeSession.__new__(RealtimeSession)
    sess.session_id = "rt_test"
    sess.transcript = transcript_lines
    sess.question_bank = question_bank
    sess.volc_ws = None
    sess.ended = False
    return sess


def test_count_questions_asked():
    """Opening self-intro line is not counted as a question."""
    sess = _make_realtime_session(
        [
            "实时语音记录\n",
            "面试官: 请先做个自我介绍",
            "你: 我叫张三，有3年AMR经验",
            "面试官: 讲讲你的立库项目",
            "你: 我负责立库的维护",
            "面试官: 遇到故障怎么排查",
        ],
        {},
    )
    assert sess._count_questions_asked() == 2  # 3 面试官行 - 1 开场


def test_total_questions_from_bank():
    """Total counts rounds + project_deep_dive."""
    sess = _make_realtime_session(
        ["面试官: 开场"],
        {
            "rounds": [
                {"questions": [{"q": "1"}, {"q": "2"}]},
                {"questions": [{"q": "3"}]},
            ],
            "project_deep_dive": [{"q": "p1"}],
        },
    )
    assert sess._total_questions() == 4


def test_maybe_force_continue_questions_remain():
    """Early end with questions remaining -> forced continue (no assessment)."""
    sess = _make_realtime_session(
        [
            "面试官: 请先自我介绍",
            "你: 我叫张三",
            "面试官: 问题1",
            "你: 回答1",
        ],
        {"rounds": [{"questions": [{"q": "1"}, {"q": "2"}, {"q": "3"}]}]},
    )
    # volc_ws None -> send fails -> return False (can't force), but must not crash
    assert asyncio.run(sess._maybe_force_continue()) is False


def test_maybe_force_continue_all_asked():
    """All questions asked -> allow end (return False)."""
    sess = _make_realtime_session(
        [
            "面试官: 请先自我介绍",
            "你: 我叫张三",
            "面试官: 问题1",
            "你: 回答1",
            "面试官: 问题2",
            "你: 回答2",
            "面试官: 问题3",
            "你: 回答3",
        ],
        {"rounds": [{"questions": [{"q": "1"}, {"q": "2"}, {"q": "3"}]}]},
    )
    assert asyncio.run(sess._maybe_force_continue()) is False  # asked 3/3 -> end allowed


def test_maybe_force_continue_free_form():
    """No bank (free-form) -> no count guard, allow end."""
    sess = _make_realtime_session(["面试官: 请自我介绍", "你: 我叫张三"], {})
    assert asyncio.run(sess._maybe_force_continue()) is False


# ---------------------------------------------------------------------------
# terminal mock_interview: total_questions init (free-form)
# ---------------------------------------------------------------------------


def test_mock_interview_free_form_init():
    """mock_interview with from_prep=False must not NameError on total_questions."""
    # The variable is defined at function scope before .format()
    src = open(ip.__file__, encoding="utf-8").read()
    m = re.search(r"def mock_interview.*?total_questions = 0", src, re.S)
    assert m, "total_questions = 0 must be initialized before MOCK_SYSTEM.format"


# ---------------------------------------------------------------------------
# 2026-08-16 audit fixes
# ---------------------------------------------------------------------------


def test_focus_miss_context_has_no_bank_section(monkeypatch):
    prep = {
        "rounds": [{"round": "一面", "focus": "技术", "questions": [{"q": "你会看图吗？"}]}],
        "project_deep_dive": [],
        "reverse_questions": ["反问"],
    }
    monkeypatch.setattr(ip, "load_resume", lambda config, direction: "resume")
    monkeypatch.setattr(ip, "load_interview_prep_json", lambda job_id, db: prep)
    job = SimpleNamespace(
        id="j1", title="设备工程师", company="测试公司", description="JD", direction="d"
    )
    msgs, _t, note, _p, total = ip._build_mock_context(job, None, "d", True, "不存在", "easy")
    assert total == 0
    assert "Question bank" not in msgs[0]["content"]
    assert ip._BANK_ABSOLUTE_RULE.strip()[:20] not in msgs[0]["content"]


def test_start_mock_session_blocks_focus_miss(monkeypatch):
    prep = {
        "rounds": [{"round": "一面", "focus": "技术", "questions": [{"q": "你会看图吗？"}]}],
        "project_deep_dive": [],
    }
    monkeypatch.setattr(
        ip,
        "_build_mock_context",
        lambda *a, **k: (["sys"], ["t"], "note", prep, 0),
    )
    job = SimpleNamespace(id="j1", title="设备工程师", company="测试公司")
    info = ip.start_mock_session(job, None, None, from_prep=True, focus="不存在")
    assert info["ok"] is False
    assert "未命中" in info["message"]


def test_asked_so_far_prefers_bank_question_indices():
    sess = {
        "msgs": [
            {"role": "user", "content": "自我介绍"},
            {"role": "user", "content": "我想一下"},
            {"role": "user", "content": "答案"},
        ],
        "bank_questions": ["q1", "q2"],
        "asked_indices": {0},
    }
    assert ip._asked_so_far(sess) == 1


def test_match_bank_question_exact_and_paraphrase():
    qs = ["你在这个项目中负责AMR调度系统与WMS/MES的对接，具体如何保证接口联调一次成功率？"]
    assert ip._match_bank_question("第一题：" + qs[0], qs) == 0
    paraphrased = (
        "你在紫龙工厂厂内物流自动化项目（一期）中负责AMR调度系统与WMS/MES的对接，"
        "具体如何保证接口联调一次成功率？"
    )
    assert ip._match_bank_question(paraphrased, qs) == 0


def test_save_mock_transcript_only_catalogs_existing_files(monkeypatch, tmp_path):
    cataloged = []

    class _FakePath:
        def __init__(self, p):
            self.p = p

        def mkdir(self, **kw):
            return None

    class _DummyDb:
        def close(self):
            return None

    real_open = open

    def fake_open(path, *a, **kw):
        if str(path).startswith("output/"):
            return real_open(tmp_path / str(path)[len("output/") :], *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr(ip, "Path", _FakePath)
    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr("agent_core.storage.db.get_db", lambda *a, **kw: _DummyDb())

    def fake_catalog(db, job_id, file_type, path, **kw):
        cataloged.append(path)

    monkeypatch.setattr("agent_core.pipeline.file_catalog.catalog_file", fake_catalog)
    job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    sess = {"job": job, "transcript": ["文字面试记录", "面试官: 问题"]}
    ip._save_mock_transcript(sess, None)
    assert cataloged == ["output/测试公司_设备工程师_mock_interview.md"]


async def test_end_mock_session_assessment_failure_returns_no_filename(monkeypatch):
    saved = {}

    async def fail_assessment(*a, **kw):
        raise RuntimeError("no llm")

    def fake_save(sess, assessment, interrupted=False):
        saved["assessment"] = assessment
        saved["interrupted"] = interrupted

    monkeypatch.setattr(ip, "generate_assessment_from_transcript", fail_assessment)
    monkeypatch.setattr(ip, "_save_mock_transcript", fake_save)
    job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    ip._mock_sessions["s1"] = {
        "msgs": [],
        "transcript": [],
        "job": job,
        "config": None,
        "provider": None,
        "question_bank": None,
        "bank_questions": [],
        "asked_indices": set(),
        "focus": None,
        "total_questions": 0,
    }
    result = await ip.end_mock_session("s1")
    assert result == {"ok": True, "md": "测试公司_设备工程师_mock_interview.md", "assessment": None}
    assert saved["assessment"] is None
    assert saved["interrupted"] is False


async def test_end_mock_session_not_interrupted_when_all_questions_asked(monkeypatch):
    saved = {}

    async def ok_assessment(*a, **kw):
        return {"overall": 8}

    def fake_save(sess, assessment, interrupted=False):
        saved["interrupted"] = interrupted

    monkeypatch.setattr(ip, "generate_assessment_from_transcript", ok_assessment)
    monkeypatch.setattr(ip, "_save_mock_transcript", fake_save)
    job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    ip._mock_sessions["s2"] = {
        "msgs": [],
        "transcript": [],
        "job": job,
        "config": None,
        "provider": None,
        "question_bank": None,
        "bank_questions": ["q1"],
        "asked_indices": {0},
        "focus": None,
        "total_questions": 1,
    }
    await ip.end_mock_session("s2")
    assert saved["interrupted"] is False


async def test_generate_assessment_focus_filters_bank(monkeypatch):
    captured = {}

    async def fake_llm(provider, messages, **kw):
        captured["prompt"] = messages[0]["content"]
        return '{"overall": 7}'

    monkeypatch.setattr(ip, "call_llm_with_retry", fake_llm)
    job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    cfg = SimpleNamespace(llm=SimpleNamespace(max_tokens=512))
    bank = {
        "rounds": [
            {
                "round": "一面",
                "focus": "技术",
                "questions": [
                    {"q": "光伏设备如何调试？", "a": ["a1"]},
                    {"q": "HJT是什么？", "a": ["a2"]},
                ],
            },
        ],
        "project_deep_dive": [],
    }
    await ip.generate_assessment_from_transcript("记录", job, cfg, None, bank, focus="HJT")
    assert "HJT" in captured["prompt"]
    assert "光伏设备如何调试" not in captured["prompt"]


async def test_generate_assessment_times_out(monkeypatch):
    """评估 LLM 长时间不返回时必须超时，不能无限卡住前端弹窗。"""

    async def slow_llm(*a, **kw):
        await asyncio.sleep(10)
        return '{"overall": 7}'

    monkeypatch.setattr(ip, "call_llm_with_retry", slow_llm)
    job = SimpleNamespace(id="j1", company="测试公司", title="设备工程师")
    cfg = SimpleNamespace(llm=SimpleNamespace(max_tokens=512))
    with pytest.raises(TimeoutError):
        await ip.generate_assessment_from_transcript("记录", job, cfg, None, None, timeout=0.01)


def test_abandon_mock_session_drops_without_save():
    ip._mock_sessions["s3"] = {"msgs": []}
    assert ip.abandon_mock_session("s3") is True
    assert "s3" not in ip._mock_sessions
