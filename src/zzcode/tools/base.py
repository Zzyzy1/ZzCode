"""Structured tool core types."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from .results import ToolResult


JsonObject = dict[str, Any]
PermissionBehavior = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class ToolValidationResult:
    """表示工具参数校验结果。"""

    ok: bool
    errors: tuple[str, ...] = ()

    @classmethod
    def success(cls) -> "ToolValidationResult":
        """构造成功校验结果。"""

        return cls(ok=True)

    @classmethod
    def failure(cls, *errors: str) -> "ToolValidationResult":
        """构造失败校验结果。"""

        return cls(ok=False, errors=tuple(error for error in errors if error))

    def merge(self, other: "ToolValidationResult") -> "ToolValidationResult":
        """合并两个校验结果。"""

        if self.ok and other.ok:
            return ToolValidationResult.success()
        return ToolValidationResult.failure(*self.errors, *other.errors)


@dataclass(frozen=True)
class ToolPermissionResult:
    """表示工具权限判断结果。"""

    behavior: PermissionBehavior
    message: str = ""
    reason: str = ""
    updated_args: JsonObject | None = None

    @classmethod
    def allow(
        cls, message: str = "", *, reason: str = "", updated_args: JsonObject | None = None
    ) -> "ToolPermissionResult":
        """允许工具执行。"""

        return cls("allow", message=message, reason=reason, updated_args=updated_args)

    @classmethod
    def deny(cls, message: str, *, reason: str = "") -> "ToolPermissionResult":
        """拒绝工具执行。"""

        return cls("deny", message=message, reason=reason)

    @classmethod
    def ask(cls, message: str, *, reason: str = "") -> "ToolPermissionResult":
        """请求用户确认。"""

        return cls("ask", message=message, reason=reason)


@dataclass(frozen=True)
class ToolPermissionRequest:
    """发送给权限确认层的结构化请求。"""

    tool_call_id: str
    tool_name: str
    display_name: str
    args: JsonObject
    summary: str
    is_destructive: bool
    source: str = "local"
    mcp_info: dict[str, Any] | None = None


PermissionChecker = Callable[[ToolPermissionRequest], ToolPermissionResult]


@dataclass(frozen=True)
class ToolContext:
    """工具执行时可访问的运行环境。

    project_root 是工具操作边界；permission_checker 用于桥接 CLI 或 JSONL 前端确认。
    """

    project_root: Path
    session_id: str = ""
    permission_checker: PermissionChecker | None = None
    session_context: dict[str, Any] = field(default_factory=dict)
    abort_signal: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    """模型返回的一次结构化工具调用。"""

    id: str
    name: str
    args: JsonObject
    raw: Any | None = None


@runtime_checkable
class Tool(Protocol):
    """结构化工具协议。"""

    name: str
    description: str
    input_schema: JsonObject
    display_name: str
    is_read_only: bool
    is_destructive: bool
    requires_approval: bool
    source: str
    mcp_info: dict[str, Any] | None

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验工具参数。"""

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """判断工具执行权限。"""

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """执行工具。"""

    def to_openai_tool(self) -> dict[str, Any]:
        """生成 OpenAI-compatible tools schema。"""


class BaseTool:
    """提供结构化工具的默认行为。"""

    name = ""
    description = ""
    input_schema: JsonObject = {"type": "object", "properties": {}}
    display_name = ""
    is_read_only = False
    is_destructive = False
    requires_approval = False
    is_concurrency_safe = False
    source = "local"
    mcp_info: dict[str, Any] | None = None

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """用工具 schema 校验参数。"""

        return validate_json_schema(args, self.input_schema)

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """返回工具默认权限行为。"""

        if self.requires_approval:
            return ToolPermissionResult.ask(self.permission_summary(args), reason="requires_approval")
        return ToolPermissionResult.allow(reason="default_allow")

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """执行工具，子类必须覆盖。"""

        raise NotImplementedError(f"Tool '{self.name}' does not implement call().")

    def to_openai_tool(self) -> dict[str, Any]:
        """生成 OpenAI-compatible tools schema。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def permission_summary(self, args: JsonObject) -> str:
        """生成人类可读的权限摘要。"""

        label = self.display_name or self.name
        return f"{label} wants to run with args: {args}"


def validate_json_schema(value: Any, schema: Mapping[str, Any]) -> ToolValidationResult:
    """校验本阶段工具参数使用的 JSON Schema 子集。

    支持 type、required、properties、additionalProperties 和 enum。
    """

    errors = _validate_json_schema(value, schema, "$")
    if errors:
        return ToolValidationResult.failure(*errors)
    return ToolValidationResult.success()


def _validate_json_schema(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type is not None:
        allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
        if not any(_matches_json_type(value, allowed_type) for allowed_type in allowed_types):
            expected = " or ".join(str(item) for item in allowed_types)
            errors.append(f"{path}: expected {expected}, got {_json_type_name(value)}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}, got {value!r}")

    if schema_type == "object" or isinstance(value, dict):
        if not isinstance(value, dict):
            return errors

        required = schema.get("required", ())
        for field_name in required:
            if field_name not in value:
                errors.append(f"{path}.{field_name}: missing required property")

        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for field_name, field_schema in properties.items():
                if field_name in value and isinstance(field_schema, Mapping):
                    errors.extend(
                        _validate_json_schema(value[field_name], field_schema, f"{path}.{field_name}")
                    )

        # 当前阶段只需要布尔值 additionalProperties；复杂 schema 后续再扩展。
        if schema.get("additionalProperties") is False and isinstance(properties, Mapping):
            allowed = set(properties)
            for field_name in value:
                if field_name not in allowed:
                    errors.append(f"{path}.{field_name}: unexpected property")

    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_validate_json_schema(item, item_schema, f"{path}[{index}]"))

    return errors


def _matches_json_type(value: Any, schema_type: Any) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True


def _json_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__
