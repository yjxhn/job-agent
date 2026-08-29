"""Interview preparation + mock interview."""

import asyncio
import difflib
import json
import logging
import re
import threading
import time
from pathlib import Path

from agent_core.config import load_resume
from agent_core.llm.providers import call_llm_with_retry

logger = logging.getLogger(__name__)

# 2026-08-17: 评估生成必须设置超时。此前 LLM 调用无超时保护，DeepSeek 偶发长时间
# 不返回时前端会一直停在“正在生成面试结果”弹窗（用户反馈十几分钟仍无结果）。
# 超时后由调用方降级为仅保存面试记录 / 内联解析，不让 UI 无限等待。
ASSESSMENT_TIMEOUT_SECONDS = 120.0

# A: 按面试轮次分层(一面/二面/HR面/终面)
# B: 简历项目深挖 + 行为题 STAR 框架
# D: 反问环节
PREDICT_PROMPT = """Interview coach: predict questions for this job across rounds.

Job: {title} @ {company} | {location}
JD: {description}
Resume: {resume}

Generate a structured interview prep plan covering 4 rounds. For each round
produce 3-5 questions with answer outlines (Chinese, 2-3 bullets each):
- 一面 (技术深挖): technical fundamentals + deep-dive on resume projects
- 二面 (系统设计/架构): system design / architecture scenarios
- HR面 (行为文化): behavioral + culture fit, answer in STAR framework (情境/任务/行动/结果)
- 终面 (战略视野): strategic thinking, career vision

For EVERY question give:
- "a": 2-3 concise bullet key points (Chinese, short phrases for quick memorization)
- "sample": a complete spoken-style model answer (Chinese, 120-200 chars,
  natural first-person speech like in a real interview: open with a direct
  answer, then expand with 1-2 concrete details/steps, close with a takeaway)
- "hint": ONE short sentence (Chinese, <=25 chars) telling the candidate what
  the interviewer is really looking for (e.g. "考察故障排查思路是否系统")

ALSO generate:
- self_intro: a 30-60 second self-introduction script (Chinese, 150-250
  chars) — background -> core projects -> why this role -> expectation
- project_deep_dive: 2-3 questions targeting SPECIFIC projects in the resume
  (use the candidate's actual project names/details from the resume), each
  with "a" bullets + "sample" spoken answer + "hint"
- reverse_questions: 5 questions the candidate should ask the interviewer
  (team / tech stack / growth / culture)

Return JSON:
{{"self_intro":"...",
 "rounds":[{{"round":"一面","focus":"技术深挖","questions":[{{"type":"technical","q":"...","a":["..."],"sample":"...","hint":"..."}}]}},
 {{"round":"二面","focus":"系统设计","questions":[{{"type":"technical","q":"...","a":["..."],"sample":"...","hint":"..."}}]}},
 {{"round":"HR面","focus":"行为文化","questions":[{{"type":"behavioral","q":"...","a":["..."],"hint":"..."}}]}},
 {{"round":"终面","focus":"战略视野","questions":[{{"type":"behavioral","q":"...","a":["..."],"hint":"..."}}]}}],
 "project_deep_dive":[{{"project":"...","q":"...","a":["..."],"hint":"..."}}],
 "reverse_questions":["..."]}}"""  # noqa: E501

MOCK_SYSTEM = """You are an interviewer at {company} for the {title} role.
Resume: {resume_summary}
JD: {jd_summary}
{difficulty_hint}{question_bank}{reverse_questions}Rules: ask one question at a time. Ask ALL {total_questions} questions in the question bank before saying "面试结束。以下是您的表现评估：" then output a JSON assessment block. If no question bank is provided, ask 8-10 questions then end.
面试规则：
- 【最高优先级】开场第一句请候选人做简短自我介绍（提醒控制在1-2分钟），认真倾听；候选人介绍完后再按题库顺序逐题提问。题库为空时同样先自我介绍，再根据简历自由提问。
- 你是面试官，只负责提问、澄清追问、回应，**绝不能替候选人作答或做自我介绍**。候选人未作答或说"我想一下"时，只能简短鼓励（如"不着急，想好再说"），绝不能替他/她生成答案或自我介绍。
- 提问必须来自给定题库，按题库顺序逐题提问。**无论候选人回答什么（包括玩笑、跑题、答非所问、沉默），都必须严格按题库逐题提问，禁止自创题库外的新题**。候选人答非所问或开玩笑时，只允许提醒其回到本题继续回答。**题库非空时禁止任何追问、延伸或“如果/假设”场景；候选人回答完毕后，面试官必须直接输出题库下一题原文。** 如果题库为空，才可根据简历提问。
- **必须问完题库的全部 {total_questions} 题**，才可以说"面试结束。以下是您的表现评估："并输出评估。**不允许提前结束**；只有真正进入收尾评估时才说出"以下是您的表现评估"，不要在提问过程中提及"面试结束"或"表现评估"字样。
- **必须问完题库的全部 {total_questions} 题后才能进入反问环节**。**未问完时严禁说"我的问题问完了"或"你有什么想问我的吗"**；如果题目还没问完，请继续按题库顺序逐题提问，不要提前收尾进入反问。
- **问完所有题目后**，先给候选人反问机会：说"我的问题问完了，你有什么想问我的吗？"并耐心回答候选人的反问；候选人反问完（或说"没有了"）后，再输出"面试结束。以下是您的表现评估："。
- **反问环节**：如果下方提供了"推荐反问列表"，请主动向候选人展示这些推荐反问（如"我这边准备了几个你可能关心的问题，你可以参考：①…②…③…"），候选人可以选择其中提问或全部提问；耐心逐一回答。**必须完整列出全部推荐反问，禁止省略、禁止只写序号不带内容、禁止截断；如果列表较长也要全部输出完再结束本条回复。**
Assessment JSON:
{{"overall": 8, "dimensions": {{"technical": {{"score": 8, "comment": "..."}}, "communication": {{"score": 7, "comment": "..."}}, "logic": {{"score": 8, "comment": "..."}}, "project": {{"score": 7, "comment": "..."}}, "culture": {{"score": 8, "comment": "..."}}}}, "strengths": ["..."], "improvements": ["..."]}}
Speak Chinese for questions/evaluations; the JSON block must be valid JSON. Start now."""  # noqa: E501


