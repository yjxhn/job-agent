"""Unit tests for interview_prep pure helpers."""

from types import SimpleNamespace

from agent_core.pipeline.interview_prep import (
    _extract_json,
    _parse_assessment,
    _prep_bank_items,
    _prep_bank_lines,
    _prep_bank_question_texts,
    format_assessment_txt,
)


def test_extract_json_with_fence_and_trailing_comma():
    text = '```json\n{"a": 1, "b": [1, 2,],}\n```'
    assert _extract_json(text) == {"a": 1, "b": [1, 2]}


def test_parse_assessment_non_dict_returns_none():
    assert _parse_assessment("[1,2,3]") is None
    assert _parse_assessment("no json") is None


def test_parse_assessment_dict_ok():
    text = '前缀 {"overall": 8, "dimensions": {}} 后缀'
    assert _parse_assessment(text)["overall"] == 8


def test_format_assessment_txt_contains_scores():
    assessment = {
        "overall": 8,
        "dimensions": {
            "technical": {"score": 7, "comment": "不错"},
            "communication": {"score": 8},
        },
        "strengths": ["表达清晰"],
        "improvements": ["更具体"],
    }
    job = SimpleNamespace(company="测试公司", title="设备工程师")
    txt = format_assessment_txt(assessment, job, mode="realtime")
    assert "实时语音评估" in txt
    assert "总分: 8/10" in txt
    assert "表达清晰" in txt


def test_prep_bank_items_focus_filter():
    bank = {
        "rounds": [
            {"round": "一面", "focus": "技术", "questions": [{"q": "Q1"}, {"q": "Q2"}]},
            {"round": "HR面", "focus": "文化", "questions": [{"q": "Q3"}]},
        ],
        "project_deep_dive": [{"project": "P", "q": "P1"}],
    }
    items = _prep_bank_items(bank, focus="技术")
    lines = [line for line, _ in items]
    assert len(items) == 2
    assert all("技术" in line for line in lines)

    assert len(_prep_bank_lines(bank)) == 4
    assert len(_prep_bank_question_texts(bank, focus="文化")) == 1
