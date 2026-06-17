"""Structured local shell tool."""

from __future__ import annotations

import subprocess

from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolPermissionResult, ToolValidationResult
from zzcode.tools.results import ToolResult
from zzcode.tools.safety import reject_dangerous_command


DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300


class RunShellTool(BaseTool):
    name = "run_shell"
    description = "Run a shell command in the project root."
    display_name = "Shell"
    is_destructive = True
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
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
        """校验 shell 命令参数。"""

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
        """先拒绝危险命令，再请求用户确认。"""

        command = str(args.get("command") or "")
        try:
            reject_dangerous_command(command)
        except ValueError as exc:
            return ToolPermissionResult.deny(str(exc), reason="dangerous_command")
        return ToolPermissionResult.ask(self.permission_summary(args), reason="requires_approval")

    def permission_summary(self, args: JsonObject) -> str:
        """生成 shell 权限摘要。"""

        return f"Run shell command: {args.get('command', '')}"

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """在项目根目录执行 shell 命令。"""

        command = args["command"].strip()
        timeout = args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        try:
            completed = subprocess.run(
                command,
                cwd=context.project_root,
                shell=True,
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
        content = _format_shell_output(stdout, stderr, completed.returncode)
        return ToolResult.success(
            tool_call_id,
            self.name,
            content,
            data={"stdout": stdout, "stderr": stderr, "exit_code": completed.returncode},
            metadata={"command": command, "timeout_seconds": timeout},
        )


def _format_shell_output(stdout: str, stderr: str, exit_code: int) -> str:
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    parts.append(f"exit_code: {exit_code}")
    return "\n".join(parts)