# 题库模式的绝对规则（MOCK_SYSTEM 之外再追加一次，双保险）。
# 2026-08-16: LLM 曾把“如果线号与图纸不一致怎么办”这类题库外场景包装成追问，
# 仅靠 MOCK_SYSTEM 中的一句约束不够稳，因此从"最多澄清一次"升级为"禁止任何追问"。
_BANK_ABSOLUTE_RULE = """
【题库模式绝对规则 — 最高优先级】
- 下方 Question bank 是唯一合法题目来源。
- 每轮只能输出题库中下一道未问过的题目原文（或与原文基本一致的表述）。
- 候选人回答完毕后，禁止任何追问、延伸、补充或“如果/假设”场景；直接进入题库下一题。
- 候选人回答离题时，只允许说“请针对本题继续回答”，然后等待候选人补充；不得自创新问题。
- 题库全部问完后，才允许进入反问环节。
"""


def _extract_json(text: str) -> dict:
    """Parse LLM JSON output: strip code fences + trailing commas."""
    t = text.strip()
    if "```json" in t:
        t = t.split("```json")[1].split("```")[0].strip()
    elif "```" in t:
        t = t.split("```")[1].split("```")[0].strip()
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", t))


async def predict_questions(
    job, config, llm_provider, direction=None, feedback=None, timeout: float | None = None
):
    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:3000]
    except Exception:
        resume = f"Candidate for {job.title}"
    feedback_block = (
        f"\n\n【用户改进意见 — 必须体现】\n{feedback}\n"
        "请在题库问题、自我介绍、反问中落实以上意见；若意见针对简历/HR消息，"
        "则保持题库合理一致即可。"
        if feedback
        else ""
    )
    prompt = (
        PREDICT_PROMPT.format(
            title=job.title,
            company=job.company,
            location=job.location or config.search_location,
            description=job.description[:3000],
            resume=resume,
        )
        + feedback_block
    )
    # Try strict JSON first; fall back to plain text if the provider rejects
    # response_format or still returns malformed JSON (same strategy as match).
    last_err: Exception | None = None
    for attempt in range(2):
        rf = {"type": "json_object"} if attempt == 0 else None
        try:
            r = await call_llm_with_retry(
                llm_provider,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=config.llm.max_tokens,
                response_format=rf,
                timeout=timeout,
            )
            return _extract_json(r)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(
                "predict_questions attempt %d failed (%s); retrying without strict JSON",
                attempt + 1,
                e,
            )
    raise last_err if last_err else RuntimeError("predict_questions failed")


def _fs(x: str) -> str:
    """Filesystem-safe name, truncated to 20 chars."""
    return re.sub(r'[\\/*?:"<>|]', "", x)[:20]


def _prep_bank_items(prep: dict, focus: str | None = None) -> list[tuple[str, str]]:
    """Return [(formatted_line, question_text), ...] for a prep question bank.

    focus 过滤与文字/实时模式共用同一口径（在 formatted_line 上做包含匹配）。
    """
    items: list[tuple[str, str]] = []
    for rnd in (prep or {}).get("rounds", []):
        tag = f"{rnd.get('round', '')}/{rnd.get('focus', '')}"
        for q in rnd.get("questions", []):
            qtext = q.get("q", "")
            items.append((f"- [{tag}] {qtext}", qtext))
    for pd in (prep or {}).get("project_deep_dive", []):
        qtext = pd.get("q", "")
        items.append((f"- [项目深挖:{pd.get('project', '')}] {qtext}", qtext))
    if focus:
        items = [(line, qtext) for line, qtext in items if focus in line]
    return items


def _prep_bank_lines(prep: dict, focus: str | None = None) -> list[str]:
    """Formatted bank lines after focus filtering (shared by all text prompts)."""
    return [line for line, _q in _prep_bank_items(prep, focus)]


def _prep_bank_question_texts(prep: dict, focus: str | None = None) -> list[str]:
    """Raw question texts after focus filtering (used for asked-question counting)."""
    return [qtext for _line, qtext in _prep_bank_items(prep, focus)]


