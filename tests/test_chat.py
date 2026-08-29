"""Tests for chat agent: tools schema, dispatcher, REPL loop.

All tests use mocks — no real LLM calls.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_core.agent.tools import TOOLS, ToolDispatcher
from agent_core.llm.base import ChatResponse, ToolCall


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    """Never write to the real data/agent.db from tests.

    ToolDispatcher._search_jobs persists jobs via
    orchestrator._save_jobs_to_db(), which uses get_db() with the default
    path "data/agent.db" — the real production database. The chat search
    tests used to pollute it with fake jobs (id=1 / byd1, "http://x"
    placeholder URLs, equipment_amr direction) that then showed up in the
    Dashboard. Same guard as tests/test_advanced.py's _no_real_db fixture.
    """
    import agent_core.pipeline.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "_save_jobs_to_db", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_save_match_to_db", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_save_pipeline_run", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_all_tools_have_required_fields(self):
        """Each tool must have type=function and function.name/description/parameters."""
        for tool in TOOLS:
            assert tool["type"] == "function"
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_tool_names_are_unique(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_tool_schema_is_json_serializable(self):
        """All tool schemas must be valid JSON."""
        serialized = json.dumps(TOOLS, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert len(parsed) == len(TOOLS)

    def test_expected_tools_present(self):
        """Verify all 11 tools are defined."""
        names = {t["function"]["name"] for t in TOOLS}
        expected = {
            "search_jobs",
            "list_tracked_applications",
            "add_application",
            "update_application_status",
            "tailor_resume",
            "generate_cover_letter",
            "interview_prep",
            "evaluate_offer",
            "salary_advice",
            "check_cookies",
            "get_job_detail",
        }
        assert names == expected

    def test_search_jobs_required_params(self):
        tool = _find_tool("search_jobs")
        required = tool["function"]["parameters"].get("required", [])
        assert "keywords" in required
        assert "location" not in required  # optional
        assert "platform" not in required  # optional
        assert "company" not in required  # optional

    def test_search_jobs_has_platform_param(self):
        tool = _find_tool("search_jobs")
        props = tool["function"]["parameters"]["properties"]
        assert "platform" in props
        assert props["platform"]["type"] == "string"
        assert "byd" in props["platform"]["description"]

    def test_search_jobs_has_company_param(self):
        tool = _find_tool("search_jobs")
        props = tool["function"]["parameters"]["properties"]
        assert "company" in props
        assert props["company"]["type"] == "string"

    def test_update_status_has_enum(self):
        tool = _find_tool("update_application_status")
        status_prop = tool["function"]["parameters"]["properties"]["status"]
        assert "enum" in status_prop
        assert "已投递" in status_prop["enum"]


def _find_tool(name: str) -> dict:
    for t in TOOLS:
        if t["function"]["name"] == name:
            return t
    raise KeyError(f"Tool not found: {name}")


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------


class TestToolDispatcher:
    @pytest.fixture
    def dispatcher(self):
        """Create a ToolDispatcher with mocked config, db, provider."""
        config = MagicMock()
        config.search_location = "全国"
        config.directions = {}
        config.platforms = {}
        config.llm = MagicMock()
        config.llm.max_tokens = 4096

        db = MagicMock()
        provider = MagicMock()
        return ToolDispatcher(config, db, provider)

    def test_dispatch_unknown_tool(self, dispatcher):
        result = asyncio.run(dispatcher.dispatch("nonexistent_tool", {}))
        data = json.loads(result)
        assert "error" in data

    def test_dispatch_get_job_detail_not_found(self, dispatcher):
        dispatcher.db.execute.return_value.fetchone.return_value = None
        result = asyncio.run(dispatcher.dispatch("get_job_detail", {"job_id": "no-such-id"}))
        data = json.loads(result)
        assert "error" in data

    def test_dispatch_get_job_detail_found(self, dispatcher):
        mock_row = {
            "id": "abc123",
            "title": "Python 工程师",
            "company": "测试公司",
            "location": "苏州",
            "salary_min": 15000,
            "salary_max": 25000,
            "description": "岗位描述...",
            "direction": "python_dev",
            "first_seen": "2026-01-01",
            "last_seen": "2026-06-01",
        }
        dispatcher.db.execute.return_value.fetchone.return_value = mock_row
        result = asyncio.run(dispatcher.dispatch("get_job_detail", {"job_id": "abc123"}))
        data = json.loads(result)
        assert data["id"] == "abc123"
        assert data["title"] == "Python 工程师"
        assert data["company"] == "测试公司"

    def test_dispatch_add_application_empty_id(self, dispatcher):
        result = asyncio.run(dispatcher.dispatch("add_application", {"job_id": ""}))
        data = json.loads(result)
        assert "error" in data

    def test_dispatch_add_application_success(self, dispatcher):
        with patch("agent_core.tracking.tracker.add_application", return_value=42) as mock_add:
            result = asyncio.run(dispatcher.dispatch("add_application", {"job_id": "abc123"}))
            data = json.loads(result)
            assert data["ok"] is True
            assert data["application_id"] == 42
            mock_add.assert_called_once()

    def test_dispatch_list_applications_empty(self, dispatcher):
        with patch("agent_core.tracking.tracker.list_applications", return_value=[]) as mock_list:
            result = asyncio.run(dispatcher.dispatch("list_tracked_applications", {}))
            assert "暂无投递记录" in result
            mock_list.assert_called_once()

    def test_dispatch_list_applications_with_filter(self, dispatcher):
        mock_apps = [
            {
                "id": 1,
                "status": "约面",
                "job_title": "Python 工程师",
                "job_company": "测试公司",
                "applied_at": "2026-06-01",
            }
        ]
        with patch(
            "agent_core.tracking.tracker.list_applications", return_value=mock_apps
        ) as mock_list:
            result = asyncio.run(
                dispatcher.dispatch("list_tracked_applications", {"status_filter": "约面"})
            )
            data = json.loads(result)
            assert data["total"] == 1
            assert data["applications"][0]["status"] == "约面"
            mock_list.assert_called_once()

    def test_dispatch_update_status_value_error(self, dispatcher):
        with patch(
            "agent_core.tracking.tracker.update_status",
            side_effect=ValueError("Invalid: Offer -> 已投递. Allowed: ['入职', '已终止']"),
        ):
            result = asyncio.run(
                dispatcher.dispatch("update_application_status", {"app_id": 1, "status": "已投递"})
            )
            data = json.loads(result)
            assert "error" in data
            assert "Invalid" in data["error"]

    def test_dispatch_check_cookies(self, dispatcher):
        fake_result = MagicMock()
        fake_result.display_name = "boss 直聘"
        fake_result.status_label = "有效"
        fake_result.details = ["共 45 个 cookie"]

        with patch(
            "agent_core.cookie_health.check_cookies",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = [fake_result]
            result = asyncio.run(dispatcher.dispatch("check_cookies", {}))
            data = json.loads(result)
            assert "platforms" in data
            assert len(data["platforms"]) == 1
            assert data["platforms"][0]["platform"] == "boss 直聘"

    def test_dispatch_evaluate_offer(self, dispatcher):
        eval_result = {
            "overall_score": 8,
            "competitive_score": 7,
            "growth_score": 9,
            "risk_score": 3,
            "summary": "这个 Offer 竞争力不错",
            "pros": ["薪资高", "成长空间大"],
            "cons": ["通勤远"],
            "negotiation_levers": ["可以谈签字费"],
        }
        with patch(
            "agent_core.pipeline.offer_eval.evaluate",
            new_callable=AsyncMock,
        ) as mock_eval:
            mock_eval.return_value = eval_result
            result = asyncio.run(
                dispatcher.dispatch(
                    "evaluate_offer",
                    {"company": "测试公司", "title": "Python", "salary": "25K"},
                )
            )
            data = json.loads(result)
            assert data["overall_score"] == 8
            mock_eval.assert_called_once()

    def test_dispatch_salary_advice(self, dispatcher):
        advice_result = {
            "anchor": "30K*15",
            "leverage": ["技能稀缺"],
            "concessions": ["可以接受28K"],
            "scripts": ["基于我的经验..."],
            "confidence": "high",
        }
        with patch(
            "agent_core.pipeline.salary_advice.get_advice",
            new_callable=AsyncMock,
        ) as mock_advice:
            mock_advice.return_value = advice_result
            result = asyncio.run(
                dispatcher.dispatch(
                    "salary_advice",
                    {"company": "测试公司", "salary": "25K", "target": "30K"},
                )
            )
            data = json.loads(result)
            assert data["anchor"] == "30K*15"
            mock_advice.assert_called_once()

    def test_dispatch_exception_returns_error(self, dispatcher):
        """Exception in tool execution should not crash — return error JSON."""
        with patch(
            "agent_core.tracking.tracker.list_applications",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = asyncio.run(dispatcher.dispatch("list_tracked_applications", {}))
            data = json.loads(result)
            assert "error" in data
            assert "DB connection lost" in data["error"]

    def test_dispatch_search_jobs_with_platform(self, dispatcher):
        """search_jobs with platform='byd' calls search_all with platform_names=['byd']."""

        from agent_core.platforms.base import Job

        now = datetime.now(UTC)
        fake_jobs = [
            Job(
                id="byd1",
                title="电池工程师",
                company="比亚迪",
                company_normalized="比亚迪",
                description="电池研发",
                direction="equipment_amr",
                platforms=["byd"],
                urls={"byd": "http://x"},
                salary_min=15000,
                salary_max=25000,
                first_seen=now,
                last_seen=now,
            )
        ]

        async def fake_search_all(
            config, platform_names=None, directions=None, keywords=None, headless=False
        ):
            return list(fake_jobs)

        with patch("agent_core.pipeline.search.search_all", new=fake_search_all):
            result = asyncio.run(
                dispatcher.dispatch(
                    "search_jobs",
                    {"keywords": ["电池"], "platform": "byd"},
                )
            )
            data = json.loads(result)
            assert data["total"] == 1
            assert data["jobs"][0]["company"] == "比亚迪"

    def test_dispatch_search_jobs_with_company_filter(self, dispatcher):
        """search_jobs with company='大疆' filters results to matching companies."""

        from agent_core.platforms.base import Job

        now = datetime.now(UTC)
        fake_jobs = [
            Job(
                id="1",
                title="工程师",
                company="大疆创新",
                company_normalized="大疆",
                description="无人机",
                direction="equipment_amr",
                platforms=["boss_zhipin"],
                urls={"boss_zhipin": "http://x"},
                salary_min=15000,
                salary_max=25000,
                first_seen=now,
                last_seen=now,
            ),
            Job(
                id="2",
                title="工程师",
                company="华为技术",
                company_normalized="华为",
                description="通信",
                direction="equipment_amr",
                platforms=["boss_zhipin"],
                urls={"boss_zhipin": "http://y"},
                salary_min=20000,
                salary_max=30000,
                first_seen=now,
                last_seen=now,
            ),
        ]

        async def fake_search_all(
            config, platform_names=None, directions=None, keywords=None, headless=False
        ):
            return list(fake_jobs)

        with patch("agent_core.pipeline.search.search_all", new=fake_search_all):
            result = asyncio.run(
                dispatcher.dispatch(
                    "search_jobs",
                    {"keywords": ["工程师"], "company": "大疆"},
                )
            )
            data = json.loads(result)
            assert data["total"] == 1
            assert data["company_filter"] == "大疆"
            assert data["company_filter_before"] == 2
            assert data["jobs"][0]["company"] == "大疆创新"

    def test_dispatch_search_jobs_platform_comma_split(self, dispatcher):
        """search_jobs with platform='byd,naura' splits to ['byd', 'naura']."""

        from agent_core.platforms.base import Job

        now = datetime.now(UTC)

        captured_platform_names = []

        async def fake_search_all(
            config, platform_names=None, directions=None, keywords=None, headless=False
        ):
            captured_platform_names.append(platform_names)
            return [
                Job(
                    id="1",
                    title="T",
                    company="C",
                    company_normalized="C",
                    description="D",
                    direction="equipment_amr",
                    platforms=["byd"],
                    urls={"byd": "http://x"},
                    first_seen=now,
                    last_seen=now,
                )
            ]

        with patch("agent_core.pipeline.search.search_all", new=fake_search_all):
            asyncio.run(
                dispatcher.dispatch(
                    "search_jobs",
                    {"keywords": ["T"], "platform": "byd, naura"},
                )
            )
            assert captured_platform_names == [["byd", "naura"]]

    # -- T5-4: the three pipeline tools previously had no dispatcher tests ---

    def _job_row(self):
        """A jobs-table row dict shaped like sqlite3.Row for Job.from_storage."""
        return {
            "id": "j1",
            "title": "工程师",
            "company": "ACME",
            "company_normalized": "ACME",
            "location": "苏州",
            "salary_min": 15000,
            "salary_max": 25000,
            "description": "岗位职责",
            "platforms": '["byd"]',
            "urls": '{"byd": "http://x"}',
            "direction": "default",
            "first_seen": "2026-01-01T00:00:00",
            "last_seen": "2026-01-01T00:00:00",
            "is_new": 1,
            "security_id": "",
            "lid": "",
            "published_at": "",
        }

    def test_dispatch_tailor_resume(self, dispatcher):
        """tailor_resume: enrich -> tailor -> save -> catalog (.md + .docx)."""
        dispatcher.db.execute.return_value.fetchone.return_value = self._job_row()

        async def _fake_enrich(job, config):
            return job

        async def _fake_tailor(job, config, provider):
            return "定制简历正文"

        with (
            patch("agent_core.pipeline.enrichment.enrich_job_jd", side_effect=_fake_enrich),
            patch("agent_core.pipeline.tailor.tailor_resume", side_effect=_fake_tailor),
            patch(
                "agent_core.pipeline.tailor.save_resume",
                return_value={"md": "o/a.md", "docx": "o/a.docx"},
            ),
            patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
        ):
            result = asyncio.run(dispatcher.dispatch("tailor_resume", {"job_id": "j1"}))
        data = json.loads(result)
        assert data["ok"] is True
        assert data["job_title"] == "工程师"
        assert data["company"] == "ACME"
        assert data["docx_path"] == "o/a.docx"
        assert data["preview"].startswith("定制简历正文")
        assert mock_catalog.call_count == 2  # .md + .docx both cataloged

    def test_dispatch_tailor_resume_missing_job(self, dispatcher):
        dispatcher.db.execute.return_value.fetchone.return_value = None
        result = asyncio.run(dispatcher.dispatch("tailor_resume", {"job_id": "nope"}))
        data = json.loads(result)
        assert "error" in data

    def test_dispatch_generate_cover_letter(self, dispatcher):
        """generate_cover_letter: enrich -> generate -> save -> catalog."""
        dispatcher.db.execute.return_value.fetchone.return_value = self._job_row()

        async def _fake_enrich(job, config):
            return job

        async def _fake_gen(job, config, provider):
            return "HR 你好，我是..."

        with (
            patch("agent_core.pipeline.enrichment.enrich_job_jd", side_effect=_fake_enrich),
            patch(
                "agent_core.pipeline.cover_letter.generate_cover_letter",
                side_effect=_fake_gen,
            ),
            patch(
                "agent_core.pipeline.cover_letter.save_cover_letter",
                return_value="o/a_hrmsg.md",
            ),
            patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
        ):
            result = asyncio.run(dispatcher.dispatch("generate_cover_letter", {"job_id": "j1"}))
        data = json.loads(result)
        assert data["ok"] is True
        assert data["path"] == "o/a_hrmsg.md"
        assert mock_catalog.call_count == 1

    def test_dispatch_interview_prep(self, dispatcher):
        """interview_prep: enrich -> predict -> save -> catalog with question count."""
        dispatcher.db.execute.return_value.fetchone.return_value = self._job_row()

        async def _fake_enrich(job, config):
            return job

        async def _fake_predict(job, config, provider):
            return {
                "technical": [{"q": "t1"}],
                "behavioral": [],
                "project": [{"q": "p1"}, {"q": "p2"}],
            }

        with (
            patch("agent_core.pipeline.enrichment.enrich_job_jd", side_effect=_fake_enrich),
            patch(
                "agent_core.pipeline.interview_prep.predict_questions",
                side_effect=_fake_predict,
            ),
            patch(
                "agent_core.pipeline.interview_prep.save_interview_prep",
                return_value="o/a_interview.json",
            ),
            patch("agent_core.pipeline.file_catalog.catalog_file") as mock_catalog,
        ):
            result = asyncio.run(dispatcher.dispatch("interview_prep", {"job_id": "j1"}))
        data = json.loads(result)
        assert data["ok"] is True
        assert data["total_questions"] == 3  # 1 technical + 2 project
        assert data["path"] == "o/a_interview.json"
        assert mock_catalog.call_count == 1


# ---------------------------------------------------------------------------
# REPL tests
# ---------------------------------------------------------------------------


class TestRepl:
    def _make_chat_response(self, content=None, tool_calls=None):
        """Helper to construct ChatResponse for mocks."""
        return ChatResponse(
            content=content,
            tool_calls=tool_calls or [],
        )

    def _make_tool_call(
        self, id="call_1", name="search_jobs", arguments='{"keywords": ["Python"]}'
    ):
        """Helper to construct ToolCall for mocks."""
        return ToolCall(id=id, name=name, arguments=arguments)

    @pytest.mark.asyncio
    async def test_process_turn_text_only(self):
        """LLM returns text without tool calls → print and return."""
        dispatcher = MagicMock()
        provider = MagicMock()
        provider.chat_with_tools = AsyncMock(
            return_value=self._make_chat_response(content="你好，需要什么帮助？")
        )

        messages: list[dict] = [{"role": "user", "content": "你好"}]

        from agent_core.agent.repl import _process_turn

        await _process_turn(messages, dispatcher, provider)

        # Verify assistant message appended
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "你好，需要什么帮助？"

    @pytest.mark.asyncio
    async def test_process_turn_with_tool_call(self):
        """LLM returns tool_calls → dispatch → get result → LLM final text."""
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value='{"total": 5, "jobs": []}')
        provider = MagicMock()
        provider.chat_with_tools = AsyncMock(
            side_effect=[
                # First call: tool_calls
                self._make_chat_response(tool_calls=[self._make_tool_call()]),
                # Second call: final text
                self._make_chat_response(content="找到5个Python相关职位，需要进一步筛选吗？"),
            ]
        )

        messages: list[dict] = [{"role": "user", "content": "帮我找Python工作"}]

        from agent_core.agent.repl import _process_turn

        await _process_turn(messages, dispatcher, provider)

        # Verify tool call was dispatched
        dispatcher.dispatch.assert_called_once_with("search_jobs", {"keywords": ["Python"]})

        # Verify tool result message added
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1

        # Verify final assistant message
        assert messages[-1]["role"] == "assistant"
        assert "Python" in messages[-1]["content"]

    @pytest.mark.asyncio
    async def test_process_turn_tool_error_recovery(self):
        """Tool returns error → LLM should get error text and respond gracefully."""
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            return_value=json.dumps({"error": "职位不存在: bad-id"}, ensure_ascii=False)
        )
        provider = MagicMock()
        provider.chat_with_tools = AsyncMock(
            side_effect=[
                self._make_chat_response(
                    tool_calls=[
                        self._make_tool_call(
                            name="get_job_detail", arguments='{"job_id": "bad-id"}'
                        )
                    ]
                ),
                self._make_chat_response(content="抱歉，没找到这个职位。请检查 ID 是否正确。"),
            ]
        )

        messages: list[dict] = [{"role": "user", "content": "查看职位 bad-id"}]

        from agent_core.agent.repl import _process_turn

        await _process_turn(messages, dispatcher, provider)

        # Error was dispatched
        dispatcher.dispatch.assert_called_once()
        # Tool result was added
        has_tool_msg = any(m["role"] == "tool" for m in messages)
        assert has_tool_msg
        # LLM got final text
        assert messages[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_process_turn_max_rounds_fallback(self):
        """When tool calls keep happening beyond max_rounds, force final response."""
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value='{"ok": true}')
        provider = MagicMock()

        # Return tool_calls every time, then final with tool_choice="none"
        call_count = [0]

        async def fake_chat_with_tools(messages, tools, tool_choice="auto", **kwargs):
            call_count[0] += 1
            if tool_choice == "none":
                return self._make_chat_response(content="好的，我已经处理完了。")
            if call_count[0] <= 6:
                return self._make_chat_response(tool_calls=[self._make_tool_call()])
            return self._make_chat_response(content="最终回复")

        provider.chat_with_tools = fake_chat_with_tools

        messages: list[dict] = [{"role": "user", "content": "做很多事情"}]

        from agent_core.agent.repl import _process_turn

        await _process_turn(messages, dispatcher, provider)

        # Should eventually get a final text response
        assert messages[-1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------


class TestChatCli:
    def test_chat_command_requires_api_key(self, monkeypatch):
        """chat command exits with error if DEEPSEEK_API_KEY is not set."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        from typer.testing import CliRunner

        from agent_core.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["chat"])
        # Should exit with error about missing API key
        assert result.exit_code != 0
        assert "DEEPSEEK_API_KEY" in result.stdout or "LLM unavailable" in result.stdout

    def test_chat_appears_in_help(self):
        from typer.testing import CliRunner

        from agent_core.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "chat" in result.stdout
