import unittest

from zzcode.cli.main import build_tool_registry


class CliToolRegistryTest(unittest.TestCase):
    def test_default_cli_tool_registry_uses_structured_tools(self) -> None:
        registry = build_tool_registry()

        names = registry.tool_names_text()
        self.assertIn("read_file", names)
        self.assertIn("run_shell", names)
        self.assertNotIn("Calculator", names)
        self.assertNotIn("agent", names)
        self.assertTrue(registry.to_openai_tools())


if __name__ == "__main__":
    unittest.main()
