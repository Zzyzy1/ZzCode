import io
import json
import unittest

from zzcode.protocol.events import JsonLineEventWriter, JsonLineRenderer
from zzcode.protocol.server import PermissionBridge
from zzcode.tools.base import ToolPermissionRequest
from zzcode.ui.messages import ToolResult, ToolUse


class ProtocolToolEventsTest(unittest.TestCase):
    def test_jsonl_renderer_keeps_structured_tool_input_and_id(self) -> None:
        output = io.StringIO()
        renderer = JsonLineRenderer(JsonLineEventWriter(output))

        renderer.render(ToolUse("read_file", {"path": "README.md"}, "Read", id="call_read"))
        renderer.render(ToolResult("read_file", "content", id="call_read", ok=True))

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[0]["type"], "tool_use")
        self.assertEqual(events[0]["id"], "call_read")
        self.assertEqual(events[0]["input"], {"path": "README.md"})
        self.assertEqual(events[1]["type"], "tool_result")
        self.assertEqual(events[1]["id"], "call_read")
        self.assertTrue(events[1]["ok"])

    def test_jsonl_renderer_uses_explicit_tool_result_ok(self) -> None:
        output = io.StringIO()
        renderer = JsonLineRenderer(JsonLineEventWriter(output))

        renderer.render(ToolResult("missing", "Unknown tool: missing", id="call_missing", ok=False))

        event = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(event["type"], "tool_result")
        self.assertEqual(event["id"], "call_missing")
        self.assertFalse(event["ok"])

    def test_permission_bridge_structured_request_allows_once(self) -> None:
        input_stream = io.StringIO('{"type":"permission_response","id":"permission-1","decision":"allow_once"}\n')
        output = io.StringIO()
        bridge = PermissionBridge(input_stream, JsonLineEventWriter(output), session_id="session-test")

        result = bridge.request_structured_permission(
            ToolPermissionRequest(
                tool_call_id="call_write",
                tool_name="write_file",
                display_name="Write",
                args={"path": "notes.md", "content": "hello"},
                summary="Write notes.md",
                is_destructive=True,
            )
        )

        event = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(result.behavior, "allow")
        self.assertEqual(event["type"], "permission_request")
        self.assertEqual(event["toolCallId"], "call_write")
        self.assertEqual(event["input"], {"path": "notes.md", "content": "hello"})
        self.assertEqual(event["summary"], "Write notes.md")
        self.assertTrue(event["isDestructive"])
        self.assertEqual(event["risk"], "medium")
        self.assertEqual(event["preview"]["type"], "write_file_diff")

    def test_permission_bridge_legacy_request_still_returns_bool(self) -> None:
        input_stream = io.StringIO('{"type":"permission_response","id":"permission-1","decision":"deny"}\n')
        output = io.StringIO()
        bridge = PermissionBridge(input_stream, JsonLineEventWriter(output))

        allowed = bridge.request_permission("run_shell", "echo hi", "Shell")

        event = json.loads(output.getvalue().splitlines()[0])
        self.assertFalse(allowed)
        self.assertEqual(event["input"], {"command": "echo hi"})
        self.assertEqual(event["risk"], "high")


if __name__ == "__main__":
    unittest.main()
