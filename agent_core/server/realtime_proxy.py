"""Realtime voice proxy: browser <-> agent-core(WS) <-> Volcengine RealtimeAPI(WS).

Implements the Volcengine binary frame protocol based on the official demo:
https://github.com/MarkShawn2020/realtime-dialog

Frame structure (client -> server):
  [4B header][4B event_code][4B session_id_len][session_id][4B payload_len][gzip(payload)]

  StartConnection: event=1,  payload=gzip("{}")
  StartSession:    event=100, payload=gzip(json.dumps(config))
  TaskRequest:     event=200, payload=gzip(audio_bytes)
  FinishSession:   event=102, payload=gzip("{}")

Response parsing (server -> client):
  [4B header][optional 4B event][4B session_id_len][session_id][4B payload_len][payload]
  payload is gzip-decompressed, then JSON-parsed if serialization=JSON.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Protocol constants (from demo protocol.py)
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111
MSG_WITH_EVENT = 0b0100
JSON = 0b0001
NO_SERIALIZATION = 0b0000
GZIP = 0b0001
NO_COMPRESSION = 0b0000

# Event codes
EVT_START_CONNECTION = 1
EVT_FINISH_CONNECTION = 2
EVT_START_SESSION = 100
EVT_FINISH_SESSION = 102
EVT_TASK_REQUEST = 200
EVT_CONFIG_UPDATED = 251
EVT_TTS_SENTENCE_START = 350
EVT_TTS_SENTENCE_END = 351
EVT_TTS_RESPONSE = 352
EVT_TTS_ENDED = 359
EVT_REPLY_STARTED = 553
EVT_REPLY_CONTENT = 550
EVT_REPLY_ENDED = 559


def _generate_header(
    message_type: int = CLIENT_FULL_REQUEST,
    flags: int = MSG_WITH_EVENT,
    serial: int = JSON,
    compression: int = GZIP,
) -> bytes:
    """Generate 4-byte protocol header."""
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE,
            (message_type << 4) | flags,
            (serial << 4) | compression,
            0x00,
        ]
    )


def _parse_response(res: bytes) -> dict:
    """Parse a server response binary frame."""
    if isinstance(res, str) or len(res) < 4:
        return {}
    msg_type = res[1] >> 4
    flags = res[1] & 0x0F
    serial = res[2] >> 4
    compression = res[2] & 0x0F
    header_size = res[0] & 0x0F
    payload = res[header_size * 4 :]
    result: dict[str, Any] = {"message_type": msg_type, "event": 0}

    if msg_type in (SERVER_FULL_RESPONSE, SERVER_ACK):
        start = 0
        if flags & MSG_WITH_EVENT:
            result["event"] = int.from_bytes(payload[:4], "big")
            start += 4
        payload = payload[start:]
        sid_len = int.from_bytes(payload[:4], "big", signed=True)
        result["session_id"] = str(payload[4 : 4 + sid_len], "utf-8")
        payload = payload[4 + sid_len :]
        psize = int.from_bytes(payload[:4], "big")
        pmsg = payload[4 : 4 + psize]
        if compression == GZIP:
            pmsg = gzip.decompress(pmsg)
        if serial == JSON:
            pmsg = json.loads(str(pmsg, "utf-8"))
        result["payload"] = pmsg
        result["payload_size"] = psize
    elif msg_type == SERVER_ERROR_RESPONSE:
        result["code"] = int.from_bytes(payload[:4], "big")
        psize = int.from_bytes(payload[4:8], "big")
        pmsg = payload[8 : 8 + psize]
        if compression == GZIP:
            pmsg = gzip.decompress(pmsg)
        result["payload"] = json.loads(str(pmsg, "utf-8")) if serial == JSON else str(pmsg, "utf-8")
    return result


def _build_request(
    event: int,
    session_id: str,
    payload_dict: dict | None = None,
    is_audio: bool = False,
    audio_bytes: bytes | None = None,
) -> bytes:
    """Build a client request binary frame."""
    msg_type = CLIENT_AUDIO_ONLY_REQUEST if is_audio else CLIENT_FULL_REQUEST
    serial = NO_SERIALIZATION if is_audio else JSON
    req = bytearray(_generate_header(message_type=msg_type, serial=serial))
    req.extend(event.to_bytes(4, "big"))
    sid_bytes = session_id.encode("utf-8")
    req.extend(len(sid_bytes).to_bytes(4, "big"))
    req.extend(sid_bytes)
    if is_audio and audio_bytes:
        pbytes = gzip.compress(audio_bytes)
    else:
        raw = json.dumps(payload_dict or {}).encode("utf-8")
        pbytes = gzip.compress(raw)
    req.extend(len(pbytes).to_bytes(4, "big"))
    req.extend(pbytes)
    return bytes(req)


class RealtimeSession:
    """One mock-interview voice session: browser WS <-> Volcengine WS."""

    def __init__(
        self,
        session_id,
        job,
        config,
        provider,
        character_manifest,
        question_bank=None,
        total_questions: int | None = None,
        focus: str | None = None,
        db_path: str = "data/agent.db",
    ):
        self.session_id = session_id
        self.job = job
        self.config = config
        self.provider = provider
        self.character_manifest = character_manifest
        self.question_bank = question_bank
        # focus 过滤后的实际题库题数；None 表示按 question_bank 全量计算
        self.total_questions = total_questions
        self.focus = focus
        self.db_path = db_path
        self.volc_ws: Any = None
        self.browser_ws: Any = None
        self.transcript: list[str] = [f"实时语音记录\n{job.title} @ {job.company}\n{'=' * 50}\n"]
        # ASR 结果可能晚到（甚至晚于面试官下一题），记录 transcript 时按面试官
        # 轮次回填到正确位置，避免评估被“答非所问”的乱序文本污染。
        self._interviewer_indices: list[int] = []
        self.ended = False

    async def connect_volc(self) -> None:
        """Connect to Volcengine, send StartConnection then StartSession."""
        import websockets

        rt = self.config.realtime
        headers = {
            "X-Api-App-ID": self.config.volc_app_id,
            "X-Api-Access-Key": self.config.volc_access_key,
            "X-Api-Resource-Id": rt.resource_id,
            "X-Api-App-Key": rt.resolved_app_key,
        }
        self.volc_ws = await websockets.connect(
            rt.volc_endpoint, additional_headers=headers, ping_interval=None
        )
        logger.info("[%s] WS connected to Volcengine", self.session_id)

        # 1. StartConnection (event=1)
        req = bytearray(_generate_header())
        req.extend(EVT_START_CONNECTION.to_bytes(4, "big"))
        pbytes = gzip.compress(b"{}")
        req.extend(len(pbytes).to_bytes(4, "big"))
        req.extend(pbytes)
        await self.volc_ws.send(bytes(req))
        resp = await self.volc_ws.recv()
        logger.info("[%s] StartConnection response: %s", self.session_id, _parse_response(resp))

        # 2. StartSession (event=100)
        start_config = self._build_start_session()
        req2 = _build_request(EVT_START_SESSION, self.session_id, payload_dict=start_config)
        await self.volc_ws.send(req2)
        resp2 = await self.volc_ws.recv()
        parsed = _parse_response(resp2)
        logger.info("[%s] StartSession response: %s", self.session_id, parsed)
        if parsed.get("message_type") == SERVER_ERROR_RESPONSE:
            raise RuntimeError(f"StartSession failed: {parsed}")

        # 3. Send ChatTextQuery (event=501) to trigger interviewer's first question
        trigger_req = _build_request(
            501,
            self.session_id,
            payload_dict={"content": "你好，请开始面试吧"},
        )
        await self.volc_ws.send(trigger_req)
        logger.info("[%s] ChatTextQuery sent (trigger first question)", self.session_id)

    def _build_start_session(self) -> dict:
        """Build StartSession JSON payload for SC2.0 (per PDF spec)."""
        rt = self.config.realtime
        return {
            "asr": {
                "audio_info": {
                    "format": "pcm_s16le",
                    "sample_rate": 16000,
                    "channel": 1,
                },
                "extra": {},
            },
            "tts": {
                "speaker": rt.voice,
            },
            "dialog": {
                "character_manifest": self.character_manifest,
                "dialog_id": "",
                "extra": {
                    "model": rt.model,
                    "input_mod": "keep_alive",
                    "enable_user_query_exit": True,
                    "enable_loudness_norm": True,
                },
            },
        }

    async def relay_browser_to_volc(self) -> None:
        """Forward browser audio -> Volcengine as TaskRequest (event=200)."""
        try:
            async for msg in self.browser_ws:
                if self.ended:
                    break
                if isinstance(msg, bytes):
                    if self.volc_ws and getattr(self.volc_ws, "state", 1) == 1:
                        req = _build_request(
                            EVT_TASK_REQUEST,
                            self.session_id,
                            is_audio=True,
                            audio_bytes=msg,
                        )
                        await self.volc_ws.send(req)
                elif isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "end":
                        await self._end_session(manual=True)
                        break
                    if data.get("type") == "abandon":
                        await self._abandon()
                        break
        except Exception as e:
            if not self.ended:
                logger.error("[%s] browser->volc: %s", self.session_id, e)

    async def relay_volc_to_browser(self) -> None:
        """Parse Volcengine binary responses, relay to browser."""
        try:
            async for msg in self.volc_ws:
                if self.ended:
                    break
                if isinstance(msg, bytes):
                    parsed = _parse_response(msg)
                    await self._handle_volc_event(parsed, msg)
                elif isinstance(msg, str):
                    logger.debug("[%s] text msg (unexpected): %s", self.session_id, msg[:100])
        except Exception as e:
            if not self.ended:
                logger.error("[%s] volc->browser: %s", self.session_id, e)

    async def _handle_volc_event(self, parsed: dict, raw: bytes) -> None:
        """Handle a parsed Volcengine event."""
        evt = parsed.get("event", 0)
        payload = parsed.get("payload")

        # Error response
        if parsed.get("message_type") == SERVER_ERROR_RESPONSE:
            code = parsed.get("code", 0)
            # Idle timeout: end gracefully instead of showing error alert
            if code in (52000042, 52000011, 52000016):
                logger.info("[%s] Session idle/timeout, ending gracefully", self.session_id)
                await self._end_session(manual=False)
            elif code == 45000003:
                # Abnormal silence audio (2026-08-12): fires during normal thinking
                # pauses. Hint the user to speak instead of popping an error and
                # killing the session.
                logger.info("[%s] Silence detected, hinting user to speak", self.session_id)
                await self._send_browser({"type": "hint", "text": "检测到静音，请说话继续面试"})
            else:
                logger.error(
                    "[%s] Server error: code=%s payload=%s", self.session_id, code, payload
                )
                await self._send_browser(
                    {"type": "error", "text": f"火山错误 code={code}: {payload}"}
                )
            return

        # Audio data (TTS response or raw binary)
        if evt == EVT_TTS_RESPONSE or (
            parsed.get("message_type") == SERVER_ACK and isinstance(payload, bytes | bytearray)
        ):
            if (
                self.browser_ws
                and getattr(self.browser_ws, "state", 1) == 1
                and isinstance(payload, bytes | bytearray)
            ):
                await self.browser_ws.send(
                    payload if isinstance(payload, bytes) else bytes(payload)
                )
            return

        if not isinstance(payload, dict):
            return

        # JSON events
        # ChatResponse (550) - stream text to browser in real-time.
        # Measured 2026-08-10: Volcengine SC2.0 sends INCREMENTAL text (one
        # char/fragment per event, same reply_id per turn), NOT the full
        # accumulated reply. So within one turn we APPEND. reply_id still
        # marks turn boundaries (reset on new rid).
        if evt == EVT_REPLY_CONTENT:
            text = payload.get("content", "")
            if text:
                rid = payload.get("reply_id") or ""
                cur = getattr(self, "_cur_reply_id", None)
                if rid and rid != cur:
                    # New turn: buffer starts from this event's content
                    self._cur_reply_id = rid
                    self._reply_buf = text
                elif rid:
                    # Same turn: incremental streaming (measured), append.
                    self._reply_buf = (getattr(self, "_reply_buf", "") or "") + text
                else:
                    # No reply_id (rare): fall back to append
                    self._reply_buf = (getattr(self, "_reply_buf", "") or "") + text
                await self._send_browser({"type": "tts_chunk", "text": text})

        # ChatTextQueryConfirmed (553) - new reply starts
        elif evt == EVT_REPLY_STARTED:
            self._reply_buf = ""
            self._cur_reply_id = None
            self._reply_ended_exit_marker = False
            await self._send_browser({"type": "tts_new"})

        # ChatEnded (559) - save full reply text to transcript
        elif evt == EVT_REPLY_ENDED:
            full = getattr(self, "_reply_buf", "")
            # 2026-08-16: 记录本轮面试官是否输出了收尾标志，供 TTS_ENDED 兜底判断。
            # 仅靠火山 TTS_ENDED status_code == 20000002 不稳定，实测“没有了”->面试官
            # 说“面试结束。”后 status 非该值，导致会话无法收尾。
            self._reply_ended_exit_marker = bool(full) and (
                "以下是您的表现评估" in full or "面试结束" in full
            )
            if full:
                # 2026-08-12: 截断结束语后的评估 JSON（与文字模式统一）——
                # 否则下载记录含自评 JSON，且独立评估读 transcript 会被自评分数污染。
                for marker in ("以下是您的表现评估", "面试结束"):
                    idx = full.find(marker)
                    if idx >= 0:
                        end = idx + len(marker)
                        while end < len(full) and full[end] in ("。", "：", ":", "！", " "):
                            end += 1
                        full = full[:end]
                        break
                idx = len(self.transcript)
                self.transcript.append(f"面试官: {full}\n")
                self._interviewer_indices.append(idx)

        # TTS sentence start (350) - only controls Ogg audio collection
        elif evt == EVT_TTS_SENTENCE_START:
            await self._send_browser({"type": "tts_ogg_start"})

        elif evt == EVT_TTS_SENTENCE_END:
            await self._send_browser({"type": "tts_ogg_end"})

        elif evt == EVT_TTS_ENDED:
            status = str(payload.get("status_code", ""))
            logger.info("[%s] TTS_ENDED status_code=%s", self.session_id, status)
            if status == "20000002" or getattr(self, "_reply_ended_exit_marker", False):
                if self._reverse_phase_pending():
                    logger.info(
                        "[%s] reverse-question phase waiting for candidate; not ending",
                        self.session_id,
                    )
                    return
                if await self._maybe_force_continue():
                    logger.info(
                        "[%s] Exit intent but questions remain -> force continue", self.session_id
                    )
                    return
                logger.info("[%s] Exit intent -> assessment", self.session_id)
                await self._trigger_assessment()

        # ASR results (event 451 = ASRResponse, text in results[].text)
        elif evt == 451:
            results = payload.get("results", [])
            for r_item in results:
                text = r_item.get("text", "")
                if text and not r_item.get("is_interim", False):
                    self._record_candidate_asr(text)
                    await self._send_browser({"type": "asr", "text": text})
                    # 方案A：关键词兜底结束（不依赖火山退出意图识别）
                    # 候选人说"面试结束/再见"等，直接触发评估结束
                    if self._is_exit_intent(text):
                        logger.info("[%s] Exit intent via keyword: %r", self.session_id, text)
                        if await self._maybe_force_continue():
                            logger.info(
                                "[%s] Exit intent but questions remain -> force continue",
                                self.session_id,
                            )
                        else:
                            await self._trigger_assessment()

        # ASR info/ended (event 450/459) - no text to forward
        elif evt in (450, 459):
            pass

        elif evt == EVT_CONFIG_UPDATED:
            logger.debug("[%s] ConfigUpdated ack", self.session_id)

    def _turn_has_candidate(self, idx: int) -> bool:
        for line in self.transcript[idx + 1 :]:
            if line.startswith("面试官:"):
                break
            if line.startswith("你:"):
                return True
        return False

    def _record_candidate_asr(self, text: str) -> None:
        """把 ASR 文本回填到正确面试官轮次下（晚到结果插到下一题之前）。"""
        line = f"你: {text}\n"
        target = None
        for idx in self._interviewer_indices:
            if not self._turn_has_candidate(idx):
                target = idx
                break
        if target is None and self._interviewer_indices:
            target = self._interviewer_indices[-1]
        if target is None:
            self.transcript.append(line)
            return
        insert_at = len(self.transcript)
        for i in range(target + 1, len(self.transcript)):
            if self.transcript[i].startswith("面试官:"):
                insert_at = i
                break
            if self.transcript[i].startswith("你:"):
                insert_at = i + 1
        self.transcript.insert(insert_at, line)

    async def _send_browser(self, data: dict) -> None:
        if self.browser_ws and getattr(self.browser_ws, "state", 1) == 1:
            try:
                await self.browser_ws.send(json.dumps(data, ensure_ascii=False))
            except Exception:
                logger.warning(
                    "[%s] send_browser failed for type=%s: %s",
                    self.session_id,
                    data.get("type"),
                    repr(data)[:200],
                )
                logger.debug("send_browser failure details", exc_info=True)

    _EXIT_KEYWORDS = (
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

    _NATURAL_END_PHRASES = {
        "没有了",
        "没有问题了",
        "没有其他问题",
        "没别的问题了",
        "没有别的问题了",
    }

    def _is_exit_intent(self, text: str) -> bool:
        """Detect candidate's exit intent from ASR text (plan A fallback).

        明确的“面试结束/再见”类短语允许包含匹配；口语化结束语（没有了等）只允许
        整句匹配，避免“这个项目我参与不多，暂时没有了”这种正常回答被误判退出。
        """
        t = (text or "").strip()
        if not t:
            return False
        if t.rstrip("。！？!? ") in self._NATURAL_END_PHRASES:
            return True
        return any(kw in t for kw in self._EXIT_KEYWORDS)

    def _count_questions_asked(self) -> int:
        """Count how many interview questions the interviewer has asked.

        开场白不算题目；进入反问环节（"我的问题问完了/你有什么想问我的吗"）后
        的面试官行也不再计数——否则反问回答会把已问题数抬高，导致题库已问完时
        _maybe_force_continue 仍误判为未问完并强制续问（2026-08-16 实测）。
        """
        count = 0
        for line in self.transcript:
            if not line.startswith("面试官:"):
                continue
            if any(m in line for m in ("我的问题问完了", "你有什么想问我的吗")):
                break
            count += 1
        # First 面试官 line is the opening self-intro request, not a question
        return max(0, count - 1)

    def _reverse_phase_pending(self) -> bool:
        """True if interviewer entered reverse-question phase but candidate hasn't responded yet.

        Prevents TTS_ENDED / exit-marker from ending the interview right after the
        interviewer asks “你有什么想问我的吗？” — the candidate must get a chance
        to ask reverse questions first (2026-08-17).
        """
        idx = -1
        for i, line in enumerate(self.transcript):
            if line.startswith("面试官:") and any(
                m in line for m in ("我的问题问完了", "你有什么想问我的吗")
            ):
                idx = i
                break
        if idx < 0:
            return False
        for line in self.transcript[idx + 1 :]:
            if line.startswith("面试官:"):
                return False
            if line.startswith("你:"):
                return False
        return True

    def _total_questions(self) -> int:
        """Total questions in the question bank (0 if no bank -> free-form)."""
        total_questions = getattr(self, "total_questions", None)
        if total_questions is not None:
            return total_questions
        bank = self.question_bank or {}
        total = 0
        for rnd in bank.get("rounds", []):
            total += len(rnd.get("questions", []))
        total += len(bank.get("project_deep_dive", []))
        return total

    async def _maybe_force_continue(self) -> bool:
        """If the interviewer tried to end early (questions remain), force
        another turn via ChatTextQuery. Returns True if we forced continue."""
        total = self._total_questions()
        if not total:  # free-form (no bank): no count guard, allow end
            return False
        asked = self._count_questions_asked()
        if asked >= total:
            return False
        logger.info(
            "[%s] questions asked %d/%d, forcing continue",
            self.session_id,
            asked,
            total,
        )
        if self.volc_ws and getattr(self.volc_ws, "state", 1) == 1:
            req = _build_request(
                501,
                self.session_id,
                payload_dict={
                    "content": (
                        f"你刚才还没有问完所有题目（题库共 {total} 题，你已问了 {asked} 题）。"
                        "请继续按题库顺序问下一个问题，不要结束面试。"
                    )
                },
            )
            try:
                await self.volc_ws.send(req)
                return True
            except Exception:
                logger.exception("[%s] force-continue ChatTextQuery failed", self.session_id)
        return False

    async def _trigger_assessment(self) -> None:
        if self.ended:
            return
        self.ended = True
        transcript_text = "\n".join(self.transcript)
        assessment = None
        await self._send_browser(
            {"type": "generating", "stage": "assessing"}
        )  # 2026-08-12: 进度弹窗-LLM 评估阶段
        try:
            from agent_core.pipeline.interview_prep import (
                _parse_assessment,
                generate_assessment_from_transcript,
            )

            assessment = await generate_assessment_from_transcript(
                transcript_text,
                self.job,
                self.config,
                self.provider,
                self.question_bank,
                focus=self.focus,
            )
            if not assessment:
                # LLM returned but parse failed (non-standard JSON) -- fall back
                # to parsing the interviewer's final reply (same as text mode).
                logger.warning(
                    "[%s] assessment LLM empty, falling back to inline parse", self.session_id
                )
                last_reply = next(
                    (line for line in reversed(self.transcript) if line.startswith("面试官:")), ""
                )
                assessment = _parse_assessment(last_reply)
        except Exception as e:
            logger.error("[%s] assessment failed: %s", self.session_id, e)
            # fallback: try inline parse of final interviewer reply
            try:
                from agent_core.pipeline.interview_prep import _parse_assessment

                last_reply = next(
                    (line for line in reversed(self.transcript) if line.startswith("面试官:")), ""
                )
                assessment = _parse_assessment(last_reply)
            except Exception:
                assessment = None
        await self._send_browser(
            {"type": "generating", "stage": "record"}
        )  # notify UI: writing files
        self._save_artifacts(
            transcript_text, assessment
        )  # 2026-08-12: 先写文件再发 ended（原顺序前端收到时文件未落盘）
        md_name, assessment_name = self._artifact_names()
        logger.info("[%s] sending ended to browser", self.session_id)
        await self._send_browser(
            {
                "type": "ended",
                "assessment": assessment,
                "md_name": md_name,
                "assessment_name": assessment_name,
            }
        )
        await self._send_finish_session()
        await self._close_connections()

    def _artifact_names(self) -> tuple[str, str]:
        """md + assessment file basenames for this session (progress-modal links)."""

        def _fs(x: str) -> str:
            return re.sub(r'[\/*?:"<>|]', "", x)[:20]

        base = f"{_fs(self.job.company)}_{_fs(self.job.title)}_realtime_mock"
        return base + ".md", base + "_assessment.txt"

    def _save_artifacts(
        self, transcript_text: str, assessment: dict | None, interrupted: bool = False
    ) -> None:
        def _fs(x: str) -> str:
            return re.sub(r'[\\/*?:"<>|]', "", x)[:20]

        base = f"output/{_fs(self.job.company)}_{_fs(self.job.title)}_realtime_mock"
        Path("output").mkdir(parents=True, exist_ok=True)
        with open(base + ".md", "w", encoding="utf-8") as f:
            f.write(transcript_text)
        assessment_path = base + "_assessment.txt"
        if assessment:
            # 2026-08-12: wrap in try/except — a format/parse failure mid-write used to
            # leave a 0-byte file behind (the UI then shows an empty report).
            try:
                # 2026-08-12 fix: format_assessment_txt lives in interview_prep —
                # without this import every assessment write hit NameError and left
                # a 0-byte file (dashboard.log: "name 'format_assessment_txt' is not defined").
                from agent_core.pipeline.interview_prep import format_assessment_txt

                with open(assessment_path, "w", encoding="utf-8") as f:
                    f.write(
                        format_assessment_txt(
                            assessment, self.job, interrupted=interrupted, mode="realtime"
                        )
                    )
                # 写入后校验非空——0 字节残留会让 UI 显示空报告
                if os.path.getsize(assessment_path) == 0:
                    os.remove(assessment_path)
            except Exception as e:
                logger.error("[%s] assessment write failed: %s", self.session_id, e)
                try:
                    if os.path.exists(assessment_path):
                        os.remove(assessment_path)
                except Exception as e2:
                    logger.error("[%s] stale assessment remove failed: %s", self.session_id, e2)
        else:
            # assessment failed to generate (LLM parse) -- remove any stale
            # 0-byte file so the UI never shows an empty report.
            logger.warning("[%s] assessment empty, skipping _assessment.txt", self.session_id)
            try:
                if os.path.exists(assessment_path):
                    os.remove(assessment_path)
            except OSError:
                pass
        try:
            from agent_core.pipeline.file_catalog import TYPE_MOCK_INTERVIEW, catalog_file
            from agent_core.storage.db import get_db

            db = get_db(self.db_path)
            try:
                paths = [base + ".md"]
                if assessment:
                    paths.append(assessment_path)
                for path in paths:
                    catalog_file(
                        db,
                        getattr(self.job, "id", ""),
                        TYPE_MOCK_INTERVIEW,
                        path,
                        company=self.job.company,
                        job_title=self.job.title,
                    )
            finally:
                db.close()
        except Exception:
            logger.warning("realtime catalog skipped: %s", exc_info=True)

    async def _send_finish_session(self) -> None:
        """Send FinishSession (event=102) to Volcengine."""
        if self.volc_ws and getattr(self.volc_ws, "state", 1) == 1:
            try:
                req = _build_request(EVT_FINISH_SESSION, self.session_id)
                await self.volc_ws.send(req)
            except Exception:
                pass

    async def _abandon(self) -> None:
        """Drop the session without saving files (前端清空按钮)."""
        if self.ended:
            return
        self.ended = True
        await self._close_connections()

    async def _end_session(self, manual: bool = False) -> None:
        if self.ended:
            return
        self.ended = True
        transcript_text = "\n".join(self.transcript)
        assessment = None
        if manual:
            # 2026-08-12: 用户手动结束也生成评估（标注中途结束，题库可能未全部问完）；
            # 评估失败时降级为仅保存记录。
            try:
                from agent_core.pipeline.interview_prep import (
                    generate_assessment_from_transcript,
                )

                await self._send_browser(
                    {"type": "generating", "stage": "assessing"}
                )  # 2026-08-12: 进度弹窗-评估阶段
                assessment = await generate_assessment_from_transcript(
                    transcript_text,
                    self.job,
                    self.config,
                    self.provider,
                    self.question_bank,
                    focus=self.focus,
                )
            except Exception as e:
                logger.error("[%s] manual-end assessment failed: %s", self.session_id, e)
        await self._send_browser({"type": "generating", "stage": "record"})
        self._save_artifacts(transcript_text, assessment, interrupted=manual)
        md_name, assessment_name = self._artifact_names()
        await self._send_browser(
            {
                "type": "ended",
                "assessment": assessment,
                "md_name": md_name,
                "assessment_name": assessment_name,
            }
        )
        await self._send_finish_session()
        await self._close_connections()

    async def _close_connections(self) -> None:
        if self.volc_ws and getattr(self.volc_ws, "state", 1) == 1:
            try:
                await self.volc_ws.close()
            except Exception:
                pass
        if self.browser_ws and getattr(self.browser_ws, "state", 1) == 1:
            try:
                await self.browser_ws.close()
            except Exception:
                pass


async def handle_browser_connection(browser_ws, config, db_path="data/agent.db") -> None:
    """Handle one browser WS connection."""
    import asyncio

    try:
        start_raw = await asyncio.wait_for(browser_ws.recv(), timeout=10.0)
        data = json.loads(start_raw)
        if data.get("type") != "start":
            await browser_ws.send(json.dumps({"type": "error", "text": "expected start"}))
            return
        job_id = data.get("job_id", "")
        if not job_id:
            await browser_ws.send(json.dumps({"type": "error", "text": "missing job_id"}))
            return
        from agent_core.platforms.base import Job
        from agent_core.storage.db import get_db

        conn = get_db(db_path)
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        if not row:
            await browser_ws.send(json.dumps({"type": "error", "text": "job not found"}))
            return
        job = Job.from_storage(row)
        from agent_core.pipeline.interview_prep import (
            _prep_bank_question_texts,
            build_character_manifest,
            load_interview_prep_json,
        )

        question_bank = None
        focus = data.get("focus") or None
        if data.get("from_prep"):
            conn = get_db(db_path)
            question_bank = load_interview_prep_json(job_id, conn)
            conn.close()
        bank_questions = _prep_bank_question_texts(question_bank, focus) if question_bank else []
        if focus and question_bank and not bank_questions:
            await browser_ws.send(
                json.dumps(
                    {
                        "type": "error",
                        "text": f"focus={focus} 未命中题库题目，请修改或清空后重试",
                    },
                    ensure_ascii=False,
                )
            )
            return
        filtered_total = len(bank_questions)
        manifest = build_character_manifest(
            job,
            config,
            question_bank=question_bank,
            difficulty=data.get("difficulty") or None,
            focus=focus,
        )
        from agent_core.llm.providers import create_provider

        provider = create_provider(config)
        session = RealtimeSession(
            session_id=f"rt_{job_id}_{int(time.time() * 1000)}",
            job=job,
            config=config,
            provider=provider,
            character_manifest=manifest,
            question_bank=question_bank,
            total_questions=filtered_total,
            focus=focus,
            db_path=db_path,
        )
        session.browser_ws = browser_ws
        await session.connect_volc()
        await browser_ws.send(
            json.dumps(
                {
                    "type": "started",
                    "session_id": session.session_id,
                    "job_title": job.title,
                    "job_company": job.company,
                },
                ensure_ascii=False,
            )
        )
        await asyncio.gather(
            session.relay_browser_to_volc(),
            session.relay_volc_to_browser(),
        )
    except TimeoutError:
        try:
            await browser_ws.send(json.dumps({"type": "error", "text": "start timeout"}))
        except Exception:
            pass
    except Exception as e:
        logger.error("browser connection error: %s", e, exc_info=True)
        try:
            await browser_ws.send(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass


async def _run_proxy_server(config, db_path: str) -> None:
    import asyncio

    import websockets

    port = config.realtime.ws_port
    logger.info("Realtime proxy on ws://127.0.0.1:%d", port)
    async with websockets.serve(
        lambda ws: handle_browser_connection(ws, config, db_path),
        "127.0.0.1",
        port,
    ):
        await asyncio.Future()


def start_proxy_in_thread(config, db_path: str = "data/agent.db") -> threading.Thread | None:
    import asyncio
    import threading

    if not config.realtime.enabled:
        return None
    if not config.volc_app_id or not config.volc_access_key:
        logger.warning("Realtime proxy: VOLC creds not set")
        return None

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_proxy_server(config, db_path))
        except Exception as e:
            logger.error("Realtime proxy crashed: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="realtime-proxy")
    t.start()
    logger.info("Realtime proxy thread started (port %d)", config.realtime.ws_port)
    return t
