"""Offer evaluation: comprehensive analysis."""

import json
import logging
import re

from agent_core.llm.providers import call_llm_with_retry

logger = logging.getLogger(__name__)

EVAL_PROMPT = (
    "Career advisor: evaluate this job offer across 8 dimensions.\n"
    "\n"
    "Company: {company} | Title: {title} | Location: {location}\n"
    "Monthly Salary: {salary} | Bonus/Stock: {bonus} | Benefits: {benefits}\n"
    "Level: {level} | Notes: {notes}\n"
    "Offer 原文（供参考，含未结构化细节）：\n{raw_text}\n"
    "\n"
    "Dimensions (1-10, higher is better):\n"
    "1. competitive_score: market competitiveness of total comp and title\n"
    "2. growth_score: career growth, learning, and promotion potential\n"
    "3. risk_score: employment risk and business stability (higher = lower risk / more secure)\n"
    "4. salary_score: satisfaction level of base salary, bonus, and stock\n"
    "5. commute_score: commute convenience and relocation difficulty\n"
    "6. wlb_score: work-life balance\n"
    "7. culture_score: team/culture fit\n"
    "8. stability_score: company stability and job security\n"
    "9. overall_score: comprehensive weighted score\n"
    "\n"
    "Return JSON:\n"
    '{{"overall_score":<1-10>,"competitive_score":<1-10>,"growth_score":<1-10>,'
    '"risk_score":<1-10>,"salary_score":<1-10>,"commute_score":<1-10>,'
    '"wlb_score":<1-10>,"culture_score":<1-10>,"stability_score":<1-10>,'
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
    raw_text="",
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
        raw_text=raw_text or "（无）",
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


COMPARE_PROMPT = (
    "Career advisor: holistically compare these {n} job offers and recommend the best.\n"
    "Do NOT merely compare scores -- weigh the actual offer terms and your evaluation reasoning.\n"
    "\n"
    "{offers_text}\n"
    "\n"
    "Return markdown in Chinese:\n"
    "## 逐项对比\n"
    "（薪资总包 / 成长空间 / 风险与稳定 / 工作生活平衡 / 文化匹配 等关键维度）\n"
    "## 各 Offer 核心优劣\n"
    "## 推荐结论\n"
    "（综合评分仅作参考，不等于最终推荐。若综合评分最高者与成长性/长远潜力最优者不是同一份，须明确表述，例如「虽然A综合评分N更高，但从长远眼光看B在成长性/赛道潜力上更优」，再给出最终推荐及核心理由，确保结论与分数表不矛盾。若某 Offer 尚未评估无评分，基于原文条款判断）\n"
    "## 谈判建议\n"
    "（基于对比的差异化谈判点）\n"
)


async def compare(config, llm_provider, offers):
    """LLM re-compares multiple offers (terms + eval results) -> markdown analysis."""
    lines = []
    for i, o in enumerate(offers, 1):
        r = o.get("result") or {}
        p = o.get("parsed") or {}
        has_eval = r.get("overall_score") is not None
        head = "Offer {n}：\n  公司: {company} | 职位: {title} | 地点: {loc}\n  月薪base: {mb} | 发放月数: {pm} | 年总包: {at}\n".format(
            n=i,
            company=o.get("company") or p.get("company") or "未命名",
            title=o.get("title") or p.get("title") or "",
            loc=p.get("location", ""),
            mb=p.get("monthly_base", ""),
            pm=p.get("pay_months", ""),
            at=p.get("annual_total", ""),
        )
        if has_eval:
            ev = "  评估: 综合 {ov}/10 (竞争{comp} 成长{gro} 风险{ris} 薪资{sal} 通勤{cm} 平衡{wlb} 文化{cul} 稳定{sta})\n  摘要: {sum}\n  优势: {pros}\n  劣势: {cons}\n".format(
                ov=r.get("overall_score", "-"),
                comp=r.get("competitive_score", "-"),
                gro=r.get("growth_score", "-"),
                ris=r.get("risk_score", "-"),
                sal=r.get("salary_score", "-"),
                cm=r.get("commute_score", "-"),
                wlb=r.get("wlb_score", "-"),
                cul=r.get("culture_score", "-"),
                sta=r.get("stability_score", "-"),
                sum=r.get("summary", ""),
                pros="；".join(r.get("pros") or []),
                cons="；".join(r.get("cons") or []),
            )
        else:
            ev = "  （尚未评估，无评分，请基于原文条款对比）\n"
        lines.append(head + ev + "  原文:\n{raw}\n".format(raw=(o.get("raw_text") or "（无）")))
    prompt = COMPARE_PROMPT.format(n=len(offers), offers_text="\n".join(lines))
    r = await call_llm_with_retry(
        llm_provider,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=config.llm.max_tokens,
    )
    return r.strip()
