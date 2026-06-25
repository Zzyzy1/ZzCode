import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zzcode.tools.base import ToolCall, ToolContext, ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.local.powershell import RunPowerShellTool
from zzcode.tools.local.powershell_readonly import classify_read_only_powershell_command
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.runner import ToolRunner


class PowerShellToolTest(unittest.TestCase):
    def test_readonly_classifier_allows_get_date(self) -> None:
        self.assertEqual(
            classify_read_only_powershell_command("Get-Date -Format 'yyyy-MM-dd'"),
            (True, "readonly_powershell_get_date"),
        )

    def test_readonly_classifier_rejects_set_date(self) -> None:
        self.assertEqual(
            classify_read_only_powershell_command("Set-Date -Date '2026-06-24'"),
            (False, "powershell_date_dangerous_command"),
        )

    def test_readonly_classifier_rejects_complex_get_date_pipeline(self) -> None:
        self.assertEqual(
            classify_read_only_powershell_command("Get-Date | Out-File date.txt"),
            (False, "powershell_complex_command"),
        )

    def test_get_date_is_allowed_but_reports_missing_executable(self) -> None:
        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.powershell.shutil.which", return_value=None):
            result = _run(Path(tmp), {"command": "Get-Date -Format 'yyyy-MM-dd'"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "powershell_not_found")

    def test_unknown_powershell_command_requires_permission(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "Write-Output hi"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "permission_checker_missing")

    def test_unknown_powershell_command_runs_after_allow(self) -> None:
        captured: list[ToolPermissionRequest] = []

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            captured.append(request)
            return ToolPermissionResult.allow(reason="test_allow")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.powershell.shutil.which", return_value=None):
            result = _run(Path(tmp), {"command": "Write-Output hi"}, checker)

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "powershell_not_found")
        self.assertEqual(captured[0].tool_name, "run_powershell")
        self.assertEqual(captured[0].summary, "Run PowerShell command: Write-Output hi")
        self.assertTrue(captured[0].is_destructive)

    def test_set_date_is_denied_before_permission_checker(self) -> None:
        called = False

        def checker(request: ToolPermissionRequest) -> ToolPermissionResult:
            nonlocal called
            called = True
            return ToolPermissionResult.allow(reason="should_not_run")

        with TemporaryDirectory() as tmp:
            result = _run(Path(tmp), {"command": "Set-Date -Date '2026-06-24'"}, checker)

        self.assertFalse(result.ok)
        self.assertFalse(called)
        self.assertEqual(result.metadata["reason"], "powershell_date_dangerous_command")


def _run(root: Path, args: dict, permission_checker=None):
    registry = ToolRegistry()
    tool = RunPowerShellTool()
    registry.register(tool)
    context = ToolContext(project_root=root, permission_checker=permission_checker)
    return ToolRunner(registry).run(ToolCall(id="call_1", name=tool.name, args=args), context)


if __name__ == "__main__":
    unittest.main()
