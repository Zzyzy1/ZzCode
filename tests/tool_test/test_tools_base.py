import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.tools.base import (
    BaseTool,
    ToolContext,
    ToolPermissionResult,
    validate_json_schema,
)
from zzcode.tools.results import ToolResult


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo text for tests."
    display_name = "Echo"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def call(self, args, context, tool_call_id):
        return ToolResult.success(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=args["text"] * args.get("count", 1),
            data={"project_root": str(context.project_root)},
        )


class DestructiveTool(BaseTool):
    name = "write"
    description = "Fake write tool."
    display_name = "Write"
    requires_approval = True
    is_destructive = True
    input_schema = {"type": "object", "properties": {}, "additionalProperties": True}


class ToolBaseTest(unittest.TestCase):
    def test_fake_tool_validates_and_executes_successfully(self) -> None:
        with TemporaryDirectory() as tmp:
            tool = EchoTool()
            context = ToolContext(project_root=Path(tmp))
            args = {"text": "ha", "count": 2}

            validation = tool.validate_input(args)
            permission = tool.check_permission(args, context)
            result = tool.call(args, context, tool_call_id="call_1")

        self.assertTrue(validation.ok)
        self.assertEqual(permission, ToolPermissionResult.allow(reason="default_allow"))
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "haha")
        self.assertEqual(
            result.to_openai_message(),
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "echo",
                "content": "haha",
            },
        )

    def test_schema_validation_reports_missing_and_unexpected_fields(self) -> None:
        result = validate_json_schema(
            {"extra": True},
            EchoTool.input_schema,
        )

        self.assertFalse(result.ok)
        self.assertIn("$.text: missing required property", result.errors)
        self.assertIn("$.extra: unexpected property", result.errors)

    def test_schema_validation_reports_type_errors(self) -> None:
        result = EchoTool().validate_input({"text": "ok", "count": "two"})

        self.assertFalse(result.ok)
        self.assertEqual(result.errors, ("$.count: expected integer, got string",))

    def test_tool_exports_openai_compatible_schema(self) -> None:
        self.assertEqual(
            EchoTool().to_openai_tool(),
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo text for tests.",
                    "parameters": EchoTool.input_schema,
                },
            },
        )

    def test_requires_approval_defaults_to_ask(self) -> None:
        with TemporaryDirectory() as tmp:
            result = DestructiveTool().check_permission({}, ToolContext(project_root=Path(tmp)))

        self.assertEqual(result.behavior, "ask")
        self.assertEqual(result.reason, "requires_approval")
        self.assertIn("Write", result.message)


if __name__ == "__main__":
    unittest.main()
