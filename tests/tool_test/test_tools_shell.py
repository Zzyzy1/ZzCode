import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.tools.base import ToolCall, ToolContext, ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.builtin import build_builtin_tool_registry
from zzcode.tools.local.shell import RunShellTool
from zzcode.tools.local.shell_readonly import classify_read_only_shell_command
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.runner import ToolRunner


class ShellToolTest(unittest.TestCase):
    def test_builtin_registry_contains_shell_tool(self) -> None:
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
                "run_powershell",
                "web_search",
                "web_fetch",
            ],
        )
        self.assertEqual(registry.get("run_shell").display_name, "Shell")
        self.assertEqual(registry.get("run_powershell").display_name, "PowerShell")

    def test_shell_command_requires_permission(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "printf hi"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "permission_checker_missing")

    def test_readonly_shell_command_runs_without_permission_checker(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "pwd"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["exit_code"], 0)
        self.assertIn("exit_code: 0", result.content)

    def test_shell_command_runs_after_allow(self) -> None:
        captured: list[ToolPermissionRequest] = []

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            captured.append(request)
            return ToolPermissionResult.allow(reason="test_allow")

        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "printf hi", "timeout_seconds": 5}, checker)

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "hi\nexit_code: 0")
        self.assertEqual(result.data["stdout"], "hi")
        self.assertEqual(result.data["stderr"], "")
        self.assertEqual(result.data["exit_code"], 0)
        self.assertEqual(captured[0].tool_name, "run_shell")
        self.assertEqual(captured[0].summary, "Run shell command: printf hi")
        self.assertTrue(captured[0].is_destructive)

    def test_shell_command_preserves_stderr_and_exit_code(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(
                Path(tmp),
                {"command": "python3 -c 'import sys; print(\"err\", file=sys.stderr); sys.exit(7)'"},
                _allow,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["stderr"], "err")
        self.assertEqual(result.data["exit_code"], 7)
        self.assertIn("stderr:\nerr", result.content)
        self.assertIn("exit_code: 7", result.content)

    def test_dangerous_command_is_denied_before_permission_checker(self) -> None:
        called = False

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            nonlocal called
            called = True
            return ToolPermissionResult.allow(reason="should_not_run")

        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "sudo echo hi"}, checker)

        self.assertFalse(result.ok)
        self.assertFalse(called)
        self.assertEqual(result.metadata["reason"], "dangerous_command")

    def test_date_set_command_is_denied_before_permission_checker(self) -> None:
        called = False

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            nonlocal called
            called = True
            return ToolPermissionResult.allow(reason="should_not_run")

        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "date -s 2026-06-24"}, checker)

        self.assertFalse(result.ok)
        self.assertFalse(called)
        self.assertEqual(result.metadata["reason"], "date_dangerous_flag")

    def test_timeout_returns_structured_error(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(
                Path(tmp),
                {"command": "python3 -c 'import time; time.sleep(2)'", "timeout_seconds": 1},
                _allow,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "timeout")
        self.assertEqual(result.metadata["timeout_seconds"], 1)
        self.assertIsNone(result.data["exit_code"])

    def test_timeout_validation_rejects_invalid_value(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "printf hi", "timeout_seconds": 0}, _allow)

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "validation_failed")
        self.assertIn("$.timeout_seconds: must be between", result.content)

    def test_readonly_classifier_allows_safe_date(self) -> None:
        self.assertEqual(classify_read_only_shell_command("date +%Y-%m-%d"), (True, "readonly_date"))

    def test_readonly_classifier_rejects_date_set(self) -> None:
        self.assertEqual(
            classify_read_only_shell_command("date -s 2026-06-24"),
            (False, "date_dangerous_flag"),
        )

    def test_shell_rejects_powershell_wrapper(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "powershell -Command \"Get-Date\""}, _allow)

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "use_powershell_tool")


def _run(root: Path, args: dict, permission_checker=None):
    registry = ToolRegistry()
    tool = RunShellTool()
    registry.register(tool)
    context = ToolContext(project_root=root, permission_checker=permission_checker)
    return ToolRunner(registry).run(ToolCall(id="call_1", name=tool.name, args=args), context)


def _allow(request: ToolPermissionRequest) -> ToolPermissionResult:
    return ToolPermissionResult.allow(reason="test_allow")


if __name__ == "__main__":
    unittest.main()
