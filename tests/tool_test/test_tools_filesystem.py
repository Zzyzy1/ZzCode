import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.tools.base import ToolCall, ToolContext, ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.builtin import build_builtin_tool_registry
from zzcode.tools.local.filesystem import (
    AppendFileTool,
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.runner import ToolRunner


class FilesystemToolTest(unittest.TestCase):
    def test_builtin_registry_contains_file_tools(self) -> None:
        registry = build_builtin_tool_registry()

        tool_names = [tool.name for tool in registry.list()]
        self.assertEqual(tool_names[:7], ["list_files", "glob", "grep", "read_file", "write_file", "edit_file", "append_file"])
        self.assertEqual(registry.get("read_file").display_name, "Read")

    def test_list_files_uses_json_path_arg(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "README.md").write_text("hello", encoding="utf-8")

            result = _run(ListFilesTool(), root, {"path": "."})

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "pkg/\nREADME.md")
        self.assertEqual(result.data["entries"], ["pkg/", "README.md"])

    def test_read_file_reads_utf8_content_with_optional_line_slice(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text("one\ntwo\nthree\n", encoding="utf-8")

            result = _run(ReadFileTool(), root, {"path": "notes.md", "offset": 2, "limit": 1})

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "two\n")
        self.assertEqual(result.metadata["path"], "notes.md")

    def test_write_file_requires_permission_and_writes_after_allow(self) -> None:
        captured: list[ToolPermissionRequest] = []

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            captured.append(request)
            return ToolPermissionResult.allow(reason="test_allow")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _run(
                WriteFileTool(),
                root,
                {"path": "docs/notes.md", "content": "hello"},
                permission_checker=checker,
            )
            written = (root / "docs" / "notes.md").read_text(encoding="utf-8")

        self.assertTrue(result.ok)
        self.assertEqual(written, "hello")
        self.assertEqual(captured[0].tool_name, "write_file")
        self.assertEqual(captured[0].args, {"path": "docs/notes.md", "content": "hello"})
        self.assertTrue(captured[0].is_destructive)

    def test_write_file_is_denied_without_permission_checker(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _run(WriteFileTool(), root, {"path": "notes.md", "content": "hello"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "permission_checker_missing")

    def test_edit_file_replaces_unique_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "README.md"
            target.write_text("old text\n", encoding="utf-8")

            result = _run(
                EditFileTool(),
                root,
                {"path": "README.md", "old_text": "old", "new_text": "new"},
                permission_checker=_allow,
            )
            content = target.read_text(encoding="utf-8")

        self.assertTrue(result.ok)
        self.assertEqual(content, "new text\n")

    def test_edit_file_rejects_ambiguous_old_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("same same", encoding="utf-8")

            result = _run(
                EditFileTool(),
                root,
                {"path": "README.md", "old_text": "same", "new_text": "one"},
                permission_checker=_allow,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "old_text_not_unique")

    def test_append_file_adds_separator_when_needed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "notes.md"
            target.write_text("first", encoding="utf-8")

            result = _run(
                AppendFileTool(),
                root,
                {"path": "notes.md", "content": "second"},
                permission_checker=_allow,
            )
            content = target.read_text(encoding="utf-8")

        self.assertTrue(result.ok)
        self.assertEqual(content, "first\nsecond")

    def test_path_outside_project_is_denied_before_write(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _run(
                WriteFileTool(),
                root,
                {"path": "../outside.txt", "content": "no"},
                permission_checker=_allow,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "path_outside_project")


def _run(tool, root: Path, args: dict, permission_checker=None):
    registry = ToolRegistry()
    registry.register(tool)
    context = ToolContext(project_root=root, permission_checker=permission_checker)
    return ToolRunner(registry).run(ToolCall(id="call_1", name=tool.name, args=args), context)


def _allow(request: ToolPermissionRequest) -> ToolPermissionResult:
    return ToolPermissionResult.allow(reason="test_allow")


if __name__ == "__main__":
    unittest.main()
