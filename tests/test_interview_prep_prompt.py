"""Guard tests for the mock-interview reverse-question truncation fix."""

from types import SimpleNamespace

from agent_core.pipeline.interview_prep import MOCK_SYSTEM, build_character_manifest


def test_mock_system_requires_complete_reverse_question_list():
    assert "必须完整列出全部推荐反问" in MOCK_SYSTEM


def test_character_manifest_requires_complete_reverse_question_list():
    job = SimpleNamespace(company="ACME", title="工程师", location="苏州")
    config = SimpleNamespace()
    bank = {
        "reverse_questions": [
            "问题一",
            "问题二",
            "问题三",
        ]
    }
    manifest = build_character_manifest(job, config, question_bank=bank)
    assert "必须完整列出全部条目" in manifest
    assert "问题一" in manifest
    assert "问题三" in manifest
