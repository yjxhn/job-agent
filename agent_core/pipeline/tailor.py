"""Tailor resume for a specific job using LLM. Output .docx + .md + open job link."""

import logging
import re
import webbrowser
from pathlib import Path

from agent_core.config import load_resume

logger = logging.getLogger(__name__)

TAILOR_PROMPT = (
    "You are a resume tailoring expert. Adapt the resume below for a specific job.\n"
    "\n"
    "Job: {title} @ {company} | {location}\n"
    "JD: {description}\n"
    "\n"
    "Original Resume:\n"
    "{resume}\n"
    "\n"
    "Rules:\n"
    "1. Keep ALL facts exactly as-is (dates, companies, titles, skills)\n"
    "2. Reorder/rephrase bullets to emphasize skills relevant to this job\n"
    "3. Update self-summary to highlight match with this role\n"
    "4. Do NOT invent any experience or skills\n"
    "5. Output tailored resume in clean Markdown with sections: "
    "教育背景, 核心能力 (3-5 most relevant skills for this job), "
    "工作经历/项目经历 (reordered by relevance), 技能, 自我评价\n"
    "\n"
    "Return ONLY the Markdown resume. No other text."
)


async def tailor_resume(job, config, llm_provider, direction=None):
    """Generate a tailored resume for a job. Returns markdown text."""
    if direction is None:
        direction = job.direction
    resume_text = load_resume(config, direction)

    prompt = TAILOR_PROMPT.format(
        title=job.title, company=job.company,
        location=job.location or config.search_location,
        description=job.description[:4000], resume=resume_text)

    response = await llm_provider.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=config.llm.max_tokens)
    return response.strip()


def save_resume(text, job, output_dir="output"):
    """Save tailored resume as .md and .docx. Returns file paths."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[\\/*?:"<>|]', '', job.title)[:30]
    safe_company = re.sub(r'[\\/*?:"<>|]', '', job.company)[:20]
    base = f"{output_dir}/{safe_company}_{safe_title}"

    md_path = f"{base}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"Saved: {md_path}")

    docx_path = f"{base}.docx"
    _save_docx(text, docx_path)
    logger.info(f"Saved: {docx_path}")
    return {"md": md_path, "docx": docx_path}


def _save_docx(text, path):
    """Convert markdown resume to .docx document."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(11)

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:], level=1)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=2)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif re.match(r'^\d+\.\s', line):
            doc.add_paragraph(re.sub(r'^\d+\.\s*', '', line), style="List Number")
        else:
            p = doc.add_paragraph()
            if "**" in line:
                parts = re.split(r'(\*\*.*?\*\*)', line)
                for part in parts:
                    if part.startswith("**") and part.endswith("**"):
                        run = p.add_run(part[2:-2])
                        run.bold = True
                    elif part:
                        p.add_run(part)
            else:
                p.add_run(line)
    doc.save(path)


def open_job_link(job):
    """Open the job posting URL in default browser."""
    urls = job.urls if isinstance(job.urls, dict) else {}
    for _platform, url in urls.items():
        if url:
            logger.info(f"Opening: {url}")
            webbrowser.open(url)
            return
