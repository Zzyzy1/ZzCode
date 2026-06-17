"""Structured tool execution pipeline."""

from __future__ import annotations

from typing import Any

from .base import (
    JsonObject,
    ToolCall,
    ToolContext,
    ToolPermissionRequest,
    ToolPermissionResult,
    validate_json_schema,
)
from .registry import ToolRegistry
from .results import ToolResult


class ToolRunner:
    """执行结构化工具调用。

    runner 负责查找、schema 校验、工具自定义校验、权限判断和异常转换。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def run(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        """执行一次工具调用并返回结构化结果。"""

        tool = self.registry.get(tool_call.name)
        if tool is None:
            return ToolResult.failure(
                tool_call.id,
                tool_call.name,
                f"Unknown tool: {tool_call.name}",
                metadata={"reason": "unknown_tool"},
            )

        if not isinstance(tool_call.args, dict):
            return ToolResult.failure(
                tool_call.id,
                tool_call.name,
                "Tool arguments must be a JSON object.",
                metadata={"reason": "invalid_arguments"},
            )

        args: JsonObject = dict(tool_call.args)

        schema_result = validate_json_schema(args, tool.input_schema)
        if not schema_result.ok:
            return self._validation_failure(tool_call, schema_result.errors)

        validation_result = tool.validate_input(args)
        if not validation_result.ok:
            return self._validation_failure(tool_call, validation_result.errors)

        try:
            permission_result = tool.check_permission(args, context)
        except Exception as exc:
            return ToolResult.failure(
                tool_call.id,
                tool_call.name,
                f"Tool permission check failed: {exc}",
                metadata={"reason": "permission_exception"},
            )

        permission_args = permission_result.updated_args or args
        permission_result = self._resolve_permission(
            tool_call=tool_call,
            context=context,
            permission_result=permission_result,
            args=permission_args,
            display_name=tool.display_name or tool.name,
            is_destructive=tool.is_destructive,
            summary=_permission_summary(tool, permission_args, permission_result.message),
            source=getattr(tool, "source", "local"),
            mcp_info=getattr(tool, "mcp_info", None),
        )
        if permission_result.behavior != "allow":
            message = permission_result.message or f"Tool execution denied: {tool_call.name}"
            return ToolResult.failure(
                tool_call.id,
                tool_call.name,
                message,
                metadata={
                    "reason": permission_result.reason or "permission_denied",
                    "permission_behavior": permission_result.behavior,
                },
            )

        call_args = permission_result.updated_args or permission_args
        try:
            return tool.call(call_args, context, tool_call.id)
        except Exception as exc:
            return ToolResult.failure(
                tool_call.id,
                tool_call.name,
                f"Error while running tool '{tool_call.name}': {exc}",
                metadata={"reason": "tool_exception"},
            )

    def _resolve_permission(
        self,
        *,
        tool_call: ToolCall,
        context: ToolContext,
        permission_result: ToolPermissionResult,
        args: JsonObject,
        display_name: str,
        is_destructive: bool,
        summary: str,
        source: str,
        mcp_info: dict[str, Any] | None,
    ) -> ToolPermissionResult:
        if permission_result.behavior in {"allow", "deny"}:
            return permission_result

        if context.permission_checker is None:
            return ToolPermissionResult.deny(
                permission_result.message or f"Tool requires approval: {tool_call.name}",
                reason="permission_checker_missing",
            )

        request = ToolPermissionRequest(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            display_name=display_name,
            args=args,
            summary=summary,
            is_destructive=is_destructive,
            source=source,
            mcp_info=mcp_info,
        )
        try:
            user_result = context.permission_checker(request)
        except Exception as exc:
            return ToolPermissionResult.deny(
                f"Permission checker failed: {exc}",
                reason="permission_checker_exception",
            )

        if user_result.behavior == "allow":
            return user_result
        if user_result.behavior == "deny":
            return user_result
        return ToolPermissionResult.deny(
            user_result.message or f"Tool execution denied: {tool_call.name}",
            reason=user_result.reason or "permission_not_allowed",
        )

    def _validation_failure(self, tool_call: ToolCall, errors: tuple[str, ...]) -> ToolResult:
        message = "Tool argument validation failed."
        if errors:
            message = message + " " + "; ".join(errors)
        return ToolResult.failure(
            tool_call.id,
            tool_call.name,
            message,
            data={"errors": list(errors)},
            metadata={"reason": "validation_failed"},
        )


def _permission_summary(tool: Any, args: JsonObject, fallback: str) -> str:
    if fallback:
        return fallback
    summary = getattr(tool, "permission_summary", None)
    if callable(summary):
        return str(summary(args))
    return f"{tool.name} wants to run with args: {args}"
