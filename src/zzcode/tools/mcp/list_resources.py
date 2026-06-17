"""list_mcp_resources 工具。"""

from __future__ import annotations

from typing import Any, Protocol

from zzcode.mcp import McpConnectionError, format_mcp_resources, normalize_mcp_resources
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolValidationResult
from zzcode.tools.results import ToolResult


class McpResourceLister(Protocol):
    """MCP resource 列表接口，通常由 McpManager 实现。"""

    def list_resources(
        self,
        server_name: str | None = None,
        *,
        use_cache: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """返回按 server 分组的 MCP resource 原始列表。"""


class ListMcpResourcesTool(BaseTool):
    """列出 MCP server 显式暴露的 resources。"""

    name = "list_mcp_resources"
    description = "List resources explicitly exposed by connected MCP servers."
    display_name = "List MCP Resources"
    is_read_only = True
    requires_approval = False
    source = "mcp"
    input_schema = {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "Optional MCP server name. Omit to list all connected resource servers.",
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, lister: McpResourceLister) -> None:
        self.lister = lister

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 MCP resource list 参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        server = args.get("server")
        if server is not None and (not isinstance(server, str) or not server.strip()):
            errors.append("$.server: server cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """调用 MCP resources/list，不访问本地文件系统。"""

        server = args.get("server")
        server_name = server.strip() if isinstance(server, str) else None
        try:
            resources_by_server = self.lister.list_resources(server_name=server_name)
            resources = normalize_mcp_resources(resources_by_server)
        except (McpConnectionError, ValueError) as exc:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                str(exc),
                metadata={"source": "mcp", "reason": "mcp_resource_list_error"},
            )

        return ToolResult.success(
            tool_call_id,
            self.name,
            format_mcp_resources(resources),
            data={"resources": [resource.to_dict() for resource in resources]},
            metadata={"source": "mcp", "server": server_name or ""},
        )

