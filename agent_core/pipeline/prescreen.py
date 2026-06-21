"""Prescreen: rule scoring + resume direction selection before LLM matching."""

import logging

from agent_core.platforms.base import Job

logger = logging.getLogger(__name__)


class PrescreenResult:
    def __init__(self, job, score, direction, resume_file, confidence="high"):
        self.job = job
        self.score = score
        self.direction = direction
        self.resume_file = resume_file
        self.confidence = confidence


def prescreen(jobs: list[Job], config) -> list[PrescreenResult]:
    if not jobs:
        return []
    results = []
    for job in jobs:
        direction, resume_file, confidence = _select_direction(job, config)
        job.direction = direction
        score = _score_job(job, config, direction)
        # F10: confidence now affects ranking — low-confidence direction matches
        # get a small penalty so they sort below confident matches.
        if confidence == "low":
            score = max(0.0, score - 10.0)
        results.append(PrescreenResult(job, score, direction, resume_file, confidence))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[: config.matching.prescreen_top_n]


def _select_direction(job, config):
    text = (job.title + " " + job.description).lower()
    scores = {}
    for dname, dcfg in config.directions.items():
        scores[dname] = sum(1 for w in dcfg.feature_words if w.lower() in text)
    if not scores:
        d = list(config.directions.keys())[0]
        return d, config.directions[d].resume_file, "low"
    sorted_dirs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_name, best_score = sorted_dirs[0]
    if len(sorted_dirs) >= 2:
        gap = best_score - sorted_dirs[1][1]
        if gap < 2:
            if best_score < 5:
                return best_name, config.directions[best_name].resume_file, "low"
            return best_name, config.directions[best_name].resume_file, "medium"
    confidence = "low" if best_score < 5 else "high"
    return best_name, config.directions[best_name].resume_file, confidence


def _score_job(job, config, direction):
    score = 50.0
    if direction in config.directions:
        fw = config.directions[direction].feature_words
        text = (job.title + " " + job.description).lower()
        hits = sum(1 for w in fw if w.lower() in text)
        if fw:
            score += (hits / len(fw)) * config.prescreen_rules.feature_weight
        kw = config.directions[direction].keywords
        title_hits = sum(1 for k in kw if k.lower() in job.title.lower())
        if kw:
            score += (title_hits / len(kw)) * config.prescreen_rules.keyword_weight
    if job.salary_max is not None and job.salary_max >= config.min_salary:
        score += 10
    if (
        job.salary_min is not None
        and job.salary_min >= config.min_salary * config.prescreen_rules.salary_high_multiplier
    ):  # noqa: E501
        score += config.prescreen_rules.salary_high_bonus
    return min(score, 100.0)
