import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.tools.base import ToolCall, ToolContext
from zzcode.tools.builtin import build_builtin_tool_registry
from zzcode.tools.local.search import GlobTool, GrepTool
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.runner import ToolRunner


class SearchToolTest(unittest.TestCase):
    def test_builtin_registry_contains_search_tools_before_read_file(self) -> None:
        registry = build_builtin_tool_registry()

        self.assertEqual(
            [tool.name for tool in registry.list()],
            [
                "list_files",
                "glob",
                "grep",
                "read_file",
                "write_file",
                "edit_file",
                "append_file",
                "run_shell",
            ],
        )

    def test_glob_finds_file_inside_project(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests" / "tool_test").mkdir(parents=True)
            (root / "tests" / "tool_test" / "1.txt").write_text("hello", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["tests/tool_test/1.txt"])
        self.assertFalse(result.metadata["truncated"])

    def test_glob_respects_search_root_and_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "1.txt").write_text("a", encoding="utf-8")
            (root / "b" / "1.txt").write_text("b", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt", "path": "a", "limit": 1})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["a/1.txt"])
        self.assertTrue(result.metadata["truncated"])

    def test_glob_rejects_path_outside_project(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(GlobTool(), Path(tmp), {"pattern": "**/*.txt", "path": ".."})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "path_outside_project")

    def test_glob_skips_heavy_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules").mkdir()
            (root / "node_modules" / "1.txt").write_text("skip", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "1.txt").write_text("keep", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["src/1.txt"])

    def test_grep_returns_matching_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.txt").write_text("first\nneedle here\n", encoding="utf-8")
            (root / "src" / "b.py").write_text("needle ignored by include\n", encoding="utf-8")

            result = _run(GrepTool(), root, {"pattern": "needle", "include": "**/*.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], [{"path": "src/a.txt", "line": 2, "text": "needle here"}])
        self.assertIn("src/a.txt:2: needle here", result.content)

    def test_grep_missing_path_returns_structured_error(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(GrepTool(), Path(tmp), {"pattern": "needle", "path": "missing"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "path_not_found")


def _run(tool, root: Path, args: dict):
    registry = ToolRegistry()
    registry.register(tool)
    context = ToolContext(project_root=root)
    return ToolRunner(registry).run(ToolCall(id="call_1", name=tool.name, args=args), context)


if __name__ == "__main__":
    unittest.main()