def save_interview_prep(questions, job, output_dir="output"):
    """Save interview prep as markdown (human) AND JSON (machine).

    The JSON is the canonical structured output -- mock-interview --from-prep
    imports it as a question bank instead of regenerating. The markdown is
    for reading/printing.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    base = f"{output_dir}/{_fs(job.company)}_{_fs(job.title)}_interview"

    # --- metadata ---
    from datetime import datetime

    try:
        from agent_core.config import load_config

        model_name = load_config().llm.model
    except Exception:
        model_name = "unknown"
    meta = {
        "job_id": getattr(job, "id", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": model_name,
        "schema_version": 1,
    }

    # --- markdown ---
    lines = [
        f"# 面试准备\n\n**{job.title}** @ {job.company}\n",
        f"> 生成时间: {meta['generated_at']} | 模型: {meta['model']} | 职位ID: {meta['job_id']}\n",
    ]
    si = questions.get("self_intro")
    if si:
        lines.append("\n## 自我介绍（30-60秒）")
        lines.append(f"{si}")
    for rnd in questions.get("rounds", []):
        lines.append(f"\n## {rnd.get('round', '')} · {rnd.get('focus', '')}")
        for item in rnd.get("questions", []):
            lines.append(f"\n### Q: {item.get('q', '')}")
            hint = item.get("hint")
            if hint:
                lines.append(f"> 💡 {hint}")
            for a in item.get("a", []):
                lines.append(f"- {a}")
            sample = item.get("sample")
            if sample:
                lines.append(f"\n📝 示范回答：{sample}")
    pdd = questions.get("project_deep_dive", [])
    if pdd:
        lines.append("\n## 项目深挖")
        for item in pdd:
            lines.append(f"\n### {item.get('project', '')}")
            lines.append(f"Q: {item.get('q', '')}")
            hint = item.get("hint")
            if hint:
                lines.append(f"> 💡 {hint}")
            for a in item.get("a", []):
                lines.append(f"- {a}")
            sample = item.get("sample")
            if sample:
                lines.append(f"\n📝 示范回答：{sample}")
    rq = questions.get("reverse_questions", [])
    if rq:
        lines.append("\n## 推荐反问")
        for q in rq:
            lines.append(f"- {q}")
    md_path = base + ".md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # --- JSON (canonical, for mock-interview import) ---
    json_path = base + ".json"
    payload = {
        "meta": meta,
        "job": {"title": job.title, "company": job.company, "location": job.location or ""},
        "self_intro": questions.get("self_intro", ""),
        "rounds": questions.get("rounds", []),
        "project_deep_dive": pdd,
        "reverse_questions": rq,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved: {md_path} + {json_path}")
    return md_path


def load_interview_prep_json(job_id, db) -> dict | None:
    """Load the most recent cached interview-prep JSON for a job.

    C: 缓存复用 -- mock-interview --from-prep reads this instead of regenerating.
    Returns None if no cached prep exists.
    """
    row = db.execute(
        "SELECT file_path FROM generated_files "
        "WHERE job_id=? AND file_type='interview_prep' AND file_path LIKE '%.json' "
        "ORDER BY created_at DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    p = Path(row["file_path"])
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"load_interview_prep_json({job_id}) failed: {e}")
        return None


def _parse_assessment(text: str) -> dict | None:
    """Extract the JSON assessment block from the interviewer's final reply (B)."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        r = _extract_json(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    # _extract_json can return ANY JSON type (list/str/number). A non-dict
    # truthy value used to slip past `if assessment:` and crash
    # format_assessment_txt mid-write, leaving a 0-byte _assessment.txt file.
    if not isinstance(r, dict):
        return None
    return r


def format_assessment_txt(
    assessment: dict, job, interrupted: bool = False, mode: str = "text"
) -> str:
    """Format an assessment dict into a human-readable .txt report.

    interrupted=True marks a manual early-end assessment (question bank may be
    incomplete) so readers know the scores are reference-only.
    mode="text" -> 文字面试评估; mode="realtime" -> 实时语音评估 (title line).
    """
    company = getattr(job, "company", "") or ""
    title = getattr(job, "title", "") or ""
    dim_labels = {
        "technical": "技术能力",
        "communication": "沟通表达",
        "logic": "逻辑思维",
        "project": "岗位匹配",
        "culture": "综合文化",
    }
    lines = [
        "实时语音评估" if mode == "realtime" else "文字面试评估",
        f"{title} @ {company}",
        "=" * 50,
        "",
    ]
    if interrupted:
        lines.append("⚠️ 面试中途结束，评估仅供参考（题库可能未全部问完）")
        lines.append("")
    lines += [
        f"🎯 总分: {assessment.get('overall', '?')}/10",
        "",
        "【维度评分】",
    ]
    dims = assessment.get("dimensions") or {}
    for key, label in dim_labels.items():
        d = dims.get(key)
        if isinstance(d, dict):
            lines.append(f"{label}({key}): {d.get('score', '?')}/10")
            if d.get("comment"):
                lines.append(f"  {d['comment']}")
        elif d is not None:
            lines.append(f"{label}({key}): {d}/10")
        lines.append("")
    strengths = assessment.get("strengths") or []
    if strengths:
        lines.append("【优势】")
        for s in strengths:
            lines.append(f"- {s}")
        lines.append("")
    improvements = assessment.get("improvements") or []
    if improvements:
        lines.append("【改进点】")
        for i in improvements:
            lines.append(f"- {i}")
        lines.append("")
    return "\n".join(lines)


