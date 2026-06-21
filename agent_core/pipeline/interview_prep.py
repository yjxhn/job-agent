"""Interview preparation + mock interview."""

import json
import logging
import re
from pathlib import Path

from agent_core.config import load_resume

logger = logging.getLogger(__name__)

PREDICT_PROMPT = """Interview coach: predict questions for this job.

Job: {title} @ {company} | {location}
JD: {description}
Resume: {resume}

Generate in 3 categories: technical (3-5), behavioral (2-3), project deep-dive (2-3).
Each with question + answer outline (2-3 bullet points in Chinese).
Return JSON: {{"technical":[{{"q":"...","a":["..."]}}],"behavioral":[{{"q":"...","a":["..."]}}],"project":[{{"q":"...","a":["..."]}}]}}"""  # noqa: E501

MOCK_SYSTEM = """You are an interviewer at {company} for the {title} role.
Resume: {resume_summary}
JD: {jd_summary}
Rules: ask one question at a time, alternate technical/behavioral/project. After 5-7 questions say "面试结束。以下是您的表现评估：" then give: strengths(2-3), improvements(2-3), score(1-10). Speak Chinese. Start now."""  # noqa: E501


async def predict_questions(job, config, llm_provider, direction=None):
    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:3000]
    except Exception:
        resume = f"Candidate for {job.title}"
    prompt = PREDICT_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or config.search_location,
        description=job.description[:3000],
        resume=resume,
    )
    r = await llm_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=config.llm.max_tokens,
    )  # noqa: E501
    t = r.strip()
    if "```json" in t:
        t = t.split("```json")[1].split("```")[0].strip()
    elif "```" in t:
        t = t.split("```")[1].split("```")[0].strip()
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", t))


def save_interview_prep(questions, job, output_dir="output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    def _fs(x):
        return re.sub(r'[\\/*?:"<>|]', "", x)[:20]

    p = f"{output_dir}/{_fs(job.company)}_{_fs(job.title)}_interview.md"
    lines = [f"# 面试准备\n\n**{job.title}** @ {job.company}\n"]
    for cat, cn in [("technical", "技术"), ("behavioral", "行为"), ("project", "项目深挖")]:
        lines.append(f"## {cn}")
        for item in questions.get(cat, []):
            lines.append(f"\n### Q: {item['q']}")
            for a in item.get("a", []):
                lines.append(f"- {a}")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Saved: {p}")
    return p


def mock_interview(job, config, llm_provider, direction=None):
    import asyncio
    import re

    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:1000]
    except Exception:
        resume = f"Candidate for {job.title}"
    msgs = [
        {
            "role": "system",
            "content": MOCK_SYSTEM.format(
                company=job.company,
                title=job.title,
                resume_summary=resume,
                jd_summary=job.description[:1000],
            ),
        }
    ]  # noqa: E501
    transcript = [f"模拟面试记录\n{job.title} @ {job.company}\n{'='*50}\n"]
    print(f"\n{'='*50}\n模拟面试: {job.title} @ {job.company}\n输入 quit 退出\n{'='*50}\n")

    async def _l():
        while True:
            r = await llm_provider.chat(messages=msgs, temperature=0.7, max_tokens=1024)
            msgs.append({"role": "assistant", "content": r})
            transcript.append(f"面试官: {r}\n")
            print(f"\n面试官: {r}\n")
            if "面试结束" in r or "表现评估" in r:
                # Save transcript
                def _sanitize_name(x):
                    return re.sub(r'[\\/*?:"<>|]', "", x)[:20]

                path = (
                    f"output/{_sanitize_name(job.company)}"
                    f"_{_sanitize_name(job.title)}_mock_interview.md"
                )
                Path("output").mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(transcript))
                print(f"\n记录已保存: {path}")
                return r
            u = input("你: ").strip()
            if u.lower() in ("quit", "exit", "q"):
                transcript.append("用户提前结束面试\n")
                return None
            msgs.append({"role": "user", "content": u})
            transcript.append(f"你: {u}\n")

    return asyncio.run(_l())
