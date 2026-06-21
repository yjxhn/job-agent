"""Offer evaluation: comprehensive analysis."""

import json
import logging
import re

from agent_core.llm.providers import call_llm_with_retry

logger = logging.getLogger(__name__)

EVAL_PROMPT = (
    "Career advisor: evaluate this job offer.\n"
    "\n"
    "Company: {company} | Title: {title} | Location: {location}\n"
    "Monthly Salary: {salary} | Bonus/Stock: {bonus} | Benefits: {benefits}\n"
    "Level: {level} | Notes: {notes}\n"
    "\n"
    "Analyze: 1) Market competitiveness 2) Total comp breakdown"
    " 3) Hidden costs (COL/tax/commute) 4) Growth potential 5) Risks\n"
    "\n"
    "Return JSON:\n"
    '{{"overall_score":<1-10>,"competitive_score":<1-10>,'
    '"growth_score":<1-10>,"risk_score":<1-10>,'
    '"summary":"<2-3 sentences Chinese>",'
    '"pros":["3-5 pros"],"cons":["3-5 cons"],'
    '"negotiation_levers":["2-3 levers"]}}\n'
)


async def evaluate(
    config,
    llm_provider,
    company="",
    title="",
    location="",
    salary="",
    bonus="",
    benefits="",
    level="",
    notes="",
):  # noqa: E501
    p = EVAL_PROMPT.format(
        company=company,
        title=title,
        location=location,
        salary=salary,
        bonus=bonus or "无",
        benefits=benefits or "五险一金",
        level=level or "未定",
        notes=notes or "无",
    )
    r = await call_llm_with_retry(
        llm_provider,
        messages=[{"role": "user", "content": p}],
        temperature=0.4,
        max_tokens=config.llm.max_tokens,
    )
    t = r.strip()
    if "```json" in t:
        t = t.split("```json")[1].split("```")[0].strip()
    elif "```" in t:
        t = t.split("```")[1].split("```")[0].strip()
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", t))
