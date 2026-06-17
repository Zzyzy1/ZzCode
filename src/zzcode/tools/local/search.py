"""Structured local search tools."""

from __future__ import annotations

from collections.abc import Iterator
import fnmatch
from pathlib import Path
from typing import Any

from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolPermissionResult, ToolValidationResult
from zzcode.tools.results import ToolResult
from zzcode.tools.safety import resolve_project_path


DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_SCANNED_ENTRIES = 10000
MAX_GREP_FILE_BYTES = 512 * 1024
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
}


class SearchToolMixin:
    """提供项目内搜索工具共用校验和边界。"""

    is_read_only = True
    requires_approval = False

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验搜索参数。"""

        result = super().validate_input(args)  # type: ignore[misc]
        errors = list(result.errors)
        path = args.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            errors.append("$.path: path cannot be empty")
        limit = args.get("limit", DEFAULT_LIMIT)
        if isinstance(limit, int) and (limit < 1 or limit > MAX_LIMIT):
            errors.append(f"$.limit: must be between 1 and {MAX_LIMIT}")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """只允许搜索项目根目录内路径。"""

        try:
            resolve_project_path(context.project_root, str(args.get("path") or "."))
        except ValueError as exc:
            return ToolPermissionResult.deny(str(exc), reason="path_outside_project")
        return ToolPermissionResult.allow(reason="read_only")


class GlobTool(SearchToolMixin, BaseTool):
    name = "glob"
    description = (
        "Find project files by path pattern. Use this when the user gives a file name, "
        "partial path, or wildcard and the exact path is unknown."
    )
    display_name = "Glob"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern such as **/README.md."},
            "path": {"type": "string", "description": "Search root inside the project.", "default": "."},
            "limit": {"type": "integer", "description": "Maximum number of matches.", "default": DEFAULT_LIMIT},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 glob 参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        pattern = args.get("pattern")
        if isinstance(pattern, str) and not pattern.strip():
            errors.append("$.pattern: pattern cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """在项目内按 glob pattern 查找路径。"""

        search_root = resolve_project_path(context.project_root, str(args.get("path") or "."))
        rel_root = _relative_path(context.project_root, search_root)
        if not search_root.exists():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"搜索路径不存在: {rel_root}",
                metadata={"path": rel_root, "reason": "path_not_found"},
            )
        if not search_root.is_dir():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"搜索路径不是目录: {rel_root}",
                metadata={"path": rel_root, "reason": "not_directory"},
            )

        pattern = str(args["pattern"]).strip()
        limit = int(args.get("limit", DEFAULT_LIMIT))
        matches: list[str] = []
        scanned = 0
        truncated = False
        for item in _walk_project(search_root):
            scanned += 1
            if scanned > MAX_SCANNED_ENTRIES:
                truncated = True
                break
            rel = _relative_path(context.project_root, item)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(item.name, pattern):
                matches.append(rel)
                if len(matches) >= limit:
                    truncated = True
                    break

        content = "\n".join(matches) if matches else "(no matches)"
        if truncated:
            content = content + "\n(results truncated)"
        return ToolResult.success(
            tool_call_id,
            self.name,
            content,
            data={"matches": matches},
            metadata={"path": rel_root, "pattern": pattern, "scanned": scanned, "truncated": truncated},
        )


class GrepTool(SearchToolMixin, BaseTool):
    name = "grep"
    description = "Search text content in project files. Use this when locating files by content or symbol."
    display_name = "Grep"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Plain text pattern to search for."},
            "path": {"type": "string", "description": "Search root inside the project.", "default": "."},
            "include": {"type": "string", "description": "File glob filter such as *.py or **/*.txt."},
            "limit": {"type": "integer", "description": "Maximum number of matches.", "default": DEFAULT_LIMIT},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 grep 参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        pattern = args.get("pattern")
        if isinstance(pattern, str) and not pattern:
            errors.append("$.pattern: pattern cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """在项目内搜索文本内容。"""

        search_root = resolve_project_path(context.project_root, str(args.get("path") or "."))
        rel_root = _relative_path(context.project_root, search_root)
        if not search_root.exists():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"搜索路径不存在: {rel_root}",
                metadata={"path": rel_root, "reason": "path_not_found"},
            )
        if not search_root.is_dir():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"搜索路径不是目录: {rel_root}",
                metadata={"path": rel_root, "reason": "not_directory"},
            )

        pattern = str(args["pattern"])
        include = args.get("include")
        limit = int(args.get("limit", DEFAULT_LIMIT))
        matches: list[dict[str, Any]] = []
        scanned = 0
        truncated = False
        for item in _walk_project(search_root):
            scanned += 1
            if scanned > MAX_SCANNED_ENTRIES:
                truncated = True
                break
            if not item.is_file() or not _matches_include(context.project_root, item, include):
                continue
            if item.stat().st_size > MAX_GREP_FILE_BYTES:
                continue
            try:
                lines = item.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = _relative_path(context.project_root, item)
            for line_number, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append({"path": rel, "line": line_number, "text": line.strip()})
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break

        content_lines = [f"{match['path']}:{match['line']}: {match['text']}" for match in matches]
        content = "\n".join(content_lines) if content_lines else "(no matches)"
        if truncated:
            content = content + "\n(results truncated)"
        return ToolResult.success(
            tool_call_id,
            self.name,
            content,
            data={"matches": matches},
            metadata={"path": rel_root, "pattern": pattern, "scanned": scanned, "truncated": truncated},
        )


def _walk_project(search_root: Path) -> Iterator[Path]:
    stack = [search_root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in SKIP_DIR_NAMES:
                    continue
                stack.append(child)
            else:
                yield child


def _matches_include(project_root: Path, path: Path, include: object) -> bool:
    if not include:
        return True
    if not isinstance(include, str):
        return True
    rel = _relative_path(project_root, path)
    return fnmatch.fnmatch(rel, include) or fnmatch.fnmatch(path.name, include)


def _relative_path(project_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))
