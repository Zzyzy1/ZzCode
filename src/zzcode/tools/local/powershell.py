"""Structured local PowerShell tool."""

from __future__ import annotations

import shutil
import subprocess

from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolPermissionResult, ToolValidationResult
from zzcode.tools.local.powershell_readonly import classify_read_only_powershell_command
from zzcode.tools.results import ToolResult


DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300


class RunPowerShellTool(BaseTool):
    name = "run_powershell"
    description = (
        "Run a PowerShell command in the project root. "
        "Use this only for terminal operations via PowerShell such as git, npm, docker, and PS cmdlets. "
        "Prefer dedicated tools for file search, content search, reading, editing, and writing files. "
        "For normal communication, answer directly instead of using Write-Output or Write-Host. "
        "Use Get-Date for local time queries; do not wrap PowerShell commands inside run_shell."
    )
    display_name = "PowerShell"
    is_destructive = True
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "PowerShell command to run, without powershell.exe prefix."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Command timeout in seconds.",
                "default": DEFAULT_TIMEOUT_SECONDS,
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 PowerShell 命令参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        command = args.get("command")
        if isinstance(command, str) and not command.strip():
            errors.append("$.command: command cannot be empty")
        timeout = args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if isinstance(timeout, int) and (timeout < 1 or timeout > MAX_TIMEOUT_SECONDS):
            errors.append(f"$.timeout_seconds: must be between 1 and {MAX_TIMEOUT_SECONDS}")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """按 PowerShell 语义判断只读、危险和需确认命令。"""

        command = str(args.get("command") or "")
        is_readonly, reason = classify_read_only_powershell_command(command)
        if is_readonly:
            return ToolPermissionResult.allow(reason=reason)
        if reason == "powershell_date_dangerous_command":
            return ToolPermissionResult.deny(
                f"命令命中危险日期操作，已拒绝执行: {command}",
                reason=reason,
            )
        return ToolPermissionResult.ask(self.permission_summary(args), reason=reason or "requires_approval")

    def permission_summary(self, args: JsonObject) -> str:
        """生成 PowerShell 权限摘要。"""

        return f"Run PowerShell command: {args.get('command', '')}"

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """在项目根目录执行 PowerShell 命令。"""

        command = args["command"].strip()
        timeout = args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        executable = _resolve_powershell_executable()
        if executable is None:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "未找到 PowerShell 可执行文件: pwsh 或 powershell",
                data={"stdout": "", "stderr": "PowerShell executable not found.", "exit_code": None},
                metadata={"command": command, "timeout_seconds": timeout, "reason": "powershell_not_found"},
            )

        try:
            completed = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=context.project_root,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"命令超时: {timeout} seconds",
                data={"stdout": stdout, "stderr": stderr, "exit_code": None},
                metadata={"command": command, "timeout_seconds": timeout, "reason": "timeout"},
            )
        except OSError as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"命令执行失败: {exc}",
                data={"stdout": "", "stderr": str(exc), "exit_code": None},
                metadata={"command": command, "timeout_seconds": timeout, "reason": "os_error"},
            )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        content = _format_powershell_output(stdout, stderr, completed.returncode)
        return ToolResult.success(
            tool_call_id,
            self.name,
            content,
            data={"stdout": stdout, "stderr": stderr, "exit_code": completed.returncode},
            metadata={"command": command, "timeout_seconds": timeout, "executable": executable},
        )


def _resolve_powershell_executable() -> str | None:
    for candidate in ("pwsh", "powershell"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    return None


def _format_powershell_output(stdout: str, stderr: str, exit_code: int) -> str:
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    parts.append(f"exit_code: {exit_code}")
    return "\n".join(parts)
