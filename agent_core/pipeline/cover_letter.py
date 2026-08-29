"""Generate HR outreach message for recruitment software (BOSS / Liepin / Zhilian).

Formerly a 150-300 char cover letter; repurposed to a short 打招呼 message sent
to HR on recruitment apps. 150-200 chars, highlights match, no contact info,
no fabrication. Hard facts from the resume are injected as a "pick from these,
do not invent" list (anti-hallucination), mirroring tailor.py's approach.
"""

import logging
import re
from pathlib import Path

from agent_core.config import load_resume
from agent_core.llm.providers import call_llm_with_retry
from agent_core.pipeline.tailor import extract_hard_facts

logger = logging.getLogger(__name__)

# Low temperature: outreach message is factual highlighting, not creative writing.
HR_MESSAGE_TEMPERATURE = 0.4

HR_MESSAGE_PROMPT = """你是求职者，要在招聘软件（BOSS直聘/猎聘/智联等）上给HR发第一条打招呼消息。

目标职位：{title} @ {company} | {location}
JD 摘要：{description}
你的简历：{resume}

要求：
- 150-200 个中文字符（含标点）
- 开头简短问候，直接切题（不要"尊敬的领导"等套话）
- 突出与该岗位最匹配的 2-3 个优势（从简历真实经历里挑，不许编造）
- 表达求职意向 + 一个软钩子（如"期待进一步沟通"）
- 口语化、真诚，不轻浮不谄媚
- 不要留电话/邮箱/微信号（招聘软件内置联系方式）
- 不要用 markdown、不要列表、不要换行分段，输出一段纯文本
- 以下是你简历里的真实事实，可在消息中引用相关项，但不得编造此清单之外的经历或数字：{hard_facts}

只输出这段消息文本，不要任何前后缀说明。"""


def _format_facts(facts, max_items=40):
    """Render hard facts as a compact list for prompt injection."""
    items = [f"日期:{d}" for d in facts["dates"]] + [f"数字:{n}" for n in facts["numbers"]]
    if len(items) > max_items:
        items = items[:max_items] + [f"...(+{len(items) - max_items})"]
    return "; ".join(items) if items else "(无)"


async def generate_cover_letter(
    job, config, llm_provider, direction=None, feedback=None, timeout: float | None = None
):
    """Generate an HR outreach message (150-200 chars) for recruitment software.

    Function name kept for backward compat with cli/tools callers; semantics
    changed from cover letter to HR 打招呼 message. Optional `feedback` from a
    human reviewer is appended to steer regeneration.
    """
    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:2000]
    except (FileNotFoundError, ValueError):
        resume = (
            f"Candidate applying for {job.title} at {job.company}. "
            "Skills include industrial automation, AI Agent engineering, "
            "and equipment maintenance. (Full resume not available)"
        )  # noqa: E501
    facts = extract_hard_facts(resume)
    prompt = HR_MESSAGE_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or config.search_location,
        description=job.description[:2000],
        resume=resume,
        hard_facts=_format_facts(facts),
    )
    if feedback:
        prompt += f"\n\n人工审核改进意见（请据此调整本次生成）：{feedback}"
    resp = await call_llm_with_retry(
        llm_provider,
        messages=[{"role": "user", "content": prompt}],
        temperature=HR_MESSAGE_TEMPERATURE,
        max_tokens=config.llm.max_tokens,
        timeout=timeout,
    )
    return resp.strip()


def save_cover_letter(text, job, output_dir="output"):
    """Save HR outreach message as .md. Returns file path."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    def _sanitize(x):
        return re.sub(r'[\\/*?:"<>|]', "", x)[:20]

    path = f"{output_dir}/{_sanitize(job.company)}_{_sanitize(job.title)}_hrmsg.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# HR打招呼消息\n\n**{job.title}** @ {job.company}\n\n---\n\n{text}\n")
    logger.info(f"HR message: {path}")
    return path
