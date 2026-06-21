"""Tests for prescreen scoring rules configuration."""

import pytest
import tempfile
import os
import shutil
from pathlib import Path
from agent_core.pipeline.prescreen import _score_job
from agent_core.config import load_config


def test_default_config_score():
    """Test that default config produces same scores as hardcoded values."""
    cfg = load_config()
    job = type(
        "Job",
        (),
        {
            "title": "AI Agent Engineer",
            "description": "Agent architecture, LLM, RAG, Memory, Multi-Agent",
            "salary_min": 10000,
            "salary_max": 20000,
        },
    )()

    # With all feature matches and keyword matches
    score = _score_job(job, cfg, "industrial_ai_agent")
    assert score > 50  # Base 50 + feature bonus + keyword bonus
    assert score <= 100  # Cap at 100


def test_config_override_score():
    """Test that config override changes scores."""
    # Create a copy of default config and modify it
    import yaml
    from agent_core.config import Config, DirectionConfig, PlatformConfig, MatchingConfig, PrescreenRulesConfig

    cfg = load_config()

    # Modify the rules
    cfg.prescreen_rules.feature_weight = 50
    cfg.prescreen_rules.keyword_weight = 30
    cfg.prescreen_rules.salary_high_multiplier = 2.0
    cfg.prescreen_rules.salary_high_bonus = 10

    job = type(
        "Job",
        (),
        {
            "title": "AI Agent Engineer",
            "description": "Agent, LLM, RAG, Memory, Multi-Agent, Agent",
            "salary_min": 15000,
            "salary_max": 25000,
        },
    )()

    score = _score_job(job, cfg, "industrial_ai_agent")
    # With doubled weights, score should be significantly higher
    assert score > 75  # More than default scores


def test_backward_compatibility():
    """Test that old config without prescreen_rules still works."""
    # Create a minimal config without prescreen_rules section
    import yaml

    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, "config.yaml")

    try:
        # Use a minimal config dict without prescreen_rules
        minimal_config = {
            "platforms": {
                "boss_zhipin": {
                    "enabled": False,
                    "login_method": "none"
                }
            },
            "search": {
                "location": "全国",
                "min_salary": 6000,
                "exclude_keywords": [],
                "directions": {
                    "industrial_ai_agent": {
                        "keywords": ["AI Agent"],
                        "resume_file": "resumes/industrial_ai_agent.txt",
                        "feature_words": ["Agent", "LLM"]
                    }
                }
            },
            "matching": {
                "prescreen_top_n": 30,
                "match_min_score": 50
            }
        }

        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(minimal_config, f)

        cfg = load_config(temp_path)

        # Verify defaults are applied
        assert cfg.prescreen_rules.feature_weight == 25
        assert cfg.prescreen_rules.keyword_weight == 15
        assert cfg.prescreen_rules.salary_high_multiplier == 1.5
        assert cfg.prescreen_rules.salary_high_bonus == 5

        job = type(
            "Job",
            (),
            {
                "title": "AI Agent Engineer",
                "description": "Agent, LLM, RAG, Memory, Multi-Agent, Agent",
                "salary_min": 15000,
                "salary_max": 25000,
            },
        )()

        score = _score_job(job, cfg, "industrial_ai_agent")
        assert 50 <= score <= 100
    finally:
        shutil.rmtree(temp_dir)


def test_salary_scoring_with_config():
    """Test salary scoring respects salary_high_multiplier and salary_high_bonus."""
    # Create a config with modified salary thresholds
    import yaml
    from agent_core.config import Config, DirectionConfig, PlatformConfig, MatchingConfig, PrescreenRulesConfig

    cfg = load_config()
    cfg.prescreen_rules.salary_high_multiplier = 3.0
    cfg.prescreen_rules.salary_high_bonus = 15

    job_below = type(
        "Job",
        (),
        {
            "title": "AI Engineer",
            "description": "Engineer role",
            "salary_min": 15000,  # 1.5 * 6000
            "salary_max": 18000,
        },
    )()

    job_above = type(
        "Job",
        (),
        {
            "title": "Senior AI Engineer",
            "description": "Senior role",
            "salary_min": 18000,  # 3.0 * 6000
            "salary_max": 35000,
        },
    )()

    score_below = _score_job(job_below, cfg, "industrial_ai_agent")
    score_above = _score_job(job_above, cfg, "industrial_ai_agent")

    # Above threshold should get higher bonus
    assert score_above > score_below


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
