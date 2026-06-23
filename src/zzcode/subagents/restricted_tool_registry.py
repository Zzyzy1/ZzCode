"""结构化子 Agent 受限工具注册表。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zzcode.tools.base import JsonObject, Tool, ToolContext, ToolPermissionResult, ToolValidationResult
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult
from zzcode.tools.safety import resolve_project_path


READ_PATH_TOOLS = frozenset({"list_files", "glob", "grep", "read_file"})
WRITE_PATH_TOOLS = frozenset({"write_file", "edit_file", "append_file"})


class RestrictedToolWrapper:
    """包装结构化工具，增加子 Agent 工具名和路径限制。"""

    def __init__(
        self,
        tool: Tool,
        *,
        project_root: Path,
        allow_read_paths: list[Path] | None,
        allow_write_paths: list[Path] | None,
    ) -> None:
        self._tool = tool
        self.project_root = project_root.resolve()
        self.allow_read_paths = _resolve_allowed_paths(self.project_root, allow_read_paths)
        self.allow_write_paths = _resolve_allowed_paths(self.project_root, allow_write_paths or [])

        self.name = tool.name
        self.description = tool.description
        self.input_schema = tool.input_schema
        self.display_name = tool.display_name
        self.is_read_only = tool.is_read_only
        self.is_destructive = tool.is_destructive
        self.requires_approval = tool.requires_approval
        self.source = getattr(tool, "source", "local")
        self.mcp_info = getattr(tool, "mcp_info", None)

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """复用原工具参数校验。"""

        return self._tool.validate_input(args)

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """先执行子 Agent 路径限制，再进入原工具权限判断。"""

        denied = self._validate_tool_input(args)
        if denied:
            return ToolPermissionResult.deny(denied, reason="restricted_tool_denied")
        return self._tool.check_permission(args, context)

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """路径限制通过后调用原工具。"""

        denied = self._validate_tool_input(args)
        if denied:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                denied,
                metadata={"reason": "restricted_tool_denied"},
            )
        return self._tool.call(args, context, tool_call_id)

    def to_openai_tool(self) -> dict[str, Any]:
        """复用原工具 OpenAI-compatible schema。"""

        return self._tool.to_openai_tool()

    def permission_summary(self, args: JsonObject) -> str:
        """复用原工具权限摘要。"""

        summary = getattr(self._tool, "permission_summary", None)
        if callable(summary):
            return str(summary(args))
        return f"{self.display_name or self.name} wants to run with args: {args}"

    def _validate_tool_input(self, args: JsonObject) -> str | None:
        if self.name in READ_PATH_TOOLS:
            return self._validate_path(args, self.allow_read_paths, "read")
        if self.name in WRITE_PATH_TOOLS:
            return self._validate_path(args, self.allow_write_paths, "write")
        return None

    def _validate_path(self, args: JsonObject, allowed_paths: list[Path] | None, kind: str) -> str | None:
        if allowed_paths is None:
            return None
        path_text = str(args.get("path") or ".")
        try:
            path = resolve_project_path(self.project_root, path_text)
        except ValueError as exc:
            return f"Error: restricted tool {kind} path denied for {self.name}: {exc}"
        if not _path_is_allowed(path, allowed_paths):
            return f"Error: restricted tool {kind} path denied for {self.name}: {path}"
        return None


def build_restricted_tool_registry(
    base_registry: ToolRegistry,
    *,
    project_root: Path,
    allow_tools: set[str] | None = None,
    disallowed_tools: set[str] | None = None,
    allow_read_paths: list[Path] | None = None,
    allow_write_paths: list[Path] | None = None,
) -> ToolRegistry:
    """按工具名和路径边界创建子 Agent 专用结构化工具池。"""

    blocked = disallowed_tools or set()
    registry = ToolRegistry()
    for tool in base_registry.list():
        if allow_tools is not None and tool.name not in allow_tools:
            continue
        if tool.name in blocked:
            continue
        registry.register(
            RestrictedToolWrapper(
                tool,
                project_root=project_root,
                allow_read_paths=allow_read_paths,
                allow_write_paths=allow_write_paths,
            )
        )
    return registry


def _resolve_allowed_paths(project_root: Path, paths: list[Path] | None) -> list[Path] | None:
    if paths is None:
        return None
    resolved: list[Path] = []
    for path in paths:
        candidate = path if path.is_absolute() else project_root / path
        resolved.append(candidate.resolve())
    return resolved


def _path_is_allowed(path: Path, allowed_paths: list[Path] | None) -> bool:
    if allowed_paths is None:
        return True
    for allowed in allowed_paths:
        if path == allowed:
            return True
        if _allowed_path_is_directory_root(allowed):
            try:
                path.relative_to(allowed)
            except ValueError:
                continue
            return True
    return False


def _allowed_path_is_directory_root(path: Path) -> bool:
    return path.exists() and path.is_dir()