def mock_interview(
    job,
    config,
    llm_provider,
    direction=None,
    from_prep=False,
    focus=None,
    difficulty=None,
    db_path="data/agent.db",
):
    """Interactive mock interview (terminal).

    B: multi-dimensional assessment (technical/communication/logic/project/culture).
    C: from_prep=True imports the interview-prep question bank for this job.
    """
    import asyncio

    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:1000]
    except Exception:
        resume = f"Candidate for {job.title}"

    # C: import prep question bank
    question_bank = ""
    total_questions = 0
    prep = None
    if from_prep:
        from agent_core.storage.db import get_db

        db = get_db(db_path)
        try:
            prep = load_interview_prep_json(getattr(job, "id", ""), db)
        finally:
            db.close()
        if prep:
            bank_lines = _prep_bank_lines(prep, focus)
            total_questions = len(bank_lines)
            if focus and not bank_lines:
                print(f"focus={focus} 未命中题库题目，已取消面试")
                return None
            question_bank = (
                (
                    "Question bank (draw questions from these, one at a time):\n"
                    + "\n".join(bank_lines)
                    + "\n\n"
                )
                if bank_lines
                else ""
            )
            print(
                f"已加载 prep 题库: {len(bank_lines)} 题" + (f" (focus={focus})" if focus else "")
            )

        else:
            print("未找到 prep 题库，使用自由面试模式")

    # 推荐反问列表（反问环节展示给候选人）：prep 有则用 prep 的 5 条，否则用默认通用反问
    reverse_questions = ""
    rq_pool = (prep or {}).get("reverse_questions") or []
    if not rq_pool:
        rq_pool = [
            "这个岗位所在团队目前多少人，设备工程师是独立负责一条产线还是按专业分工？",
            "新员工入职后的带教机制是怎样的，前三个月主要在哪些产线历练？",
            "产线目前用的 PLC 品牌和工控系统主要是哪些，有没有国产替代的规划？",
            "部门近两年有没有自动化改造/立库/无人化项目在规划中？",
            "如果入职，您最希望我前三个月帮团队解决一个什么样的问题？",
        ]
    if rq_pool:
        rq_lines = [f"推荐反问 {i + 1}: {q}" for i, q in enumerate(rq_pool)]
        reverse_questions = (
            "Recommended reverse questions (show these to the candidate in the "
            "reverse-question phase, candidate may ask all or some):\n"
            + "\n".join(rq_lines)
            + "\n\n"
        )

    difficulty_hint = f"Difficulty: {difficulty}.\n" if difficulty else ""
    msgs = [
        {
            "role": "system",
            "content": MOCK_SYSTEM.format(
                company=job.company,
                title=job.title,
                resume_summary=resume,
                jd_summary=job.description[:1000],
                question_bank=question_bank,
                reverse_questions=reverse_questions,
                total_questions=total_questions,
                difficulty_hint=difficulty_hint,
            ),
        }
    ]  # noqa: E501
    if question_bank:
        msgs[0]["content"] += _BANK_ABSOLUTE_RULE
    transcript = [f"文字面试记录\n{job.title} @ {job.company}\n{'=' * 50}\n"]
    print(f"\n{'=' * 50}\n模拟面试: {job.title} @ {job.company}\n输入 quit 退出\n{'=' * 50}\n")

    async def _l():
        while True:
            r = await call_llm_with_retry(
                llm_provider, messages=msgs, temperature=0.7, max_tokens=config.llm.max_tokens
            )
            msgs.append({"role": "assistant", "content": r})
            transcript.append(f"面试官: {r}\n")
            print(f"\n面试官: {r}\n")
            if "面试结束" in r or "表现评估" in r:
                # B: parse multi-dimensional assessment
                assessment = _parse_assessment(r)

                # Save transcript
                def _sanitize_name(x):
                    return re.sub(r'[\\/*?:"<>|]', "", x)[:20]

                Path("output").mkdir(parents=True, exist_ok=True)
                base = (
                    f"output/{_sanitize_name(job.company)}"
                    f"_{_sanitize_name(job.title)}_mock_interview"
                )
                with open(base + ".md", "w", encoding="utf-8") as f:
                    f.write("\n".join(transcript))
                if assessment:
                    with open(base + "_assessment.json", "w", encoding="utf-8") as f:
                        json.dump(assessment, f, ensure_ascii=False, indent=2)
                    print(f"\n记录已保存: {base}.md + {base}_assessment.json")
                    print(f"总分: {assessment.get('overall', '?')}/10")
                else:
                    print(f"\n记录已保存: {base}.md")
                return r
            u = input("你: ").strip()
            if u.lower() in ("quit", "exit", "q"):
                transcript.append("用户提前结束面试\n")
                return None
            msgs.append({"role": "user", "content": u})
            transcript.append(f"你: {u}\n")

    return asyncio.run(_l())


# ---------------------------------------------------------------------------
# Stage 3: HTTP/SSE-driven mock interview (Dashboard online)
# Splits the terminal mock_interview() into stateless server-side turns so the
# dashboard can drive a chat UI via POST + SSE. The terminal path is untouched.
# ---------------------------------------------------------------------------

_mock_sessions: dict[str, dict] = {}
_mock_lock = threading.Lock()
_MOCK_SESSION_CAP = 50

# 2026-08-12: 文字模式退出关键词（对齐 realtime_proxy._EXIT_KEYWORDS）。
# 命中时记入 transcript（评估可见）但不发给 LLM——面试官按规则继续问完题库，
# 题库问完/无题库时才直接收尾评估。
_TEXT_EXIT_KEYWORDS = (
    "面试结束",
    "结束面试",
    "面试到此结束",
    "今天的面试就到这里",
    "再见",
    "拜拜",
    "谢谢你的配合",
    "谢谢配合",
    "感谢你的配合",
)


def _asked_so_far(sess: dict) -> int:
    """Count how many bank questions the candidate has actually answered.

    题库模式下优先使用 stream_mock_turn 写入的 asked_indices（按面试官回复命中
    题库哪一题去重计数），避免“我想一下”等中间输入把计数抬高。自由面试（无题库）
    才退回旧逻辑：统计开场自我介绍之后的 user 消息数。
    """
    bank_questions = sess.get("bank_questions") or []
    if bank_questions:
        return len(sess.get("asked_indices") or set())
    count = 0
    for msg in sess.get("msgs", []):
        if msg.get("role") == "user" and msg.get("content", "").strip():
            count += 1
    # First user message is the opening trigger, not an answer
    return max(0, count - 1)


def _normalize_bank_text(text: str) -> str:
    """Remove punctuation/whitespace so question matching tolerates LLM rewording."""
    return re.sub(r"[\s\*\#\-：:？?。，,！!、（）()]+", "", text or "").lower()


def _match_bank_question(reply: str, questions: list[str]) -> int:
    """Return index of the bank question asked in reply, or -1.

    优先做归一化后的全文包含；失败时用最长公共子串兜底（LLM 偶尔改写题目，
    如把“你在这个项目中负责”写成“你在紫龙工厂……中负责”）。
    """
    rn = _normalize_bank_text(reply)
    if not rn:
        return -1
    best_idx, best_len = -1, 0
    for idx, q in enumerate(questions):
        qn = _normalize_bank_text(q)
        if qn and qn in rn:
            return idx
        if qn:
            m = difflib.SequenceMatcher(None, qn, rn).find_longest_match(0, len(qn), 0, len(rn))
            if m.size > best_len:
                best_idx, best_len = idx, m.size
    if best_idx >= 0 and best_len >= max(8, len(_normalize_bank_text(questions[best_idx])) * 0.5):
        return best_idx
    return -1


