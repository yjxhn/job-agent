"""Salary negotiation strategy."""

import json
import logging
import re

from agent_core.llm.providers import call_llm_with_retry

logger = logging.getLogger(__name__)

ADVICE_PROMPT = (
    "Salary negotiation coach (Chinese market).\n"
    "\n"
    "Strengths: {strengths}\n"
    "Offer: {company} | {title} | {salary}\n"
    "Structured: 月薪base={monthly_base} 月数={pay_months} 年包={annual_total}\n"
    "Target: {target}\n"
    "Floor (底线，低于此则放弃): {floor}\n"
    "Negotiator (谈判对象): {negotiator}\n"
    "Context: {context}\n"
    "\n"
    "Provide: 1) Anchor number + rationale 2) Leverage points"
    " 3) Concession plan (阶梯让步，底线为最后红线)"
    " 4) Script (2-3 sentences in Chinese, 适配{negotiator}风格)\n"
    "\n"
    "anchor 必须是简洁数字锚点（如 28K*16 / 年包45万 / 月薪30k），不含理由或解释；"
    "锚定理由单独放 rationale 字段（1-2句中文）。\n"
    "\n"
    "Return JSON: "
    '{{"anchor":"简洁数字锚点如 28K*16","rationale":"1-2句锚定理由","leverage":["..."],'
    '"concessions":["..."],"scripts":["..."],'
    '"confidence":"high/medium/low"}}\n'
)


async def get_advice(
    config,
    llm_provider,
    company="",
    title="",
    salary="",
    target="",
    strengths="",
    context="",
    floor="",
    negotiator="",
    monthly_base="",
    pay_months="",
    annual_total="",
):  # noqa: E501
    p = ADVICE_PROMPT.format(
        company=company,
        title=title,
        salary=salary or "未透露",
        target=target or "期望30%涨幅",
        strengths=strengths or "技能匹配",
        context=context or "制造业AI岗位需求旺盛",
        floor=floor or "未设定",
        negotiator=negotiator or "HR",
        monthly_base=monthly_base or "-",
        pay_months=pay_months or "-",
        annual_total=annual_total or "-",
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
