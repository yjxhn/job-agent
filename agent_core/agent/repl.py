"""REPL (Read-Eval-Print Loop) for the conversational job agent.

Provides an interactive chat interface backed by the LLM with function-calling.
The LLM autonomously decides which tools to call based on user intent.
"""

from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime
from typing import Any

from agent_core.agent.tools import TOOLS, ToolDispatcher
from agent_core.llm.providers import _clean_surrogates, call_llm_with_tools_retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是求职 AI 助手，帮助用户找工作、改简历、跟踪投递进度、评估 Offer。\n"
    "\n"
    "## 求职流程\n"
    "1. 🔍 搜索 — 按关键词+地点在各平台抓取岗位\n"
    "2. 👤 人工筛选 — 用户在 Dashboard 上看结果，标记 🌟想投递 / ❌不合适\n"
    '3. 🧠 精排 — LLM 对标记"想投递"的做深度匹配\n'
    "4. 📝 简历定制 — 针对目标岗位生成定制简历\n"
    "5. 📮 投递追踪 — 记录投递状态、跟踪进度\n"
    "\n"
    "可用工具：\n"
    "- search_jobs: 搜索职位\n"
    "- tailor_resume: 定制简历  - generate_cover_letter: 生成HR打招呼消息\n"
    "- interview_prep: 面试准备  - evaluate_offer: 评估 Offer\n"
    "- salary_advice: 薪资谈判  - check_cookies: 检查登录状态\n"
    "- list_tracked_applications: 查看投递  - add_application: 记录投递\n"
    "- update_application_status: 更新投递状态\n"
    "\n"
    "规则：\n"
    "1. 用中文回复，简洁友好\n"
    "2. 用户意图明确时主动调用工具\n"
    "3. 不确定时向用户确认\n"
    "4. 搜索前先规划关键词组合，想好几组再开始\n"
    "5. **每个阶段结束后，主动提示用户当前处于第几步、下一步是什么**\n"
    '   例：搜索完成 → 提示用户"搜索完成！接下来你可以筛选感兴趣的岗位"\n'
    "6. 不要替用户做决定，展示选项让用户选\n"
    "7. **用户进入对话后，先展示一个示例信息模板，引导用户按模板提供需求**。\n"
    "   模板示例：\n"
    "   1. 岗位/方向：设备工程师\n"
    "   2. 工作地点：全国\n"
    "   3. 技术栈/技能：不限\n"
    "   4. 目标公司：不限\n"
    "   5. 工作年限：3年\n"
    "   6. 薪资期望：月薪9K\n"
    "   7. 行业偏好：不限\n"
    "   8. 岗位数量要求：50个\n"
    "   9. 学历要求：不限\n"
    "   10. 公司规模/性质：不限\n"
    "   11. 岗位类型：全职\n"
    "   12. 发布时间：近7天\n"
    "   然后根据用户提供的这些信息调用 search_jobs 工具，提取关键词、地点、薪资下限、结果数量等参数。\n"
    "8. **每次搜索完成后，提示用户去 Dashboard 看完整列表：**\n"
    "   - Dashboard 地址：http://localhost:8765\n"
    "   - **岗位列表 Tab** → 查看所有搜索结果，可搜索、筛选、排序\n"
    "   - **深度匹配 Tab** → 查看 LLM 精排后的匹配分\n"
    "   - **已生成文件 Tab** → 查看定制的简历、求职信等\n"
    "   - 提示用户可以复制岗位 ID 回来继续操作（定制简历、记录投递等）\n"
    "9. **展示搜索结果时，只展示精选岗位（如薪资匹配度高的、行业头部的），控制在合理数量内。**\n"
    '   同时告诉用户："完整 {total} 条结果已同步到 Dashboard（http://localhost:8765），去岗位列表 Tab 查看全部并筛选。"\n'
    "\n"
    "## 工具结果判读规则（重要）\n"
    '- 后端服务始终在线，工具调用是本地函数，不存在"网络异常/服务未启动"。\n'
    '- 工具返回的是 JSON 字符串。只有当 JSON 里含 `"error"` 字段时才算失败；否则一律视为成功。\n'
    '- 列表返回 `total:0` 或 `applications:[]` 表示"暂无数据"，是正常空结果，不是故障。直接如实告诉用户"目前没有记录"即可。\n'
    '- 字段值短、description 简洁、记录数少，都是正常数据，不要据此推断"返回异常"或要求用户重启服务。\n'
    "- 拿到岗位/投递信息后，直接用其中的 job_id 调下游工具（如 generate_cover_letter、tailor_resume），不要停下来向用户确认服务状态。\n"
)

EXIT_KEYWORDS = {"exit", "quit", "q", "退出", "quit()"}