def _build_mock_context(
    job, config, direction, from_prep, focus, difficulty, db_path="data/agent.db"
):
    """Build initial msgs/transcript for a mock interview session.

    Shared by terminal mock_interview() and HTTP stream_mock_turn(). Returns
    (msgs, transcript, note) where note is a status string for the caller.
    """
    if direction is None:
        direction = getattr(job, "direction", "") or (
            list(config.directions.keys())[0] if config.directions else ""
        )  # noqa: E501
    try:
        resume = load_resume(config, direction)[:1000]
    except Exception:
        resume = f"Candidate for {job.title}"

    question_bank = ""
    total_questions = 0
    note = ""
    prep = None
    if from_prep:
        from agent_core.storage.db import get_db

        db = get_db(db_path)
        try:
            prep = load_interview_prep_json(getattr(job, "id", ""), db)
        finally:
            db.close()
        if prep:
            bank_lines = _prep_bank_lines(prep, focus)
            total_questions = len(bank_lines)
            question_bank = (
                (
                    "Question bank (draw questions from these, one at a time):\n"
                    + "\n".join(bank_lines)
                    + "\n\n"
                )
                if bank_lines
                else ""
            )
            if focus and not bank_lines:
                # focus 过滤后题库为空：不注入题库段；由 start_mock_session 负责拦截
                note = f"focus={focus} 未命中题库题目，进行自由面试"
            else:
                note = f"已加载 prep 题库: {len(bank_lines)} 题" + (
                    f" (focus={focus})" if focus else ""
                )
        else:
            note = "未找到 prep 题库，使用自由面试模式"

    # 推荐反问列表（反问环节展示给候选人）：prep 有则用 prep 的 5 条，否则用默认通用反问
    reverse_questions = ""
    rq_pool = (prep or {}).get("reverse_questions") or []
    if not rq_pool:
        rq_pool = [
            "这个岗位所在团队目前多少人，设备工程师是独立负责一条产线还是按专业分工？",
            "新员工入职后的带教机制是怎样的，前三个月主要在哪些产线历练？",
            "产线目前用的 PLC 品牌和工控系统主要是哪些，有没有国产替代的规划？",
            "部门近两年有没有自动化改造/立库/无人化项目在规划中？",
            "如果入职，您最希望我前三个月帮团队解决一个什么样的问题？",
        ]
    if rq_pool:
        rq_lines = [f"推荐反问 {i + 1}: {q}" for i, q in enumerate(rq_pool)]
        reverse_questions = (
            "Recommended reverse questions (show these to the candidate in the "
            "reverse-question phase, candidate may ask all or some):\n"
            + "\n".join(rq_lines)
            + "\n\n"
        )

    difficulty_hint = f"Difficulty: {difficulty}.\n" if difficulty else ""
    msgs = [
        {
            "role": "system",
            "content": MOCK_SYSTEM.format(
                company=job.company,
                title=job.title,
                resume_summary=resume,
                jd_summary=job.description[:1000],
                question_bank=question_bank,
                reverse_questions=reverse_questions,
                total_questions=total_questions,
                difficulty_hint=difficulty_hint,
            ),
        }
    ]  # noqa: E501
    if question_bank:
        msgs[0]["content"] += _BANK_ABSOLUTE_RULE
    transcript = [f"文字面试记录\n{job.title} @ {job.company}\n{'=' * 50}\n"]
    return msgs, transcript, note, prep, total_questions


def start_mock_session(
    job,
    config,
    llm_provider,
    direction=None,
    from_prep=False,
    focus=None,
    difficulty=None,
    db_path="data/agent.db",
) -> dict:
    """Create a server-side mock interview session. Returns session info dict.

    Does NOT call the LLM; the caller requests the opening turn via
    stream_mock_turn(session_id, user_text=None). Returns {"ok": False, ...}
    when the focus keyword does not match any prep question (D2: block start).
    """
    msgs, transcript, note, prep, total_questions = _build_mock_context(
        job, config, direction, from_prep, focus, difficulty, db_path=db_path
    )
    bank_questions: list[str] = []
    if prep:
        bank_questions = _prep_bank_question_texts(prep, focus)
        if focus and not bank_questions:
            return {
                "ok": False,
                "message": f"focus={focus} 未命中题库题目，请修改或清空后重试",
            }
    session_id = f"mock_{getattr(job, 'id', 'x')}_{int(time.time() * 1000)}"
    with _mock_lock:
        if len(_mock_sessions) >= _MOCK_SESSION_CAP:
            oldest_id = min(_mock_sessions, key=lambda k: _mock_sessions[k]["created_at"])
            _mock_sessions.pop(oldest_id, None)
        _mock_sessions[session_id] = {
            "msgs": msgs,
            "transcript": transcript,
            "job": job,
            "config": config,
            "provider": llm_provider,
            "question_bank": prep,
            "bank_questions": bank_questions,
            "asked_indices": set(),
            "focus": focus,
            "db_path": db_path,
            "total_questions": total_questions,
            "created_at": time.time(),
            "ended": False,
        }
    return {
        "ok": True,
        "session_id": session_id,
        "note": note,
        "job_title": job.title,
        "job_company": job.company,
    }


