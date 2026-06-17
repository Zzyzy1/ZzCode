"""MCP tools/resources 发现逻辑。"""

from __future__ import annotations

from typing import Any

from .connection import McpConnection, McpConnectionError, model_to_dict


def fetch_tools_for_connection(connection: McpConnection) -> list[dict[str, Any]]:
    """从 connected server 读取 tools/list。"""

    if not connection.is_connected or not _supports_capability(connection.capabilities, "tools"):
        return []
    try:
        result = connection.list_tools()
    except McpConnectionError:
        raise
    return _extract_object_list(result, "tools", connection.name)


def fetch_resources_for_connection(connection: McpConnection) -> list[dict[str, Any]]:
    """从 connected server 读取 resources/list。"""

    if not connection.is_connected or not _supports_capability(connection.capabilities, "resources"):
        return []
    try:
        result = connection.list_resources()
    except McpConnectionError:
        raise
    return _extract_object_list(result, "resources", connection.name)


def _supports_capability(capabilities: dict[str, Any], name: str) -> bool:
    return isinstance(capabilities.get(name), dict)


def _extract_object_list(result: Any, field_name: str, server_name: str) -> list[dict[str, Any]]:
    raw = model_to_dict(result)
    raw_items = raw.get(field_name, [])
    if not isinstance(raw_items, list):
        raise McpConnectionError(
            f"Invalid MCP {field_name}/list response from '{server_name}': "
            f"'{field_name}' must be a list."
        )
    items: list[dict[str, Any]] = []
    for item in raw_items:
        item_dict = model_to_dict(item)
        if not item_dict:
            raise McpConnectionError(
                f"Invalid MCP {field_name}/list response from '{server_name}': "
                f"items must be objects."
            )
        items.append(item_dict)
    return items
