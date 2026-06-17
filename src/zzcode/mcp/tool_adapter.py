"""把 MCP tool 定义适配为 ZzCode Tool。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from zzcode.tools.base import BaseTool, JsonObject, ToolContext
from zzcode.tools.results import ToolResult

from .connection import McpConnectionError
from .names import build_mcp_tool_name
from .results import normalize_mcp_tool_result


DEFAULT_MCP_INPUT_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


class McpToolCaller(Protocol):
    """MCP tool 调用接口，通常由 McpManager 实现。"""

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        tool_call_id: str = "",
    ) -> Any:
        """调用 MCP tool 并返回原始 MCP result。"""


@dataclass(frozen=True)
class McpToolInfo:
    """保存 MCP server 返回的原始工具信息。"""

    server_name: str
    tool_name: str
    description: str = ""
    input_schema: JsonObject = field(default_factory=lambda: dict(DEFAULT_MCP_INPUT_SCHEMA))
    annotations: dict[str, Any] = field(default_factory=dict)


class McpToolAdapter(BaseTool):
    """把单个 MCP tool 暴露为 ZzCode 结构化工具。"""

    source = "mcp"
    requires_approval = True

    def __init__(self, info: McpToolInfo, caller: McpToolCaller) -> None:
        self.info = info
        self.caller = caller
        self.name = build_mcp_tool_name(info.server_name, info.tool_name)
        self.description = info.description or f"MCP tool {info.server_name}:{info.tool_name}"
        self.input_schema = _normalize_input_schema(info.input_schema)
        self.display_name = f"{info.server_name}:{info.tool_name}"
        self.mcp_info = {
            "server_name": info.server_name,
            "tool_name": info.tool_name,
        }
        self.is_read_only = bool(info.annotations.get("readOnlyHint"))
        self.is_destructive = bool(info.annotations.get("destructiveHint"))

    def permission_summary(self, args: JsonObject) -> str:
        """生成 MCP tool 权限摘要，展示完整工具名和参数。"""

        return f"{self.name} wants to run with args: {args}"

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """调用 MCP server 并转换结果。"""

        try:
            raw_result = self.caller.call_tool(
                self.info.server_name,
                self.info.tool_name,
                args,
                tool_call_id=tool_call_id,
            )
        except McpConnectionError as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                str(exc),
                metadata={
                    "source": "mcp",
                    "server_name": self.info.server_name,
                    "tool_name": self.info.tool_name,
                    "reason": "mcp_error",
                },
            )

        normalized = normalize_mcp_tool_result(
            raw_result,
            server_name=self.info.server_name,
            tool_name=self.info.tool_name,
        )
        if normalized.ok:
            return ToolResult.success(
                tool_call_id,
                self.name,
                normalized.content,
                data=normalized.data,
                metadata=normalized.metadata,
            )
        return ToolResult.failure(
            tool_call_id,
            self.name,
            normalized.content,
            data=normalized.data,
            metadata={**normalized.metadata, "reason": "mcp_tool_error"},
        )


def build_mcp_tools(
    caller: McpToolCaller,
    tools_by_server: dict[str, list[dict[str, Any]]],
) -> list[McpToolAdapter]:
    """把 tools/list 原始结果转换为 MCP Tool adapter 列表。"""

    tools: list[McpToolAdapter] = []
    for server_name in sorted(tools_by_server):
        for raw_tool in tools_by_server[server_name]:
            tools.append(McpToolAdapter(from_mcp_tool_definition(server_name, raw_tool), caller))
    return tools


def from_mcp_tool_definition(server_name: str, raw_tool: dict[str, Any]) -> McpToolInfo:
    """解析 MCP tools/list 中的单个 tool 定义。"""

    tool_name = raw_tool.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError(f"Invalid MCP tool from server '{server_name}': missing non-empty name.")

    description = raw_tool.get("description", "")
    input_schema = raw_tool.get("inputSchema") or raw_tool.get("input_schema") or DEFAULT_MCP_INPUT_SCHEMA
    annotations = raw_tool.get("annotations", {})
    return McpToolInfo(
        server_name=server_name,
        tool_name=tool_name.strip(),
        description=description if isinstance(description, str) else "",
        input_schema=_normalize_input_schema(input_schema),
        annotations=annotations if isinstance(annotations, dict) else {},
    )


def format_mcp_tool_result(raw_result: Any) -> str:
    """把 MCP tool result 转成可回灌模型的文本。"""

    return normalize_mcp_tool_result(raw_result, server_name="", tool_name="").content


def _normalize_input_schema(value: Any) -> JsonObject:
    if not isinstance(value, dict):
        return dict(DEFAULT_MCP_INPUT_SCHEMA)
    schema = dict(value)
    if schema.get("type") != "object":
        schema["type"] = "object"
    schema.setdefault("properties", {})
    schema.setdefault("additionalProperties", True)
    return schema