async def stream_mock_turn(session_id, user_text=None):
    """One interview turn driven by HTTP/SSE.

    If user_text is given (non-empty), it is appended to msgs first. Then the
    LLM reply is streamed. Yields event dicts:
      {"type": "delta", "text": ...}   - incremental reply chunk
      {"type": "turn_end"}             - reply finished, interview continues
      {"type": "end", "assessment": ...} - interview concluded, saved
      {"type": "error", "text": ...}   - session missing or LLM failure
    """
    with _mock_lock:
        sess = _mock_sessions.get(session_id)
    if not sess:
        yield {"type": "error", "text": "会话不存在或已结束"}
        return
    provider = sess["provider"]
    if user_text:
        sess["transcript"].append(f"你: {user_text}\n")
        # 2026-08-12: exit keywords (面试结束/再见/拜拜/谢谢配合 etc.) — recorded in
        # transcript (assessment sees them) but NOT sent to the LLM, so the
        # interviewer keeps asking per rule 5. If the bank is complete (or there
        # is no bank), conclude with an assessment right away.
        if any(kw in user_text for kw in _TEXT_EXIT_KEYWORDS):
            total = sess.get("total_questions", 0)
            asked = _asked_so_far(sess)
            if total and asked < total:
                logger.info(
                    "mock interview: exit keyword %r, %d/%d asked -> force continue",
                    user_text,
                    asked,
                    total,
                )
            else:
                logger.info(
                    "mock interview: exit keyword %r, bank complete -> assessment", user_text
                )
                transcript_text = "\n".join(sess["transcript"])
                yield {"type": "generating"}
                assessment = None
                try:
                    assessment = await generate_assessment_from_transcript(
                        transcript_text,
                        sess["job"],
                        sess["config"],
                        sess["provider"],
                        sess.get("question_bank"),
                        focus=sess.get("focus"),
                    )
                except Exception:
                    logger.exception("exit-intent assessment failed")
                _save_mock_transcript(sess, assessment)
                with _mock_lock:
                    _mock_sessions.pop(session_id, None)
                base = f"{_fs(sess['job'].company)}_{_fs(sess['job'].title)}_mock_interview"
                md_name = base + ".md"
                yield {
                    "type": "end",
                    "assessment": assessment,
                    "md_name": md_name,
                    "assessment_name": (
                        md_name.replace(".md", "_assessment.txt") if assessment else None
                    ),
                }
                return
        sess["msgs"].append({"role": "user", "content": user_text})

    full: list[str] = []
    _END_MARKER = "以下是您的表现评估"
    _sent_len = 0  # 已流式发送的字符数（2026-08-12: 结束语之后的评估 JSON 不再发给前端）
    _MAX_EMPTY_STREAM_RETRIES = 2
    _last_stream_error: str | None = None
    for _attempt in range(_MAX_EMPTY_STREAM_RETRIES):
        full = []
        _sent_len = 0
        _last_stream_error = None
        try:
            async for delta in provider.chat_stream(
                sess["msgs"], temperature=0.7, max_tokens=sess["config"].llm.max_tokens
            ):
                full.append(delta)
                full_text = "".join(full)
                idx = full_text.find(_END_MARKER)
                if idx >= 0:
                    # 结束语已出现：只发到结束语末尾（含紧随的冒号/空格），
                    # 后续（评估 JSON）吞掉不展示。limit 需包含 marker 后的标点，
                    # 否则跨 delta 边界时冒号会被漏掉（2026-08-12 实测修复）。
                    limit = idx + len(_END_MARKER)
                    while limit < len(full_text) and full_text[limit] in ("：", ":"):
                        limit += 1
                    if limit > _sent_len:
                        yield {"type": "delta", "text": full_text[_sent_len:limit]}
                        _sent_len = limit
                    continue
                yield {"type": "delta", "text": full_text[_sent_len:]}
                _sent_len = len(full_text)
        except Exception as e:
            _last_stream_error = str(e)
            logger.exception(
                "mock interview stream failed (attempt %d/%d)",
                _attempt + 1,
                _MAX_EMPTY_STREAM_RETRIES,
            )
        if "".join(full).strip():
            break
        logger.warning(
            "mock interview stream returned empty content (attempt %d/%d), retrying",
            _attempt + 1,
            _MAX_EMPTY_STREAM_RETRIES,
        )

    reply = "".join(full)
    if not reply.strip():
        logger.error("mock interview stream empty after %d attempts", _MAX_EMPTY_STREAM_RETRIES)
        msg = (
            "面试官没有生成回复，请稍后重试"
            if not _last_stream_error
            else f"面试官没有生成回复（{_last_stream_error}），请稍后重试"
        )
        yield {"type": "error", "text": msg}
        return
    sess["msgs"].append({"role": "assistant", "content": reply})
    # 题库模式：按“面试官本轮回复命中了题库哪一题”去重计数，替代旧的消息数估算。
    # 澄清/反问/收尾回复不会命中题目，因此不会抬高已问数。
    if user_text and sess.get("bank_questions") and "以下是您的表现评估" not in reply:
        if "我的问题问完了" not in reply and "你有什么想问我的吗" not in reply:
            matched = _match_bank_question(reply, sess["bank_questions"])
            if matched >= 0:
                sess.setdefault("asked_indices", set()).add(matched)
    # 2026-08-12: transcript 与前端显示统一——结束语后的评估 JSON 不记录（否则
    # 下载记录含 JSON 与界面不一致，且独立评估读 transcript 会被面试官自评干扰）。
    _tr = reply
    _idx = _tr.find("以下是您的表现评估")
    if _idx >= 0:
        _tr = _tr[:_idx].rstrip()
    sess["transcript"].append(f"面试官: {_tr}\n")

    # E: 反问入口——只要面试官进入反问环节，这一轮就只交还控制权给候选人，
    # 绝不在同一轮触发结束/评估。即使 LLM 在同一段回复里既问“有什么想问的”
    # 又写“以下是您的表现评估”，也必须等候选人先回应反问。
    if "我的问题问完了" in reply or "你有什么想问我的吗" in reply:
        total = sess.get("total_questions", 0)
        if total and _asked_so_far(sess) < total:
            logger.warning(
                f"mock interview: interviewer entered reverse-question early "
                f"({_asked_so_far(sess)}/{total}), forcing continue"
            )
        else:
            logger.info("mock interview: reverse-question phase started, waiting for candidate")
        yield {"type": "turn_end"}
        return

    # C: 唯一结束语（"以下是您的表现评估"）才判定结束，避免提问过程中
    # 顺口提及"表现评估/面试结束"字样被误判为收尾。
    # D: 服务端计数兜底——已问题数 < 题库总数时，即使 LLM 提前说结束也强制继续。
    if "以下是您的表现评估" in reply:
        total = sess.get("total_questions", 0)
        if total and _asked_so_far(sess) < total:
            logger.warning(
                f"mock interview: LLM ended early ({_asked_so_far(sess)}/{total}), forcing continue"
            )
            yield {"type": "turn_end"}
            return
        transcript_text = "\n".join(sess["transcript"])
        yield {"type": "generating"}  # notify UI: files are being written
        assessment = None
        try:
            assessment = await generate_assessment_from_transcript(
                transcript_text,
                sess["job"],
                sess["config"],
                sess["provider"],
                sess.get("question_bank"),
                focus=sess.get("focus"),
            )
        except Exception:
            logger.exception("text-mode assessment failed, falling back to inline")
            assessment = _parse_assessment(reply)
        _save_mock_transcript(sess, assessment)
        with _mock_lock:
            _mock_sessions.pop(session_id, None)
        base = f"{_fs(sess['job'].company)}_{_fs(sess['job'].title)}_mock_interview"
        md_name = base + ".md"
        yield {
            "type": "end",
            "assessment": assessment,
            "md_name": md_name,
            "assessment_name": (md_name.replace(".md", "_assessment.txt") if assessment else None),
        }
    else:
        yield {"type": "turn_end"}


