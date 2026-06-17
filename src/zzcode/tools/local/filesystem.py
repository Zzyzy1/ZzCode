"""Structured local filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zzcode.tools.base import (
    BaseTool,
    JsonObject,
    ToolContext,
    ToolPermissionResult,
    ToolValidationResult,
)
from zzcode.tools.results import ToolResult
from zzcode.tools.safety import resolve_project_path


MAX_READ_BYTES = 100 * 1024


def _path_schema(default: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": "Path inside the project."}
    if default is not None:
        schema["default"] = default
    return schema


class FileToolMixin:
    """提供文件工具共用的路径权限检查。"""

    requires_approval = False

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """先做路径围栏检查，再应用默认权限策略。"""

        path_text = str(args.get("path") or ".")
        try:
            resolve_project_path(context.project_root, path_text)
        except ValueError as exc:
            return ToolPermissionResult.deny(str(exc), reason="path_outside_project")

        if self.requires_approval:
            return ToolPermissionResult.ask(self.permission_summary(args), reason="requires_approval")
        return ToolPermissionResult.allow(reason="read_only")

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 path 不为空。"""

        base_result = super().validate_input(args)  # type: ignore[misc]
        errors = list(base_result.errors)
        path = args.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            errors.append("$.path: path cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def _resolve_path(self, context: ToolContext, args: JsonObject) -> Path:
        return resolve_project_path(context.project_root, str(args.get("path") or "."))

    def _relative_path(self, context: ToolContext, path: Path) -> str:
        return str(path.relative_to(context.project_root.resolve()))


class ListFilesTool(FileToolMixin, BaseTool):
    name = "list_files"
    description = "List files in a project directory."
    display_name = "List"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {"path": _path_schema(".")},
        "additionalProperties": False,
    }

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """列出项目内目录内容。"""

        path = self._resolve_path(context, args)
        rel_path = self._relative_path(context, path)
        if not path.exists():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"路径不存在: {rel_path}",
                metadata={"path": rel_path, "reason": "path_not_found"},
            )
        if not path.is_dir():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"不是目录: {rel_path}",
                metadata={"path": rel_path, "reason": "not_directory"},
            )

        entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        lines = [f"{entry.name}{'/' if entry.is_dir() else ''}" for entry in entries]
        content = "\n".join(lines) if lines else "(empty)"
        return ToolResult.success(
            tool_call_id,
            self.name,
            content,
            data={"entries": lines},
            metadata={"path": rel_path},
        )


class ReadFileTool(FileToolMixin, BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file in the project when the exact path is known."
    display_name = "Read"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": _path_schema(),
            "offset": {"type": "integer", "description": "1-based line offset."},
            "limit": {"type": "integer", "description": "Maximum number of lines."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验读取参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        for field_name in ("offset", "limit"):
            if field_name in args and isinstance(args[field_name], int) and args[field_name] < 1:
                errors.append(f"$.{field_name}: must be >= 1")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """读取项目内 UTF-8 文本文件。"""

        path = self._resolve_path(context, args)
        rel_path = self._relative_path(context, path)
        if not path.exists():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"文件不存在: {rel_path}。如果用户提供的是文件名或部分路径，可以使用 glob 搜索匹配文件。",
                metadata={"path": rel_path, "reason": "path_not_found"},
            )
        if not path.is_file():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"不是文件: {rel_path}",
                metadata={"path": rel_path, "reason": "not_file"},
            )

        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"文件过大，拒绝读取: {size} bytes > {MAX_READ_BYTES} bytes",
                metadata={"path": rel_path, "size": size, "reason": "file_too_large"},
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "文件不是 UTF-8 文本，当前 read_file 暂不支持。",
                metadata={"path": rel_path, "reason": "not_utf8"},
            )

        selected = _slice_lines(content, args.get("offset"), args.get("limit"))
        return ToolResult.success(
            tool_call_id,
            self.name,
            selected,
            data={"path": rel_path, "content": selected},
            metadata={"path": rel_path, "size": size},
        )


