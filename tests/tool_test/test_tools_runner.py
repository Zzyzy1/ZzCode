import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.tools.base import (
    BaseTool,
    ToolCall,
    ToolContext,
    ToolPermissionRequest,
    ToolPermissionResult,
    ToolValidationResult,
)
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult
from zzcode.tools.runner import ToolRunner


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo test tool."
    display_name = "Echo"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def call(self, args, context, tool_call_id):
        return ToolResult.success(tool_call_id, self.name, args["text"])


class CustomValidationTool(EchoTool):
    name = "custom"

    def validate_input(self, args):
        if args["text"] == "bad":
            return ToolValidationResult.failure("text cannot be bad")
        return ToolValidationResult.success()


class DenyTool(EchoTool):
    name = "deny"

    def check_permission(self, args, context):
        return ToolPermissionResult.deny("blocked", reason="test_deny")


class AskTool(EchoTool):
    name = "ask"
    display_name = "Ask"
    is_destructive = True

    def check_permission(self, args, context):
        return ToolPermissionResult.ask("confirm ask", reason="test_ask")


class ExceptionTool(EchoTool):
    name = "explode"

    def call(self, args, context, tool_call_id):
        raise RuntimeError("boom")


class ToolRunnerTest(unittest.TestCase):
    def test_allow_path_executes_tool(self) -> None:
        runner = _runner_with(EchoTool())

        result = runner.run(_call("echo", {"text": "ok"}), _context())

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.tool_call_id, "call_1")

    def test_unknown_tool_returns_structured_error(self) -> None:
        result = ToolRunner(ToolRegistry()).run(_call("missing", {}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Unknown tool: missing")
        self.assertEqual(result.metadata["reason"], "unknown_tool")

    def test_non_object_args_returns_structured_error(self) -> None:
        runner = _runner_with(EchoTool())

        result = runner.run(ToolCall(id="call_1", name="echo", args="bad"), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "invalid_arguments")

    def test_schema_validation_failure_skips_tool_call(self) -> None:
        runner = _runner_with(EchoTool())

        result = runner.run(_call("echo", {"text": 1}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "validation_failed")
        self.assertIn("$.text: expected string", result.content)

    def test_missing_required_argument_returns_structured_error(self) -> None:
        runner = _runner_with(EchoTool())

        result = runner.run(_call("echo", {}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "validation_failed")
        self.assertIn("$.text: missing required property", result.content)

    def test_custom_validation_failure_returns_structured_error(self) -> None:
        runner = _runner_with(CustomValidationTool())

        result = runner.run(_call("custom", {"text": "bad"}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.data["errors"], ["text cannot be bad"])

    def test_deny_permission_returns_structured_error(self) -> None:
        runner = _runner_with(DenyTool())

        result = runner.run(_call("deny", {"text": "ok"}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "blocked")
        self.assertEqual(result.metadata["reason"], "test_deny")

    def test_ask_permission_without_checker_is_denied(self) -> None:
        runner = _runner_with(AskTool())

        result = runner.run(_call("ask", {"text": "ok"}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "permission_checker_missing")

    def test_ask_permission_checker_allows_execution(self) -> None:
        captured: list[ToolPermissionRequest] = []

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            captured.append(request)
            return ToolPermissionResult.allow(updated_args={"text": "updated"}, reason="user_allowed")

        runner = _runner_with(AskTool())
        result = runner.run(_call("ask", {"text": "ok"}), _context(permission_checker=checker))

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "updated")
        self.assertEqual(captured[0].tool_call_id, "call_1")
        self.assertEqual(captured[0].tool_name, "ask")
        self.assertEqual(captured[0].display_name, "Ask")
        self.assertTrue(captured[0].is_destructive)
        self.assertEqual(captured[0].summary, "confirm ask")

    def test_ask_permission_checker_denies_execution(self) -> None:
        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            return ToolPermissionResult.deny("no", reason="user_denied")

        runner = _runner_with(AskTool())
        result = runner.run(_call("ask", {"text": "ok"}), _context(permission_checker=checker))

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "no")
        self.assertEqual(result.metadata["reason"], "user_denied")

    def test_tool_exception_is_converted_to_result(self) -> None:
        runner = _runner_with(ExceptionTool())

        result = runner.run(_call("explode", {"text": "ok"}), _context())

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "tool_exception")
        self.assertIn("boom", result.content)


def _runner_with(*tools: BaseTool) -> ToolRunner:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolRunner(registry)


def _call(name: str, args: object) -> ToolCall:
    return ToolCall(id="call_1", name=name, args=args)


def _context(permission_checker=None) -> ToolContext:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
    return ToolContext(project_root=root, permission_checker=permission_checker)


if __name__ == "__main__":
    unittest.main()