def _ts() -> str:
    """Timestamp for console output, matching project style."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Cap on messages kept in the REPL conversation history. Long chat sessions
# otherwise grow without bound and blow up token cost per turn.
_MAX_HISTORY_MESSAGES = 60


def _trim_history(messages: list[dict[str, Any]], max_msgs: int = _MAX_HISTORY_MESSAGES) -> None:
    """Trim oldest plain exchanges once the history exceeds max_msgs.

    Only complete user -> assistant(text) exchanges are dropped, walking from
    the front (after the system prompt). Trimming stops at the first tool
    round (an assistant message with tool_calls, or a role=tool message) so a
    tool-call pair can never be split — the OpenAI-compatible API rejects
    histories with dangling tool calls.
    """
    if len(messages) <= max_msgs:
        return
    i = 1  # index 0 is the system prompt, always kept
    excess = len(messages) - max_msgs
    keep_from = 0
    while i < len(messages) - 1 and excess > 0:
        m = messages[i]
        nxt = messages[i + 1]
        if m.get("role") == "user" and nxt.get("role") == "assistant" and not nxt.get("tool_calls"):
            i += 2
            excess -= 1
            keep_from = i
        else:
            break
    if keep_from > 0:
        del messages[1:keep_from]


async def run_chat_repl(config: Any, db: Any, provider: Any) -> None:
    """Main REPL loop for the chat agent.

    Args:
        config: Project Config object
        db: SQLite database connection
        provider: LLMProvider instance (DeepSeekProvider)
    """
    dispatcher = ToolDispatcher(config, db, provider)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    print(f"\n{'=' * 56}")
    print("  🤖 求职 AI 助手 (chat 模式)")
    print(f"  Model: {provider.model}")
    print("  输入 'exit' / 'quit' / '退出' 结束对话")
    print(f"{'=' * 56}")
    print()
    print("  👋 嗨，我是求职 AI 助手。已对接 Boss 直聘、猎聘、智联、腾讯、网易、")
    print("     比亚迪、北方华创、长飞 8 个渠道，覆盖求职全流程。")
    print()
    print("  🔍 多平台搜岗位        🧠 LLM 精排匹配打分")
    print("  📝 定制简历 (.docx)    ✉️  生成HR打招呼消息")
    print("  🎤 面试准备+模拟面试   💰 Offer 综合评估")
    print("  📮 投递进度追踪         🗣️  薪资谈判建议")
    print("  🔐 登录态检查          📊 Dashboard 看板 (localhost:8765)")
    print()
    print("  💬 直接告诉我想法就行，比如「搜深圳的AMR岗位」、")
    print("     「帮我把 xxx 岗位定制简历」，不用填模板。")
    print()
    print("  📋 也可以按下面格式告诉我详细需求（不填的写'不限'）：")
    print("     岗位/方向：设备工程师    工作地点：全国        薪资期望：月薪9K")
    print("     目标公司：不限            技术栈：不限          工作年限：3年")
    print("     岗位类型：全职            学历要求：不限        发布时间：近7天")
    print("     行业偏好：不限            公司规模：不限        数量要求：50个")
    print()

    # Suppress Windows asyncio subprocess ResourceWarning on exit
    warnings.filterwarnings("ignore", message="unclosed transport", category=ResourceWarning)

    while True:
        try:
            user_input = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n[{_ts()}] 再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in EXIT_KEYWORDS:
            print(f"[{_ts()}] 再见！")
            break

        messages.append({"role": "user", "content": user_input})
        # Snapshot the history length after appending the user message. If the
        # turn fails mid-way, _process_turn may have already appended assistant
        # (tool_calls) and tool messages; rolling back to this point removes
        # the user message AND any partial tool-call history, so the next turn
        # never sends a malformed tool_calls-without-tool-reply sequence to
        # the API (which can trigger a 400).
        turn_start = len(messages)

        try:
            await _process_turn(messages, dispatcher, provider)
            # Keep long sessions bounded: drop oldest plain exchanges
            # (tool-call rounds are never split).
            _trim_history(messages)
        except Exception as e:
            logger.error(f"REPL turn failed: {e}", exc_info=True)
            print(f"\n[{_ts()}] ⚠️ 出错了: {e}")
            del messages[turn_start:]
            continue


async def _process_turn(
    messages: list[dict[str, Any]],
    dispatcher: ToolDispatcher,
    provider: Any,
    max_tool_rounds: int = 5,
) -> None:
    """Process one conversation turn: call LLM, execute tools, loop until text response.

    Args:
        messages: Conversation history (mutated in-place)
        dispatcher: ToolDispatcher instance
        provider: LLMProvider instance
        max_tool_rounds: Maximum tool-call iterations per user message
    """
    # Reset search counter each turn
    dispatcher._search_rounds = 0

    for _round in range(max_tool_rounds):
        response = await call_llm_with_tools_retry(
            provider,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=4096,
        )

        # If no tool calls, print the text response and we're done
        if not response.tool_calls:
            if response.content:
                print(f"\n助手: {response.content}\n")
            messages.append({"role": "assistant", "content": response.content or ""})
            # Open dashboard if any search was done this turn
            if dispatcher._search_rounds > 0:
                try:
                    from agent_core.pipeline.orchestrator import _open_dashboard

                    _open_dashboard()
                except Exception:
                    pass
            return

        # LLM wants to call tools
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.reasoning_content:
            assistant_msg["reasoning_content"] = response.reasoning_content
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in response.tool_calls:
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError:
                args = {}

            print(f"\n[{_ts()}] 🔧 调用工具: {tc.name}({_truncate(tc.arguments, 100)})")

            result_text = await dispatcher.dispatch(tc.name, args)
            result_text = _clean_surrogates(result_text)

            preview = _truncate(result_text, 200)
            print(f"[{_ts()}] 结果: {preview}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                }
            )

    # If we exhaust max_tool_rounds, ask LLM for final response without tools
    print(f"\n[{_ts()}] ⚠️ 达到最大工具调用轮次，请求最终回复...")
    final_resp = await call_llm_with_tools_retry(
        provider,
        messages=messages,
        tools=TOOLS,
        tool_choice="none",
        temperature=0.7,
        max_tokens=4096,
    )
    if final_resp.content:
        print(f"\n助手: {final_resp.content}\n")
    messages.append({"role": "assistant", "content": final_resp.content or ""})


def _truncate(text: str, max_len: int) -> str:
    """Truncate text for console display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