class WriteFileTool(FileToolMixin, BaseTool):
    name = "write_file"
    description = "Create or replace a UTF-8 text file at an exact project path."
    display_name = "Write"
    is_destructive = True
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": _path_schema(),
            "content": {"type": "string", "description": "File content."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """写入项目内文本文件。"""

        path = self._resolve_path(context, args)
        rel_path = self._relative_path(context, path)
        content = args["content"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"写入失败: {exc}",
                metadata={"path": rel_path, "reason": "write_failed"},
            )
        return ToolResult.success(
            tool_call_id,
            self.name,
            f"Wrote {rel_path} ({len(content)} chars)",
            data={"path": rel_path, "chars": len(content)},
            metadata={"path": rel_path},
        )


class EditFileTool(FileToolMixin, BaseTool):
    name = "edit_file"
    description = "Replace one exact text range in a project file."
    display_name = "Edit"
    is_destructive = True
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": _path_schema(),
            "old_text": {"type": "string", "description": "Existing exact text."},
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验替换参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        if isinstance(args.get("old_text"), str) and not args["old_text"]:
            errors.append("$.old_text: old_text cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """替换项目内文本文件的一段内容。"""

        path = self._resolve_path(context, args)
        rel_path = self._relative_path(context, path)
        if not path.exists():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"文件不存在: {rel_path}",
                metadata={"path": rel_path, "reason": "path_not_found"},
            )
        if not path.is_file():
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"不是文件: {rel_path}",
                metadata={"path": rel_path, "reason": "not_file"},
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "文件不是 UTF-8 文本，当前 edit_file 暂不支持。",
                metadata={"path": rel_path, "reason": "not_utf8"},
            )

        old_text = args["old_text"]
        new_text = args["new_text"]
        count = content.count(old_text)
        if count == 0:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "替换失败: old_text 未在文件中找到。",
                metadata={"path": rel_path, "reason": "old_text_not_found"},
            )
        if count > 1:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"替换失败: old_text 出现 {count} 次，请提供更精确的上下文。",
                metadata={"path": rel_path, "reason": "old_text_not_unique", "count": count},
            )

        updated = content.replace(old_text, new_text, 1)
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"写入失败: {exc}",
                metadata={"path": rel_path, "reason": "write_failed"},
            )
        return ToolResult.success(
            tool_call_id,
            self.name,
            f"Edited {rel_path} ({len(old_text)} -> {len(new_text)} chars)",
            data={"path": rel_path, "old_chars": len(old_text), "new_chars": len(new_text)},
            metadata={"path": rel_path},
        )


class AppendFileTool(FileToolMixin, BaseTool):
    name = "append_file"
    description = "Append UTF-8 text to a project file."
    display_name = "Append"
    is_destructive = True
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": _path_schema(),
            "content": {"type": "string", "description": "Content to append."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """追加内容到项目内文本文件末尾。"""

        path = self._resolve_path(context, args)
        rel_path = self._relative_path(context, path)
        content = args["content"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = ""
            if path.exists():
                if not path.is_file():
                    return ToolResult.failure(
                        tool_call_id,
                        self.name,
                        f"不是文件: {rel_path}",
                        metadata={"path": rel_path, "reason": "not_file"},
                    )
                existing = path.read_text(encoding="utf-8")
            separator = "\n" if existing and not existing.endswith("\n") and content else ""
            path.write_text(existing + separator + content, encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "文件不是 UTF-8 文本，当前 append_file 暂不支持。",
                metadata={"path": rel_path, "reason": "not_utf8"},
            )
        except OSError as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"追加失败: {exc}",
                metadata={"path": rel_path, "reason": "append_failed"},
            )
        return ToolResult.success(
            tool_call_id,
            self.name,
            f"Appended {rel_path} ({len(content)} chars)",
            data={"path": rel_path, "chars": len(content)},
            metadata={"path": rel_path},
        )


def _slice_lines(content: str, offset: Any, limit: Any) -> str:
    if offset is None and limit is None:
        return content

    lines = content.splitlines(keepends=True)
    start = offset - 1 if isinstance(offset, int) else 0
    end = start + limit if isinstance(limit, int) else None
    return "".join(lines[start:end])
