"""Cover letter generation using LLM."""

import logging
import re
from pathlib import Path

from agent_core.config import load_resume

logger = logging.getLogger(__name__)

COVER_PROMPT = """Write a professional cover letter in Chinese.

Job: {title} @ {company} | {location}
JD: {description}
Resume: {resume}

Requirements:
- 150-300 Chinese characters
- Why interested in this role and company
- 2-3 most relevant skills/experiences from resume
- Professional tone, no flattery
- Output ONLY the letter text. No headers or signatures."""


async def generate_cover_letter(job, config, llm_provider, direction=None):
    if direction is None:
        direction = getattr(job, 'direction', '') or config.directions and list(config.directions.keys())[0]  # noqa: E501
    try:
        resume = load_resume(config, direction)[:2000]
    except (FileNotFoundError, ValueError):
        resume = f"Candidate applying for {job.title} at {job.company}. Skills include industrial automation, AI Agent engineering, and equipment maintenance. (Full resume not available for external applications)"  # noqa: E501
    prompt = COVER_PROMPT.format(title=job.title, company=job.company,
                                 location=job.location or config.search_location,
                                 description=job.description[:2000], resume=resume)
    resp = await llm_provider.chat(messages=[{"role":"user","content":prompt}],
                                   temperature=0.5, max_tokens=1024)
    return resp.strip()


def save_cover_letter(text, job, output_dir="output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    def _sanitize(x):
        return re.sub(r'[\\/*?:"<>|]', '', x)[:20]
    path = f"{output_dir}/{_sanitize(job.company)}_{_sanitize(job.title)}_cover.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 求职信\n\n**{job.title}** @ {job.company}\n\n---\n\n{text}\n")
    logger.info(f"Cover letter: {path}")
    return path
