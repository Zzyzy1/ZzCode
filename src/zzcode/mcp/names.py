"""MCP 工具命名辅助函数。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


MCP_TOOL_PREFIX = "mcp__"
MCP_NAME_SEPARATOR = "__"
_INVALID_MCP_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]+")
_REPEATED_UNDERSCORES = re.compile(r"_+")


@dataclass(frozen=True)
class McpToolName:
    """表示解析后的 MCP 完整工具名。"""

    server_name: str
    tool_name: str


def normalize_mcp_name(value: str) -> str:
    """把 MCP server/tool 名规范化为工具名片段。"""

    normalized = _INVALID_MCP_NAME_CHARS.sub("_", value.strip())
    normalized = _REPEATED_UNDERSCORES.sub("_", normalized).strip("_")
    if not normalized:
        raise ValueError("MCP name cannot be empty after normalization.")
    return normalized


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """构造模型可调用的 MCP 完整工具名。"""

    return (
        f"{MCP_TOOL_PREFIX}"
        f"{normalize_mcp_name(server_name)}"
        f"{MCP_NAME_SEPARATOR}"
        f"{normalize_mcp_name(tool_name)}"
    )


def parse_mcp_tool_name(name: str) -> McpToolName | None:
    """解析 MCP 完整工具名，非 MCP 名称返回 None。"""

    if not name.startswith(MCP_TOOL_PREFIX):
        return None
    remainder = name[len(MCP_TOOL_PREFIX) :]
    server_name, separator, tool_name = remainder.partition(MCP_NAME_SEPARATOR)
    if separator != MCP_NAME_SEPARATOR or not server_name or not tool_name:
        return None
    if MCP_NAME_SEPARATOR in tool_name:
        return None
    return McpToolName(server_name=server_name, tool_name=tool_name)


def get_mcp_prefix(server_name: str) -> str:
    """返回某个 server 的 MCP 工具名前缀。"""

    return f"{MCP_TOOL_PREFIX}{normalize_mcp_name(server_name)}{MCP_NAME_SEPARATOR}"


def get_mcp_permission_name(tool: Any) -> str:
    """返回权限系统应使用的 MCP 完整工具身份。

    对 MCP tool 返回完整 name；非 MCP tool 保持本地工具名，避免权限规则混用。
    """

    name = getattr(tool, "name", "")
    if isinstance(name, str) and parse_mcp_tool_name(name) is not None:
        return name
    return str(name)