def _save_mock_transcript(sess, assessment, interrupted: bool = False) -> None:
    """Persist transcript .md (+ assessment .txt). Mirrors terminal mock_interview."""
    job = sess["job"]
    base = f"output/{_fs(job.company)}_{_fs(job.title)}_mock_interview"
    Path("output").mkdir(parents=True, exist_ok=True)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(sess["transcript"]))
    if assessment:
        with open(base + "_assessment.txt", "w", encoding="utf-8") as f:
            f.write(format_assessment_txt(assessment, job, interrupted=interrupted))
    try:
        from agent_core.pipeline.file_catalog import TYPE_MOCK_INTERVIEW, catalog_file
        from agent_core.storage.db import get_db

        db = get_db(sess.get("db_path", "data/agent.db"))
        try:
            # 评估失败时只有 transcript：不得登记不存在的 _assessment.txt，
            # 否则「已生成文件」会出现幽灵文件、进度弹窗的查看按钮 404。
            paths = [base + ".md"]
            if assessment:
                paths.append(base + "_assessment.txt")
            for path in paths:
                catalog_file(
                    db,
                    getattr(job, "id", ""),
                    TYPE_MOCK_INTERVIEW,
                    path,
                    company=job.company,
                    job_title=job.title,
                )
        finally:
            db.close()
    except Exception:
        logger.debug("catalog_file skipped for mock transcript", exc_info=True)


async def end_mock_session(session_id) -> bool | dict:
    """Manually end a session (user clicked 结束).

    2026-08-12: 手动结束也生成评估；题库未问完时标注“中途结束”。
    评估生成失败时降级为仅保存记录，且不再返回/登记不存在的评估文件。
    """
    with _mock_lock:
        sess = _mock_sessions.pop(session_id, None)
    if not sess:
        return False
    total = sess.get("total_questions", 0)
    asked = _asked_so_far(sess)
    interrupted = bool(total and asked < total)
    if interrupted:
        sess["transcript"].append("用户提前结束面试" + chr(10))
    assessment = None
    try:
        assessment = await generate_assessment_from_transcript(
            chr(10).join(sess["transcript"]),
            sess["job"],
            sess["config"],
            sess["provider"],
            sess.get("question_bank"),
            focus=sess.get("focus"),
        )
    except Exception:
        logger.exception("manual-end assessment failed, saving transcript only")
    _save_mock_transcript(sess, assessment, interrupted=interrupted)
    base = f"output/{_fs(sess['job'].company)}_{_fs(sess['job'].title)}_mock_interview"
    md_name = base.split("/")[-1] + ".md"
    return {
        "ok": True,
        "md": md_name,
        "assessment": md_name.replace(".md", "_assessment.txt") if assessment else None,
    }


def abandon_mock_session(session_id) -> bool:
    """Drop a server-side text mock session without saving files (清空按钮)."""
    with _mock_lock:
        return _mock_sessions.pop(session_id, None) is not None


# ---------------------------------------------------------------------------
# Phase 2: SC2.0 realtime voice interview support
# ---------------------------------------------------------------------------


def build_character_manifest(job, config, question_bank=None, difficulty=None, focus=None):
    """Build SC2.0 character_manifest (interviewer persona) for RealtimeAPI.

    SC2.0 uses character_manifest (not system_role). Includes job context,
    optional question bank from prep, and interview rules (5-7 questions then
    say "面试结束" to trigger the exit-intent -> DeepSeek assessment flow).
    """
    parts = [
        f"你是一位在{job.company}面试{job.title}职位的面试官。",
        f"工作地点：{job.location or '未指定'}。",
    ]
    if difficulty:
        parts.append(f"面试难度：{difficulty}。")
    parts.append("你的任务是面试候选人，评估其与该岗位的匹配度。")
    if question_bank:
        bank_lines = _prep_bank_lines(question_bank, focus)
        if bank_lines:
            parts.append(
                f"请参考以下题库提问（共 {len(bank_lines)} 题，每次只问一个问题，必须逐题问完）："
            )
            parts.extend(bank_lines)
    # 2026-08-12: 推荐反问注入（prep 有则用 prep 的 5 条，否则默认通用反问）——
    # 反问环节主动展示给候选人，候选人可任选提问。
    rq_pool = (question_bank or {}).get("reverse_questions") or []
    if not rq_pool:
        rq_pool = [
            "这个岗位所在团队目前多少人，设备工程师是独立负责一条产线还是按专业分工？",
            "新员工入职后的带教机制是怎样的，前三个月主要在哪些产线历练？",
            "产线目前用的 PLC 品牌和工控系统主要是哪些，有没有国产替代的规划？",
            "部门近两年有没有自动化改造/立库/无人化项目在规划中？",
            "如果入职，您最希望我前三个月帮团队解决一个什么样的问题？",
        ]
    if rq_pool:
        parts.append(
            "推荐反问列表（问完题目后主动展示给候选人，候选人可任选其中提问，耐心逐一回答；"
            "必须完整列出全部条目，禁止省略或只写序号无内容）：\n"
            + "\n".join(f"- {q}" for q in rq_pool)
        )
    parts.extend(
        [
            "面试规则：",
            "1. 每次只问一个问题，等候选人回答后再问下一个",
            "2. 【最高优先级】开场第一句请候选人做简短自我介绍（提醒控制在1-2分钟），认真倾听；候选人介绍完后再按题库顺序逐题提问。题库为空时同样先自我介绍，再根据简历自由提问",
            '3. 你是面试官，只负责提问、澄清追问、回应，绝不能替候选人作答或做自我介绍。候选人未作答或说"我想一下"时只能简短鼓励，绝不能替他/她生成答案',
            "4. 提问必须来自给定题库，按题库顺序逐题提问。**无论候选人回答什么（包括玩笑、跑题、答非所问、沉默），都必须严格按题库逐题提问，禁止自创题库外的新题**。题库非空时禁止任何追问、延伸或“如果/假设”场景；候选人回答后直接输出题库下一题原文。题库为空时才可根据简历提问",
            '5. 必须问完题库的全部题目后才能结束面试，**不允许提前结束**；只有真正进入收尾评估时才说出"面试结束"或"以下是你的表现评估"，不要在提问过程中提及这些字样',
            '6. 问完所有题目后，先给候选人反问机会：说"我的问题问完了，你有什么想问我的吗？"并耐心回答候选人的反问；候选人反问完（或说"没有了"）后，再输出"面试结束"，说完后立即停止',
            '7. 说完"面试结束"后不要再输出任何内容（包括评估文本或JSON）——面试评估由系统在后台自动生成，你无需朗读或输出评估内容，直接停止即可',
            "8. 用中文面试",
            "9. 题库非空时禁止任何追问、延伸或“如果/假设”场景；题库为空时才可根据候选人回答适当追问或深入",
        ]
    )
    return "\n".join(parts)


