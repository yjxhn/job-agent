"""Salary negotiation strategy."""

import json
import logging
import re

logger = logging.getLogger(__name__)

ADVICE_PROMPT = (
    "Salary negotiation coach (Chinese market).\n"
    "\n"
    "Strengths: {strengths}\n"
    "Offer: {company} | {title} | {salary}\n"
    "Target: {target}\n"
    "Context: {context}\n"
    "\n"
    "Provide: 1) Anchor number + rationale 2) Leverage points"
    " 3) Concession plan (if they push back)"
    " 4) Script (2-3 sentences in Chinese)\n"
    "\n"
    "Return JSON: "
    '{{"anchor":"...","leverage":["..."],'
    '"concessions":["..."],"scripts":["..."],'
    '"confidence":"high/medium/low"}}\n'
)


async def get_advice(
    config, llm_provider, company="", title="", salary="", target="", strengths="", context=""
):  # noqa: E501
    p = ADVICE_PROMPT.format(
        company=company,
        title=title,
        salary=salary or "未透露",
        target=target or "期望30%涨幅",
        strengths=strengths or "技能匹配",
        context=context or "制造业AI岗位需求旺盛",
    )
    r = await llm_provider.chat(
        messages=[{"role": "user", "content": p}], temperature=0.4, max_tokens=config.llm.max_tokens
    )
    t = r.strip()
    if "```json" in t:
        t = t.split("```json")[1].split("```")[0].strip()
    elif "```" in t:
        t = t.split("```")[1].split("```")[0].strip()
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", t))
