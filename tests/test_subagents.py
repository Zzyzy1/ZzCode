import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zzcode.agent.react_text import TextReActAgent
from zzcode.legacy import build_legacy_tools
from zzcode.memory import TranscriptRecorder, create_session_scope
from zzcode.subagents import (
    AutoMemoryExtractionWorker,
    AutoMemoryExtractionResult,
    ForkedAgentRunner,
    GENERAL_PURPOSE_SUBAGENT,
    RestrictedToolExecutor,
    SessionMemoryUpdateResult,
    SessionMemoryUpdateWorker,
    SidechainTranscriptRecorder,
    SystemAgentScheduleResult,
    SubagentDefinition,
    SystemAgentScheduler,
    UserSubagentRunner,
    build_subagent_tool_executor,
    create_subagent_context,
    get_builtin_subagents,
    load_subagent_definitions,
    load_subagents_from_dir,
    parse_agent_tool_input,
    parse_subagent_markdown,
)
from zzcode.tools.builtin import register_builtin_tools
from zzcode.tools.executor import ToolExecutor


class SubagentDefinitionTest(unittest.TestCase):
    def test_general_purpose_subagent_matches_initial_definition(self) -> None:
        self.assertEqual(GENERAL_PURPOSE_SUBAGENT.name, "general-purpose")
        self.assertIn("搜索", GENERAL_PURPOSE_SUBAGENT.description)
        self.assertEqual(
            GENERAL_PURPOSE_SUBAGENT.tools,
            ("list_files", "read_file", "write_file", "edit_file", "append_file", "run_shell"),
        )
        self.assertEqual(GENERAL_PURPOSE_SUBAGENT.max_steps, 5)
        self.assertFalse(GENERAL_PURPOSE_SUBAGENT.background)
        self.assertEqual(GENERAL_PURPOSE_SUBAGENT.source, "built-in")
        self.assertIn("主 Agent", GENERAL_PURPOSE_SUBAGENT.system_prompt)

    def test_get_builtin_subagents_returns_general_purpose(self) -> None:
        agents = get_builtin_subagents()

        self.assertEqual(agents, [GENERAL_PURPOSE_SUBAGENT])

    def test_subagent_definition_rejects_invalid_required_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            SubagentDefinition(name="", description="desc", system_prompt="prompt")
        with self.assertRaisesRegex(ValueError, "description"):
            SubagentDefinition(name="agent", description="", system_prompt="prompt")
        with self.assertRaisesRegex(ValueError, "system_prompt"):
            SubagentDefinition(name="agent", description="desc", system_prompt="")
        with self.assertRaisesRegex(ValueError, "max_steps"):
            SubagentDefinition(name="agent", description="desc", system_prompt="prompt", max_steps=0)


