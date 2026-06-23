import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.agent.context_budget import ContextBudgetConfig
from zzcode.agent.tool_call_agent import ToolCallAgent
from zzcode.llm.client import LLMResponse, LLMToolCall
from zzcode.tools.base import BaseTool, ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult
from zzcode.ui.messages import FinalAnswer, SystemNotice, ToolResult as UiToolResult, ToolUse


class ReadTool(BaseTool):
    name = "read_file"
    description = "Read file."
    display_name = "Read"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def call(self, args, context, tool_call_id):
        return ToolResult.success(tool_call_id, self.name, f"content of {args['path']}")


class ReadToolWithMissing(ReadTool):
    def call(self, args, context, tool_call_id):
        if args["path"] == "1.txt":
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "文件不存在: 1.txt。可以使用 glob 搜索匹配文件。",
                metadata={"reason": "path_not_found"},
            )
        return ToolResult.success(tool_call_id, self.name, f"content of {args['path']}")


class GlobTool(BaseTool):
    name = "glob"
    description = "Find files."
    display_name = "Glob"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def call(self, args, context, tool_call_id):
        return ToolResult.success(
            tool_call_id,
            self.name,
            "tests/tool_test/1.txt",
            data={"matches": ["tests/tool_test/1.txt"]},
        )


class WriteTool(BaseTool):
    name = "write_file"
    description = "Write file."
    display_name = "Write"
    requires_approval = True
    is_destructive = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def call(self, args, context, tool_call_id):
        return ToolResult.success(tool_call_id, self.name, f"wrote {args['path']}")


class FakeChatClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, tools=None, temperature=0):
        self.calls.append({"messages": list(messages), "tools": tools, "temperature": temperature})
        if not self.responses:
            return None
        return self.responses.pop(0)


class CapturingRenderer:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def render(self, message) -> None:
        self.messages.append(message)


class CapturingTranscript:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def record_tool_use(self, tool_name: str, tool_input: object) -> None:
        self.events.append(("tool_use", tool_name, tool_input))

    def record_tool_result(self, tool_name: str, output: str, ok: bool = True) -> None:
        self.events.append(("tool_result", tool_name, output, ok))