async def generate_assessment_from_transcript(
    transcript,
    job,
    config,
    provider,
    question_bank=None,
    focus=None,
    timeout: float = ASSESSMENT_TIMEOUT_SECONDS,
):
    """Generate 5-dim assessment from transcript via DeepSeek (dual-model).

    Called after the interview ends (realtime TTSEnded, or text-mode 面试结束).
    If question_bank is provided, the standard answer points are included so
    DeepSeek can score against expected key points (objective rubric). focus
    narrows the rubric to the questions actually asked in this session.
    Reuses _parse_assessment to extract the JSON assessment block.

    ``timeout`` guards the whole LLM call (including retries) so a hung
    upstream request cannot leave the dashboard stuck on "正在生成评估" forever.
    """
    bank_hint = ""
    if question_bank:
        bank_lines = []
        for rnd in question_bank.get("rounds", []):
            tag = f"{rnd.get('round', '')}/{rnd.get('focus', '')}"
            for q in rnd.get("questions", []):
                qtext = q.get("q", "")
                if focus and focus not in f"- [{tag}] {qtext}":
                    continue
                ql = f"- Q: {qtext}"
                ans = q.get("a", [])
                if ans:
                    ql += chr(10) + "  标准答案要点: " + "; ".join(ans)
                bank_lines.append(ql)
        for pd in question_bank.get("project_deep_dive", []):
            qtext = pd.get("q", "")
            if focus and focus not in f"- [项目深挖:{pd.get('project', '')}] {qtext}":
                continue
            ql = f"- [项目:{pd.get('project', '')}] Q: {qtext}"
            ans = pd.get("a", [])
            if ans:
                ql += chr(10) + "  标准答案要点: " + "; ".join(ans)
            bank_lines.append(ql)
        if bank_lines:
            bank_hint = chr(10) + chr(
                10
            ) + "本次面试题库及标准答案要点（请对照判断候选人答到了哪些要点，" "未答到或答错的在对应维度comment中指出，据此客观打分）：" + chr(10) + chr(
                10
            ).join(
                bank_lines
            )
    prompt = (
        "你是一位面试评估专家。以下是候选人参加"
        f"{job.title}@{job.company}岗位的模拟面试记录。"
        "请根据面试记录，从以下5个维度评分（1-10）："
        "technical（技术能力）、communication（沟通表达）、"
        "logic（逻辑思维）、project（项目经验）、culture（文化匹配）。"
        "并给出总体评分(overall)、优势(strengths)和改进点(improvements)。"
        f"{chr(10)}{chr(10)}面试记录：{chr(10)}{transcript}{chr(10)}"
        f"{bank_hint}{chr(10)}{chr(10)}"
        '返回JSON：{"overall":N,"dimensions":{"technical":{"score":N,"comment":"..."},'
        '"communication":{"score":N,"comment":"..."},"logic":{"score":N,"comment":"..."},'
        '"project":{"score":N,"comment":"..."},"culture":{"score":N,"comment":"..."}},'
        '"strengths":["..."],"improvements":["..."]}'
    )
    # 先普通输出，解析失败再用 response_format=json_object 强制一次 JSON。
    # 2026-08-18 实测：DeepSeek 偶发返回空/非 JSON，导致实时语音没有评估文件。
    last_err: Exception | None = None
    for attempt, response_format in enumerate((None, {"type": "json_object"})):
        try:
            resp = await asyncio.wait_for(
                call_llm_with_retry(
                    provider,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=config.llm.max_tokens,
                    response_format=response_format,
                ),
                timeout=timeout,
            )
            parsed = _parse_assessment(resp)
            if parsed is not None:
                return parsed
            logger.warning(
                "mock interview assessment parse failed on attempt %d "
                "(resp len=%d); retrying with strict JSON",
                attempt + 1,
                len(resp or ""),
            )
        except TimeoutError:
            logger.warning(
                "mock interview assessment timed out after %.1fs; caller will fall back",
                timeout,
            )
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(
                "mock interview assessment call failed on attempt %d: %s",
                attempt + 1,
                e,
            )
    if last_err is not None:
        raise last_err
    return None