class SubagentLoaderTest(unittest.TestCase):
    def test_parse_subagent_markdown_reads_frontmatter_and_body(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewer.md"
            path.write_text(
                "\n".join(
                    [
                        "---",
                        "name: reviewer",
                        "description: 检查代码",
                        "tools: read_file, list_files",
                        "disallowed_tools: run_shell",
                        "model: haiku",
                        "permission_mode: acceptEdits",
                        "max_steps: 3",
                        "background: true",
                        "---",
                        "",
                        "你是代码审查子 Agent。",
                    ]
                ),
                encoding="utf-8",
            )

            agent = parse_subagent_markdown(path, source="project")

        self.assertIsNotNone(agent)
        assert agent is not None
        self.assertEqual(agent.name, "reviewer")
        self.assertEqual(agent.description, "检查代码")
        self.assertEqual(agent.tools, ("read_file", "list_files"))
        self.assertEqual(agent.disallowed_tools, ("run_shell",))
        self.assertEqual(agent.model, "haiku")
        self.assertEqual(agent.permission_mode, "acceptEdits")
        self.assertEqual(agent.max_steps, 3)
        self.assertTrue(agent.background)
        self.assertEqual(agent.source, "project")
        self.assertEqual(agent.system_prompt, "你是代码审查子 Agent。")

    def test_parse_subagent_markdown_skips_files_without_frontmatter(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text("普通说明文档", encoding="utf-8")

            agent = parse_subagent_markdown(path, source="project")

        self.assertIsNone(agent)

    def test_load_subagents_from_dir_reports_invalid_files(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bad.md").write_text(
                "---\nname: bad\n---\n\n缺少 description。",
                encoding="utf-8",
            )

            agents, failed = load_subagents_from_dir(directory, source="project")

        self.assertEqual(agents, [])
        self.assertEqual(len(failed), 1)
        self.assertIn("description", failed[0][1])

    def test_load_subagent_definitions_uses_project_override_order(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            (home / ".zzcode" / "agents").mkdir(parents=True)
            (root / ".zzcode" / "agents").mkdir(parents=True)
            (home / ".zzcode" / "agents" / "general.md").write_text(
                "---\n"
                "name: general-purpose\n"
                "description: 用户通用 Agent\n"
                "tools: read_file\n"
                "---\n\n"
                "用户级提示词。",
                encoding="utf-8",
            )
            (root / ".zzcode" / "agents" / "general.md").write_text(
                "---\n"
                "name: general-purpose\n"
                "description: 项目通用 Agent\n"
                "tools: list_files\n"
                "---\n\n"
                "项目级提示词。",
                encoding="utf-8",
            )

            result = load_subagent_definitions(root, home=home)

        active = {agent.name: agent for agent in result.active_agents}
        self.assertEqual(active["general-purpose"].description, "项目通用 Agent")
        self.assertEqual(active["general-purpose"].tools, ("list_files",))
        self.assertEqual(active["general-purpose"].source, "project")
        self.assertEqual([agent.source for agent in result.all_agents], ["built-in", "user", "project"])
        self.assertEqual(result.failed_files, ())


class SubagentContextTest(unittest.TestCase):
    def test_create_subagent_context_creates_paths_and_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")

            context = create_subagent_context(
                parent_scope,
                "general-purpose",
                agent_id="agent-test",
                description="检查项目结构",
            )

            metadata = json.loads(context.metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(context.agent_id, "agent-test")
        self.assertEqual(context.parent_session_id, "main-session")
        self.assertEqual(context.subagent_name, "general-purpose")
        self.assertEqual(context.agent_dir.name, "agent-test")
        self.assertEqual(context.transcript_path.name, "transcript.jsonl")
        self.assertEqual(metadata["agentId"], "agent-test")
        self.assertEqual(metadata["parentSessionId"], "main-session")
        self.assertEqual(metadata["subagentName"], "general-purpose")
        self.assertEqual(metadata["description"], "检查项目结构")

    def test_sidechain_transcript_records_agent_events_with_parent_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            context = create_subagent_context(parent_scope, "general-purpose", agent_id="agent-test")
            recorder = SidechainTranscriptRecorder(context)

            first = recorder.record_user("阅读 README")
            second = recorder.record_tool_use("read_file", "README.md")
            third = recorder.record_tool_result("read_file", "内容", ok=True)
            fourth = recorder.record_assistant("README 内容摘要")
            events = [json.loads(line) for line in context.transcript_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([event["type"] for event in events], ["user", "tool_use", "tool_result", "assistant"])
        self.assertEqual([event["sequence"] for event in events], [0, 1, 2, 3])
        self.assertIsNone(first["parentEventId"])
        self.assertEqual(second["parentEventId"], first["eventId"])
        self.assertEqual(third["parentEventId"], second["eventId"])
        self.assertEqual(fourth["parentEventId"], third["eventId"])
        self.assertEqual({event["agentId"] for event in events}, {"agent-test"})
        self.assertEqual({event["parentSessionId"] for event in events}, {"main-session"})
        self.assertEqual({event["subagentName"] for event in events}, {"general-purpose"})

    def test_sidechain_transcript_restores_sequence_from_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            context = create_subagent_context(parent_scope, "general-purpose", agent_id="agent-test")
            first_recorder = SidechainTranscriptRecorder(context)
            first_event = first_recorder.record_user("任务")

            second_recorder = SidechainTranscriptRecorder(context)
            second_event = second_recorder.record_assistant("结果")

        self.assertEqual(second_event["sequence"], 1)
        self.assertEqual(second_event["parentEventId"], first_event["eventId"])


class FakeThinkClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def think(self, messages: list[dict[str, str]]) -> str:
        self.prompts.append(messages[-1]["content"])
        if not self.responses:
            return ""
        return self.responses.pop(0)


class TextReActActionParserTest(unittest.TestCase):
    def test_parse_action_accepts_single_balanced_tool_action(self) -> None:
        tool_name, tool_input = TextReActAgent.parse_action("write_file[tests/1.txt|||邹陈卫民]")

        self.assertEqual(tool_name, "write_file")
        self.assertEqual(tool_input, "tests/1.txt|||邹陈卫民")

    def test_parse_action_rejects_trailing_think_or_second_action(self) -> None:
        polluted = (
            "write_file[tests/1.txt|||邹陈卫民]</think>"
            "write_file[tests/1.txt|||邹陈卫民] 成功写入。\n"
            "Action: agent[general-purpose|||写2.txt|||写入2.txt]"
        )
        second_action = "write_file[tests/1.txt|||邹陈卫民]\nAction: agent[general-purpose|||写2.txt|||写入2.txt]"

        self.assertEqual(TextReActAgent.parse_action(polluted), (None, None))
        self.assertEqual(TextReActAgent.parse_action(second_action), (None, None))

    def test_parse_action_input_rejects_polluted_finish(self) -> None:
        self.assertEqual(TextReActAgent.parse_action_input("Finish[完成]"), "完成")
        self.assertEqual(TextReActAgent.parse_action_input("Finish[完成]</think> trailing"), "")


class UserSubagentRunnerTest(unittest.TestCase):
    def test_build_subagent_tool_executor_filters_tools(self) -> None:
        base_tools = ToolExecutor()
        base_tools.register_tool("read_file", "读取", lambda _input: "read")
        base_tools.register_tool("run_shell", "命令", lambda _input: "shell")
        definition = SubagentDefinition(
            name="reader",
            description="只读",
            system_prompt="只读子 Agent",
            tools=("read_file", "run_shell"),
            disallowed_tools=("run_shell",),
        )

        child_tools = build_subagent_tool_executor(base_tools, definition)

        self.assertEqual(child_tools.tool_names_text(), "read_file")
        self.assertEqual(child_tools.execute("run_shell", "echo hi"), "Error: tool 'run_shell' was not found.")

    def test_user_subagent_runner_runs_child_agent_and_records_transcript(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            base_tools = ToolExecutor()
            base_tools.register_tool("read_file", "读取文件", lambda path: f"content:{path}", display_name="Read")
            llm = FakeThinkClient(
                [
                    "Thought: 需要读取文件\nAction: read_file[README.md]",
                    "Thought: 已经拿到内容\nAction: Finish[README 摘要]",
                ]
            )
            definition = SubagentDefinition(
                name="reader",
                description="读取文件",
                system_prompt="你是读取文件的子 Agent。",
                tools=("read_file",),
                max_steps=3,
            )
            runner = UserSubagentRunner(
                llm_client=llm,
                parent_scope=parent_scope,
                base_tools=base_tools,
                permission_checker=lambda *_args: True,
            )

            result = runner.run(
                definition=definition,
                prompt="请读取 README.md",
                description="读取 README",
                agent_id="agent-reader",
            )
            events = [json.loads(line) for line in Path(result.transcript_path).read_text(encoding="utf-8").splitlines()]

        self.assertTrue(result.ok)
        self.assertEqual(result.result, "README 摘要")
        self.assertEqual(result.agent_id, "agent-reader")
        self.assertEqual([event["type"] for event in events], ["user", "tool_use", "tool_result", "assistant"])
        self.assertEqual(events[1]["toolName"], "read_file")
        self.assertEqual(events[2]["output"], "content:README.md")
        self.assertIn("你是读取文件的子 Agent。", llm.prompts[0])

    def test_user_subagent_runner_returns_failure_without_final_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            base_tools = ToolExecutor()
            llm = FakeThinkClient(["Thought: 无法完成\nAction: missing_tool[input]"])
            definition = SubagentDefinition(
                name="limited",
                description="有限 agent",
                system_prompt="有限子 Agent",
                max_steps=1,
            )
            runner = UserSubagentRunner(
                llm_client=llm,
                parent_scope=parent_scope,
                base_tools=base_tools,
            )

            result = runner.run(definition=definition, prompt="执行任务", agent_id="agent-limited")
            events = [json.loads(line) for line in Path(result.transcript_path).read_text(encoding="utf-8").splitlines()]

        self.assertFalse(result.ok)
        self.assertIsNone(result.result)
        self.assertIn("without final answer", result.error or "")
        self.assertEqual(events[-1]["type"], "error")


class ForkedAgentRunnerTest(unittest.TestCase):
    def test_forked_agent_runner_runs_with_system_tool_pool_and_records_transcript(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            tools = ToolExecutor()
            tools.register_tool("read_transcript", "读取 transcript", lambda path: f"events:{path}")
            llm = FakeThinkClient(
                [
                    "Thought: 需要读取主会话 transcript\nAction: read_transcript[transcript.jsonl]",
                    "Thought: 已经拿到事件\nAction: Finish[summary updated]",
                ]
            )
            runner = ForkedAgentRunner(
                llm_client=llm,
                parent_scope=parent_scope,
                tool_executor=tools,
                permission_checker=lambda *_args: True,
            )

            result = runner.run(
                name="session-memory-updater",
                prompt="更新当前 session memory",
                description="系统维护任务",
                agent_id="agent-system",
                max_steps=3,
            )
            events = [json.loads(line) for line in Path(result.transcript_path).read_text(encoding="utf-8").splitlines()]
            metadata = json.loads((parent_scope.session_dir / "subagents" / "agent-system" / "metadata.json").read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.result, "summary updated")
        self.assertEqual(result.subagent_name, "session-memory-updater")
        self.assertEqual([event["type"] for event in events], ["user", "tool_use", "tool_result", "assistant"])
        self.assertEqual(events[1]["toolName"], "read_transcript")
        self.assertEqual(events[2]["output"], "events:transcript.jsonl")
        self.assertEqual(metadata["source"], "system")
        self.assertEqual(metadata["subagentName"], "session-memory-updater")

    def test_forked_agent_runner_returns_failure_without_final_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            tools = ToolExecutor()
            llm = FakeThinkClient(["Thought: 工具不可用\nAction: write_memory[x]"])
            runner = ForkedAgentRunner(
                llm_client=llm,
                parent_scope=parent_scope,
                tool_executor=tools,
            )

            result = runner.run(
                name="auto-memory-extraction",
                prompt="提取长期记忆",
                agent_id="agent-auto-memory",
                max_steps=1,
            )
            events = [json.loads(line) for line in Path(result.transcript_path).read_text(encoding="utf-8").splitlines()]

        self.assertFalse(result.ok)
        self.assertIsNone(result.result)
        self.assertIn("without final answer", result.error or "")
        self.assertEqual(events[-1]["type"], "error")

    def test_forked_agent_runner_does_not_inherit_unregistered_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            parent_scope = create_session_scope(Path(tmp), "main-session")
            tools = ToolExecutor()
            tools.register_tool("allowed_tool", "允许工具", lambda _input: "allowed")
            llm = FakeThinkClient(["Thought: 尝试越权\nAction: run_shell[echo hi]"])
            runner = ForkedAgentRunner(
                llm_client=llm,
                parent_scope=parent_scope,
                tool_executor=tools,
            )

            result = runner.run(
                name="restricted-system-agent",
                prompt="执行受限系统任务",
                agent_id="agent-restricted",
                max_steps=1,
            )
            events = [json.loads(line) for line in Path(result.transcript_path).read_text(encoding="utf-8").splitlines()]

        self.assertFalse(result.ok)
        self.assertEqual(events[1]["toolName"], "run_shell")
        self.assertEqual(events[2]["output"], "Error: tool 'run_shell' was not found.")


class RestrictedToolExecutorTest(unittest.TestCase):
    def test_restricted_tool_executor_filters_tools_by_allow_list(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            base_tools = ToolExecutor()
            register_builtin_tools(base_tools, project_root)

            restricted = RestrictedToolExecutor(
                base_tools,
                project_root=project_root,
                allow_tools={"read_file"},
            )

        self.assertEqual(restricted.tool_names_text(), "read_file")
        self.assertEqual(restricted.execute("run_shell", "echo hi"), "Error: tool 'run_shell' was not found.")

    def test_restricted_tool_executor_limits_read_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            allowed_dir = project_root / "allowed"
            allowed_dir.mkdir()
            (allowed_dir / "note.md").write_text("allowed content", encoding="utf-8")
            (project_root / "secret.md").write_text("secret content", encoding="utf-8")
            base_tools = ToolExecutor()
            register_builtin_tools(base_tools, project_root)
            restricted = RestrictedToolExecutor(
                base_tools,
                project_root=project_root,
                allow_tools={"read_file", "list_files"},
                allow_read_paths=[allowed_dir],
            )

            allowed = restricted.execute("read_file", "allowed/note.md")
            denied = restricted.execute("read_file", "secret.md")

        self.assertEqual(allowed, "allowed content")
        self.assertIn("restricted tool read path denied", denied)

    def test_restricted_tool_executor_limits_write_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            memory_dir = project_root / ".zzcode" / "memory"
            memory_dir.mkdir(parents=True)
            base_tools = ToolExecutor()
            register_builtin_tools(base_tools, project_root)
            restricted = RestrictedToolExecutor(
                base_tools,
                project_root=project_root,
                allow_tools={"write_file", "append_file", "edit_file"},
                allow_write_paths=[memory_dir],
            )

            allowed = restricted.execute("write_file", ".zzcode/memory/topic.md|||记忆")
            denied = restricted.execute("write_file", "README.md|||越权")
            append = restricted.execute("append_file", ".zzcode/memory/topic.md|||追加")
            edit = restricted.execute("edit_file", ".zzcode/memory/topic.md|||记忆|||长期记忆")

        self.assertIn("Wrote .zzcode/memory/topic.md", allowed)
        self.assertIn("restricted tool write path denied", denied)
        self.assertIn("Appended .zzcode/memory/topic.md", append)
        self.assertIn("Edited .zzcode/memory/topic.md", edit)
        self.assertFalse((project_root / "README.md").exists())

    def test_restricted_tool_executor_denies_project_escape_before_base_tool_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            memory_dir = project_root / ".zzcode" / "memory"
            memory_dir.mkdir(parents=True)
            base_tools = ToolExecutor()
            register_builtin_tools(base_tools, project_root)
            restricted = RestrictedToolExecutor(
                base_tools,
                project_root=project_root,
                allow_tools={"read_file", "write_file"},
                allow_read_paths=[memory_dir],
                allow_write_paths=[memory_dir],
            )

            read_denied = restricted.execute("read_file", "../outside.md")
            write_denied = restricted.execute("write_file", "../outside.md|||bad")

        self.assertIn("路径越界", read_denied)
        self.assertIn("路径越界", write_denied)


class SessionMemoryUpdateWorkerTest(unittest.TestCase):
    def test_session_memory_update_worker_skips_when_no_new_events(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            worker = SessionMemoryUpdateWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
            )

            result = worker.run()

        self.assertFalse(result.ran)
        self.assertFalse(result.updated)
        self.assertEqual(result.event_count, 0)
        self.assertIsNone(result.last_summarized_event_id)

    def test_session_memory_update_worker_updates_summary_and_state(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            transcript = TranscriptRecorder(parent_scope)
            transcript.begin_turn()
            user_event = transcript.record("user", text="开始实现系统 memory worker")
            assistant_event = transcript.record("assistant", text="已完成第一版")
            transcript.end_turn()
            llm = FakeThinkClient(
                [
                    (
                        "Thought: 需要写入 session summary\n"
                        "Action: write_file[.zzcode/sessions/main-session/session-memory/summary.md|||# Session Title\n"
                        "System memory worker\n\n# Current State\n已完成第一版。]"
                    ),
                    "Thought: 已更新\nAction: Finish[session memory updated]",
                ]
            )
            worker = SessionMemoryUpdateWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=llm,
                max_steps=3,
            )

            result = worker.run()
            state = json.loads((parent_scope.session_dir / "system" / "session-memory-state.json").read_text(encoding="utf-8"))
            summary = parent_scope.session_memory_path.read_text(encoding="utf-8")

        self.assertTrue(result.ran)
        self.assertTrue(result.updated)
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.last_summarized_event_id, assistant_event["eventId"])
        self.assertEqual(state["last_summarized_event_id"], assistant_event["eventId"])
        self.assertEqual(state["turn_count"], 2)
        self.assertIn("System memory worker", summary)
        self.assertIn("开始实现系统 memory worker", llm.prompts[0])
        self.assertIn(user_event["eventId"], llm.prompts[0])
        self.assertIsNotNone(result.transcript_path)

    def test_session_memory_update_worker_keeps_cursor_when_forked_agent_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            transcript = TranscriptRecorder(parent_scope)
            transcript.record("user", text="需要更新 summary")
            llm = FakeThinkClient(["Thought: 工具名错误\nAction: run_shell[echo no]"])
            worker = SessionMemoryUpdateWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=llm,
                max_steps=1,
            )

            result = worker.run()

        self.assertTrue(result.ran)
        self.assertFalse(result.updated)
        self.assertIn("without final answer", result.error or "")
        self.assertFalse((parent_scope.session_dir / "system" / "session-memory-state.json").exists())


class AutoMemoryExtractionWorkerTest(unittest.TestCase):
    def test_auto_memory_extraction_worker_skips_when_main_agent_wrote_memory(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            transcript = TranscriptRecorder(parent_scope)
            transcript.record("user", text="请记住我喜欢小步实现")
            memory_event = transcript.record(
                "tool_use",
                toolName="write_file",
                input=".zzcode/memory/user/preferences.md|||偏好",
            )
            worker = AutoMemoryExtractionWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
            )

            result = worker.run()
            state = json.loads((parent_scope.session_dir / "system" / "auto-memory-state.json").read_text(encoding="utf-8"))

        self.assertFalse(result.ran)
        self.assertTrue(result.skipped)
        self.assertFalse(result.updated)
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.last_processed_event_id, memory_event["eventId"])
        self.assertEqual(state["last_processed_event_id"], memory_event["eventId"])
        self.assertEqual(state["last_memory_write_event_id"], memory_event["eventId"])

    def test_auto_memory_extraction_worker_writes_topic_file_and_index(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            transcript = TranscriptRecorder(parent_scope)
            transcript.record("user", text="以后请优先用 rg 搜索文件")
            assistant_event = transcript.record("assistant", text="我会记住这个偏好")
            llm = FakeThinkClient(
                [
                    (
                        "Thought: 需要写详细记忆\n"
                        "Action: write_file[.zzcode/memory/user/search-preference.md|||---\n"
                        "type: user\n"
                        "description: 用户偏好使用 rg 搜索\n"
                        "---\n\n"
                        "用户偏好：搜索文件时优先使用 rg。]"
                    ),
                    (
                        "Thought: 需要更新索引\n"
                        "Action: append_file[.zzcode/memory/MEMORY.md|||- user/search-preference.md: 用户偏好使用 rg 搜索]"
                    ),
                    "Thought: 已完成\nAction: Finish[memory extracted]",
                ]
            )
            worker = AutoMemoryExtractionWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=llm,
                max_steps=4,
            )

            result = worker.run()
            state = json.loads((parent_scope.session_dir / "system" / "auto-memory-state.json").read_text(encoding="utf-8"))
            topic = (project_root / ".zzcode" / "memory" / "user" / "search-preference.md").read_text(encoding="utf-8")
            index = (project_root / ".zzcode" / "memory" / "MEMORY.md").read_text(encoding="utf-8")

        self.assertTrue(result.ran)
        self.assertTrue(result.updated)
        self.assertFalse(result.skipped)
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.last_processed_event_id, assistant_event["eventId"])
        self.assertEqual(state["last_processed_event_id"], assistant_event["eventId"])
        self.assertIsNone(state["last_memory_write_event_id"])
        self.assertIn("优先使用 rg", topic)
        self.assertIn("user/search-preference.md", index)
        self.assertIn("Existing memory manifest", llm.prompts[0])
        self.assertIsNotNone(result.transcript_path)

    def test_auto_memory_extraction_worker_keeps_cursor_when_forked_agent_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            transcript = TranscriptRecorder(parent_scope)
            transcript.record("user", text="请长期记住偏好")
            llm = FakeThinkClient(["Thought: 越权写入\nAction: write_file[README.md|||bad]"])
            worker = AutoMemoryExtractionWorker(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=llm,
                max_steps=1,
            )

            result = worker.run()

        self.assertTrue(result.ran)
        self.assertFalse(result.updated)
        self.assertFalse(result.skipped)
        self.assertIn("without final answer", result.error or "")
        self.assertFalse((parent_scope.session_dir / "system" / "auto-memory-state.json").exists())
        self.assertFalse((project_root / "README.md").exists())


class SystemAgentSchedulerTest(unittest.TestCase):
    def test_scheduler_runs_session_then_auto_memory_on_turn_finished(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
            )

            result = scheduler.on_turn_finished()

        self.assertEqual(calls, ["session:False", "auto"])
        self.assertIsNotNone(result.session_memory)
        self.assertIsNotNone(result.auto_memory)
        self.assertEqual(result.errors, ())

    def test_scheduler_forces_session_memory_before_compact(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
            )

            result = scheduler.before_compact()

        self.assertEqual(calls, ["session:True"])
        self.assertIsNotNone(result.session_memory)
        self.assertIsNone(result.auto_memory)
        self.assertEqual(result.errors, ())

    def test_scheduler_schedules_turn_finished_in_background(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            started = threading.Event()
            release = threading.Event()
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
                session_started=started,
                session_release=release,
            )

            scheduled = scheduler.schedule_turn_finished()
            self.assertTrue(started.wait(timeout=2))
            self.assertEqual(scheduled, SystemAgentScheduleResult(scheduled=True, reason="scheduled"))
            self.assertEqual(calls, ["session:False"])

            release.set()
            drained = scheduler.drain_pending(timeout_seconds=2)
            scheduler.close(timeout_seconds=0)

        self.assertTrue(drained)
        self.assertEqual(calls, ["session:False", "auto"])

    def test_scheduler_coalesces_pending_background_turns(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            started = threading.Event()
            release = threading.Event()
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
                session_started=started,
                session_release=release,
            )

            first = scheduler.schedule_turn_finished()
            self.assertTrue(started.wait(timeout=2))
            second = scheduler.schedule_turn_finished()
            release.set()
            drained = scheduler.drain_pending(timeout_seconds=2)
            scheduler.close(timeout_seconds=0)

        self.assertTrue(first.scheduled)
        self.assertFalse(second.scheduled)
        self.assertTrue(second.pending)
        self.assertTrue(drained)
        self.assertEqual(calls, ["session:False", "auto", "session:False", "auto"])

    def test_scheduler_can_disable_background_system_agents(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
            )

            with patch.dict("os.environ", {"ZZCODE_SYSTEM_AGENTS": "0"}):
                scheduled = scheduler.schedule_turn_finished()

        self.assertFalse(scheduled.scheduled)
        self.assertTrue(scheduled.disabled)
        self.assertEqual(calls, [])

    def test_scheduler_collects_worker_errors_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            calls: list[str] = []
            project_root = Path(tmp)
            parent_scope = create_session_scope(project_root, "main-session")
            scheduler = _FakeSystemAgentScheduler(
                project_root=project_root,
                parent_scope=parent_scope,
                llm_client=FakeThinkClient([]),
                calls=calls,
                fail_session=True,
                fail_auto=True,
            )

            result = scheduler.on_turn_finished()
            compact_result = scheduler.before_compact()

        self.assertEqual(calls, ["session:False", "auto", "session:True"])
        self.assertIsNone(result.session_memory)
        self.assertIsNone(result.auto_memory)
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(len(compact_result.errors), 1)


class _FakeSystemAgentScheduler(SystemAgentScheduler):
    def __init__(
        self,
        *args,
        calls: list[str],
        fail_session: bool = False,
        fail_auto: bool = False,
        session_started: threading.Event | None = None,
        session_release: threading.Event | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.calls = calls
        self.fail_session = fail_session
        self.fail_auto = fail_auto
        self.session_started = session_started
        self.session_release = session_release

    def _session_memory_worker(self):
        return _FakeSessionMemoryWorker(
            self.calls,
            self.fail_session,
            started=self.session_started,
            release=self.session_release,
        )

    def _auto_memory_worker(self):
        return _FakeAutoMemoryWorker(self.calls, self.fail_auto)


class _FakeSessionMemoryWorker:
    def __init__(
        self,
        calls: list[str],
        fail: bool,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.calls = calls
        self.fail = fail
        self.started = started
        self.release = release

    def run(self, *, force: bool = False) -> SessionMemoryUpdateResult:
        self.calls.append(f"session:{force}")
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        if self.fail:
            raise RuntimeError("session failed")
        return SessionMemoryUpdateResult(
            ran=True,
            updated=True,
            event_count=1,
            last_summarized_event_id="event-session",
        )


class _FakeAutoMemoryWorker:
    def __init__(self, calls: list[str], fail: bool) -> None:
        self.calls = calls
        self.fail = fail

    def run(self) -> AutoMemoryExtractionResult:
        self.calls.append("auto")
        if self.fail:
            raise RuntimeError("auto failed")
        return AutoMemoryExtractionResult(
            ran=True,
            updated=True,
            skipped=False,
            event_count=1,
            last_processed_event_id="event-auto",
        )


class AgentToolTest(unittest.TestCase):
    def test_parse_agent_tool_input_supports_full_and_default_forms(self) -> None:
        full = parse_agent_tool_input("reader|||读取 README|||请读取 README.md")
        default = parse_agent_tool_input("请总结项目")

        self.assertEqual(full.subagent_type, "reader")
        self.assertEqual(full.description, "读取 README")
        self.assertEqual(full.prompt, "请读取 README.md")
        self.assertEqual(default.subagent_type, "general-purpose")
        self.assertEqual(default.description, "")
        self.assertEqual(default.prompt, "请总结项目")

    def test_build_tools_registers_agent_tool_when_dependencies_are_available(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            session_scope = create_session_scope(project_root, "main-session")
            llm = FakeThinkClient(["Thought: 直接回答\nAction: Finish[子任务完成]"])
            tools = build_legacy_tools(
                project_root,
                llm_client=llm,
                session_scope=session_scope,
                permission_checker=lambda *_args: True,
                session_context_provider=lambda: "session context",
            )

            output = tools.execute("agent", "general-purpose|||测试子任务|||请完成子任务")

        self.assertIn("Agent agent-", output)
        self.assertIn("completed", output)
        self.assertIn("子任务完成", output)
        self.assertIn("Transcript:", output)
        self.assertIn("agent", tools.tool_names_text())

    def test_build_tools_without_subagent_dependencies_keeps_agent_tool_hidden(self) -> None:
        with TemporaryDirectory() as tmp:
            tools = build_legacy_tools(Path(tmp))

        self.assertIsNone(tools.get_registered_tool("agent"))


if __name__ == "__main__":
    unittest.main()