class ToolCallAgentTest(unittest.TestCase):
    def test_read_file_tool_call_then_final_answer(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    content="I will read it.",
                    tool_calls=[
                        LLMToolCall(
                            id="call_read",
                            name="read_file",
                            arguments={"path": "README.md"},
                        )
                    ],
                ),
                LLMResponse(content="README says hello."),
            ]
        )
        renderer = CapturingRenderer()
        transcript = CapturingTranscript()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(ReadTool()),
                Path(tmp),
                renderer=renderer,
                transcript_sink=transcript,
            )
            answer = agent.run("summarize README", session_context="memory")

        self.assertEqual(answer, "README says hello.")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["tools"][0]["function"]["name"], "read_file")
        self.assertEqual(
            agent.messages[-2],
            {
                "role": "tool",
                "tool_call_id": "call_read",
                "name": "read_file",
                "content": "content of README.md",
            },
        )
        self.assertEqual(agent.messages[-1], {"role": "assistant", "content": "README says hello."})
        tool_uses = [message for message in renderer.messages if isinstance(message, ToolUse)]
        self.assertEqual(tool_uses[0].tool_input, {"path": "README.md"})
        self.assertIn(("tool_result", "read_file", "content of README.md", True), transcript.events)

    def test_write_file_tool_call_uses_permission_checker_then_final_answer(self) -> None:
        captured: list[ToolPermissionRequest] = []

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            captured.append(request)
            return ToolPermissionResult.allow(reason="test_allow")

        llm = FakeChatClient(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call_write",
                            name="write_file",
                            arguments={"path": "notes.md", "content": "hello"},
                        )
                    ],
                ),
                LLMResponse(content="Done."),
            ]
        )

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(WriteTool()),
                Path(tmp),
                renderer=CapturingRenderer(),
                permission_checker=checker,
            )
            answer = agent.run("write notes")

        self.assertEqual(answer, "Done.")
        self.assertEqual(captured[0].tool_call_id, "call_write")
        self.assertEqual(captured[0].tool_name, "write_file")
        self.assertTrue(captured[0].is_destructive)
        self.assertEqual(agent.messages[-2]["tool_call_id"], "call_write")
        self.assertEqual(agent.messages[-2]["content"], "wrote notes.md")

    def test_user_denied_tool_call_stops_current_turn(self) -> None:
        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            return ToolPermissionResult.deny("Tool execution denied by user.", reason="user_denied")

        llm = FakeChatClient(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call_write",
                            name="write_file",
                            arguments={"path": "notes.md", "content": "hello"},
                        )
                    ],
                ),
                LLMResponse(
                    content="I will try shell.",
                    tool_calls=[
                        LLMToolCall(
                            id="call_shell",
                            name="run_shell",
                            arguments={"command": "echo hello > notes.md"},
                        )
                    ],
                ),
            ]
        )
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(WriteTool()),
                Path(tmp),
                renderer=renderer,
                permission_checker=checker,
            )
            answer = agent.run("write notes")

        self.assertIsNone(answer)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(agent.messages[-1]["tool_call_id"], "call_write")
        self.assertEqual(agent.messages[-1]["content"], "Tool execution denied by user.")
        notices = [message for message in renderer.messages if isinstance(message, SystemNotice)]
        self.assertEqual(notices[-1].level, "warning")
        self.assertIn("已拒绝", notices[-1].text)

    def test_tool_argument_parse_error_is_returned_as_tool_result(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call_bad",
                            name="read_file",
                            arguments={},
                            parse_error="Tool arguments JSON parse failed",
                        )
                    ],
                ),
                LLMResponse(content="I could not read it."),
            ]
        )
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(llm, _registry(ReadTool()), Path(tmp), renderer=renderer)
            answer = agent.run("read")

        self.assertEqual(answer, "I could not read it.")
        self.assertEqual(agent.messages[-2]["tool_call_id"], "call_bad")
        self.assertEqual(agent.messages[-2]["content"], "Tool arguments JSON parse failed")
        results = [message for message in renderer.messages if isinstance(message, UiToolResult)]
        self.assertEqual(results[0].output, "Tool arguments JSON parse failed")
        self.assertFalse(results[0].ok)

    def test_multiple_tool_calls_are_returned_with_matching_ids(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(id="call_a", name="read_file", arguments={"path": "a.md"}),
                        LLMToolCall(id="call_b", name="read_file", arguments={"path": "b.md"}),
                    ],
                ),
                LLMResponse(content="Both files read."),
            ]
        )

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(llm, _registry(ReadTool()), Path(tmp), renderer=CapturingRenderer())
            answer = agent.run("read both")

        self.assertEqual(answer, "Both files read.")
        tool_messages = [message for message in agent.messages if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in tool_messages], ["call_a", "call_b"])
        self.assertEqual([message["content"] for message in tool_messages], ["content of a.md", "content of b.md"])

    def test_agent_can_recover_missing_file_path_with_glob(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    tool_calls=[LLMToolCall(id="call_read_missing", name="read_file", arguments={"path": "1.txt"})],
                    content="",
                ),
                LLMResponse(
                    tool_calls=[LLMToolCall(id="call_glob", name="glob", arguments={"pattern": "**/1.txt"})],
                    content="",
                ),
                LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="call_read_exact",
                            name="read_file",
                            arguments={"path": "tests/tool_test/1.txt"},
                        )
                    ],
                    content="",
                ),
                LLMResponse(content="Found and read the file."),
            ]
        )

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(ReadToolWithMissing(), GlobTool()),
                Path(tmp),
                renderer=CapturingRenderer(),
            )
            answer = agent.run("read 1.txt")

        self.assertEqual(answer, "Found and read the file.")
        tool_messages = [message for message in agent.messages if message["role"] == "tool"]
        self.assertEqual(
            [message["tool_call_id"] for message in tool_messages],
            ["call_read_missing", "call_glob", "call_read_exact"],
        )
        self.assertIn("文件不存在", tool_messages[0]["content"])
        self.assertEqual(tool_messages[1]["content"], "tests/tool_test/1.txt")
        self.assertEqual(tool_messages[2]["content"], "content of tests/tool_test/1.txt")

    def test_unknown_tool_result_is_marked_failed_for_ui(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    content="",
                    tool_calls=[LLMToolCall(id="call_missing", name="missing_tool", arguments={})],
                ),
                LLMResponse(content="Tool was unavailable."),
            ]
        )
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(llm, _registry(ReadTool()), Path(tmp), renderer=renderer)
            answer = agent.run("use missing")

        self.assertEqual(answer, "Tool was unavailable.")
        results = [message for message in renderer.messages if isinstance(message, UiToolResult)]
        self.assertEqual(results[0].id, "call_missing")
        self.assertFalse(results[0].ok)
        self.assertIn("Unknown tool", results[0].output)

    def test_llm_none_response_stops_with_error_notice(self) -> None:
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                FakeChatClient([]),
                _registry(ReadTool()),
                Path(tmp),
                renderer=renderer,
            )
            answer = agent.run("read")

        self.assertIsNone(answer)
        notices = [message for message in renderer.messages if isinstance(message, SystemNotice)]
        self.assertEqual(notices[-1].level, "error")

    def test_max_turns_returns_none_when_tools_never_finish(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(
                    tool_calls=[LLMToolCall(id="call_1", name="read_file", arguments={"path": "a.md"})],
                    content="",
                ),
                LLMResponse(
                    tool_calls=[LLMToolCall(id="call_2", name="read_file", arguments={"path": "b.md"})],
                    content="",
                ),
            ]
        )
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(ReadTool()),
                Path(tmp),
                max_steps=2,
                renderer=renderer,
            )
            answer = agent.run("loop")

        self.assertIsNone(answer)
        notices = [message for message in renderer.messages if isinstance(message, SystemNotice)]
        self.assertEqual(notices[-1].level, "warning")
        self.assertIn("maximum turns", notices[-1].text)

    def test_context_budget_blocks_before_llm_call(self) -> None:
        renderer = CapturingRenderer()
        llm = FakeChatClient([LLMResponse(content="should not be called")])
        tiny_budget = ContextBudgetConfig(
            context_window_tokens=40,
            reserved_output_tokens=5,
            auto_compact_buffer_tokens=10,
            blocking_buffer_tokens=3,
        )

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(ReadTool()),
                Path(tmp),
                renderer=renderer,
                context_budget=tiny_budget,
            )
            answer = agent.run("x" * 400)

        self.assertIsNone(answer)
        self.assertEqual(len(llm.calls), 0)
        notices = [message for message in renderer.messages if isinstance(message, SystemNotice)]
        self.assertIn("context budget exceeded", notices[-1].text)

    def test_repeated_tool_failures_stop_current_turn(self) -> None:
        llm = FakeChatClient(
            [
                LLMResponse(tool_calls=[LLMToolCall(id="call_1", name="missing_tool", arguments={})], content=""),
                LLMResponse(tool_calls=[LLMToolCall(id="call_2", name="missing_tool", arguments={})], content=""),
                LLMResponse(tool_calls=[LLMToolCall(id="call_3", name="missing_tool", arguments={})], content=""),
                LLMResponse(content="should not be reached"),
            ]
        )
        renderer = CapturingRenderer()

        with TemporaryDirectory() as tmp:
            agent = ToolCallAgent(
                llm,
                _registry(ReadTool()),
                Path(tmp),
                max_steps=5,
                renderer=renderer,
            )
            answer = agent.run("keep using missing tool")

        self.assertIsNone(answer)
        self.assertEqual(len(llm.calls), 3)
        notices = [message for message in renderer.messages if isinstance(message, SystemNotice)]
        self.assertIn("repeated tool failures", notices[-1].text)


def _registry(*tools: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


if __name__ == "__main__":
    unittest.main()
