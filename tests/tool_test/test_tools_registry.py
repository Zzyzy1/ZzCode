import unittest

from zzcode.tools.base import BaseTool
from zzcode.tools.registry import ToolRegistry


class FirstTool(BaseTool):
    name = "first"
    description = "First test tool."
    display_name = "First"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }


class SecondTool(BaseTool):
    name = "second"
    description = "Second test tool."
    display_name = "Second"
    input_schema = {"type": "object", "properties": {}, "additionalProperties": True}


class EmptyNameTool(BaseTool):
    name = ""
    description = "Invalid test tool."


class ToolRegistryTest(unittest.TestCase):
    def test_register_and_get_tool(self) -> None:
        registry = ToolRegistry()
        tool = FirstTool()

        registry.register(tool)

        self.assertEqual(len(registry), 1)
        self.assertIn("first", registry)
        self.assertIs(registry.get("first"), tool)
        self.assertIsNone(registry.get("missing"))

    def test_list_preserves_registration_order(self) -> None:
        registry = ToolRegistry()
        first = FirstTool()
        second = SecondTool()

        registry.register(first)
        registry.register(second)

        self.assertEqual(registry.list(), [first, second])

    def test_to_openai_tools_uses_tool_schema(self) -> None:
        registry = ToolRegistry()
        registry.register(FirstTool())
        registry.register(SecondTool())

        self.assertEqual(
            registry.to_openai_tools(),
            [
                FirstTool().to_openai_tool(),
                SecondTool().to_openai_tool(),
            ],
        )

    def test_duplicate_tool_name_is_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(FirstTool())

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(FirstTool())

    def test_empty_tool_name_is_rejected(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            registry.register(EmptyNameTool())


if __name__ == "__main__":
    unittest.main()
