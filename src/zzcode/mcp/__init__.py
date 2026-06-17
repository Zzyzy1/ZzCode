"""MCP 工具来源接入层。"""

from .config import (
    DEFAULT_MCP_TIMEOUT_SECONDS,
    MCP_CONFIG_RELATIVE_PATH,
    SUPPORTED_MCP_TRANSPORTS,
    McpConfig,
    McpConfigError,
    McpServerConfig,
    get_mcp_config_path,
    load_mcp_config,
)
from .connection import (
    MCP_CLIENT_NAME,
    MCP_CLIENT_VERSION,
    MCP_PROTOCOL_VERSION,
    McpConnection,
    McpConnectionError,
    McpConnectionStatus,
)
from .manager import McpManager, McpServerStatus
from .names import (
    MCP_NAME_SEPARATOR,
    MCP_TOOL_PREFIX,
    McpToolName,
    build_mcp_tool_name,
    get_mcp_permission_name,
    get_mcp_prefix,
    normalize_mcp_name,
    parse_mcp_tool_name,
)
from .resources import (
    McpResource,
    McpReadResourceResult,
    format_mcp_read_resource_result,
    format_mcp_resources,
    normalize_mcp_resource,
    normalize_mcp_resources,
)
from .results import McpNormalizedResult, normalize_mcp_tool_result
from .runtime import McpRuntime, McpRuntimeError
from .tool_adapter import (
    DEFAULT_MCP_INPUT_SCHEMA,
    McpToolAdapter,
    McpToolCaller,
    McpToolInfo,
    build_mcp_tools,
    format_mcp_tool_result,
    from_mcp_tool_definition,
)

__all__ = [
    "DEFAULT_MCP_INPUT_SCHEMA",
    "DEFAULT_MCP_TIMEOUT_SECONDS",
    "MCP_CONFIG_RELATIVE_PATH",
    "MCP_CLIENT_NAME",
    "MCP_CLIENT_VERSION",
    "MCP_NAME_SEPARATOR",
    "MCP_PROTOCOL_VERSION",
    "MCP_TOOL_PREFIX",
    "SUPPORTED_MCP_TRANSPORTS",
    "McpConfig",
    "McpConfigError",
    "McpConnection",
    "McpConnectionError",
    "McpConnectionStatus",
    "McpManager",
    "McpNormalizedResult",
    "McpReadResourceResult",
    "McpResource",
    "McpRuntime",
    "McpRuntimeError",
    "McpServerConfig",
    "McpServerStatus",
    "McpToolAdapter",
    "McpToolCaller",
    "McpToolInfo",
    "McpToolName",
    "build_mcp_tool_name",
    "build_mcp_tools",
    "format_mcp_read_resource_result",
    "format_mcp_tool_result",
    "format_mcp_resources",
    "from_mcp_tool_definition",
    "get_mcp_config_path",
    "get_mcp_permission_name",
    "get_mcp_prefix",
    "load_mcp_config",
    "normalize_mcp_name",
    "normalize_mcp_resource",
    "normalize_mcp_resources",
    "normalize_mcp_tool_result",
    "parse_mcp_tool_name",
]
