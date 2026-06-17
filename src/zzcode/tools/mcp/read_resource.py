"""read_mcp_resource 工具。"""

from __future__ import annotations

from typing import Any, Protocol

from zzcode.mcp import McpConnectionError, format_mcp_read_resource_result
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolValidationResult
from zzcode.tools.results import ToolResult


class McpResourceReader(Protocol):
    """MCP resource 读取接口，通常由 McpManager 实现。"""

    def read_resource(self, server_name: str, uri: str) -> Any:
        """读取指定 MCP server 的 resource。"""


class ReadMcpResourceTool(BaseTool):
    """读取 MCP server 显式暴露的 resource。"""

    name = "read_mcp_resource"
    description = "Read a resource by explicit MCP server name and resource URI."
    display_name = "Read MCP Resource"
    is_read_only = True
    requires_approval = False
    source = "mcp"
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name."},
            "uri": {"type": "string", "description": "Resource URI returned by list_mcp_resources."},
        },
        "required": ["server", "uri"],
        "additionalProperties": False,
    }

    def __init__(self, reader: McpResourceReader) -> None:
        self.reader = reader

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 MCP resource read 参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        for field_name in ("server", "uri"):
            value = args.get(field_name)
            if isinstance(value, str) and not value.strip():
                errors.append(f"$.{field_name}: {field_name} cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """调用 MCP resources/read，不做本地路径猜测或搜索。"""

        server_name = str(args["server"]).strip()
        uri = str(args["uri"]).strip()
        try:
            raw_result = self.reader.read_resource(server_name, uri)
            read_result = format_mcp_read_resource_result(raw_result)
        except (McpConnectionError, ValueError) as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                str(exc),
                metadata={
                    "source": "mcp",
                    "server": server_name,
                    "uri": uri,
                    "reason": "mcp_resource_read_error",
                },
            )

        data = {
            "server": server_name,
            "uri": uri,
            "contents": list(read_result.contents),
        }
        metadata = {"source": "mcp", "server": server_name, "uri": uri}
        if read_result.has_blob:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                "MCP resource contains binary blob content; blob data is not included.",
                content=read_result.content,
                data=data,
                metadata={**metadata, "reason": "mcp_resource_blob_unsupported"},
            )
        return ToolResult.success(
            tool_call_id,
            self.name,
            read_result.content,
            data=data,
            metadata=metadata,
        )
