"""MCP server 连接管理。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import McpConfig, McpServerConfig, load_mcp_config
from .connection import McpConnection, McpConnectionError, McpConnectionStatus
from .discovery import fetch_resources_for_connection, fetch_tools_for_connection
from .runtime import McpRuntime


@dataclass(frozen=True)
class McpServerStatus:
    """用于 UI/debug 展示的 MCP server 状态快照。"""

    name: str
    status: McpConnectionStatus
    error: str = ""
    capabilities: dict[str, Any] | None = None
    server_info: dict[str, Any] | None = None


class McpManager:
    """管理多个 MCP server 的连接和协议请求。

    manager 只负责 MCP 来源的连接、状态和协议请求；工具适配和注册由后续步骤处理。
    """

    def __init__(self, project_root: Path, config: McpConfig | None = None) -> None:
        self.project_root = project_root
        self.config = config or load_mcp_config(project_root)
        self._runtime = McpRuntime()
        self._connections: dict[str, McpConnection] = {}
        self._tools_cache: dict[str, list[dict[str, Any]]] = {}
        self._resource_cache: dict[str, list[dict[str, Any]]] = {}
        for server_config in self.config.servers:
            self._connections[server_config.name] = McpConnection(
                config=server_config,
                project_root=project_root,
                runtime=self._runtime,
            )

    @classmethod
    def from_servers(
        cls,
        project_root: Path,
        servers: Iterable[McpServerConfig],
        *,
        config_path: Path | None = None,
    ) -> "McpManager":
        """从 server 配置集合构造 manager，便于测试和后续 CLI 组装。"""

        config = McpConfig(
            path=config_path or project_root / ".zzcode" / "mcp.json",
            servers=tuple(servers),
        )
        return cls(project_root=project_root, config=config)

    def connect_all(self) -> list[McpConnection]:
        """连接所有配置中的 server，单个失败不会中断其他 server。"""

        connected: list[McpConnection] = []
        for connection in self._connections.values():
            connection.connect()
            if connection.status == "connected":
                connected.append(connection)
        return connected

    def close_all(self) -> None:
        """关闭所有已启动的 MCP server。"""

        for connection in self._connections.values():
            connection.close()
        self._tools_cache.clear()
        self._resource_cache.clear()
        self._runtime.close()

    def get_connection(self, server_name: str) -> McpConnection | None:
        """按 server 名获取连接对象。"""

        return self._connections.get(server_name)

    def connected_connections(self) -> list[McpConnection]:
        """返回当前可用的 connected server。"""

        return [
            connection
            for connection in self._connections.values()
            if connection.is_connected
        ]

    def statuses(self) -> list[McpServerStatus]:
        """返回所有 server 的状态快照。"""

        return [
            McpServerStatus(
                name=connection.name,
                status=connection.status,
                error=connection.error,
                capabilities=dict(connection.capabilities),
                server_info=dict(connection.server_info),
            )
            for connection in self._connections.values()
        ]

    def list_tools(self) -> dict[str, list[dict[str, Any]]]:
        """对 connected server 调用 tools/list，返回按 server 分组的原始 tool 定义。"""

        tools_by_server: dict[str, list[dict[str, Any]]] = {}
        for connection in self.connected_connections():
            if connection.name in self._tools_cache:
                tools_by_server[connection.name] = _copy_object_list(self._tools_cache[connection.name])
                continue
            try:
                tools = fetch_tools_for_connection(connection)
                tools_by_server[connection.name] = tools
                self._tools_cache[connection.name] = _copy_object_list(tools)
            except McpConnectionError as exc:
                self._mark_failed(connection, str(exc))
                tools_by_server[connection.name] = []
        return tools_by_server

    def has_resource_servers(self) -> bool:
        """返回是否存在 connected 且支持 resources 的 server。"""

        return any(
            _supports_capability(connection.capabilities, "resources")
            for connection in self.connected_connections()
        )

    def clear_server_cache(self, server_name: str | None = None) -> None:
        """清理 tools/resources 发现缓存。"""

        if server_name is None:
            self._tools_cache.clear()
            self._resource_cache.clear()
            return
        self._tools_cache.pop(server_name, None)
        self._resource_cache.pop(server_name, None)

    def clear_resource_cache(self, server_name: str | None = None) -> None:
        """清理 resources/list 缓存。"""

        if server_name is None:
            self._resource_cache.clear()
            return
        self._resource_cache.pop(server_name, None)

    def list_resources(
        self,
        server_name: str | None = None,
        *,
        use_cache: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """对 connected server 调用 resources/list，返回按 server 分组的原始 resource 定义。"""

        resources_by_server: dict[str, list[dict[str, Any]]] = {}
        connections = (
            [self._require_connected_server(server_name)]
            if server_name is not None
            else self.connected_connections()
        )
        for connection in connections:
            if not _supports_capability(connection.capabilities, "resources"):
                if server_name is not None:
                    raise McpConnectionError(
                        f"MCP server '{connection.name}' does not support resources."
                    )
                continue
            if use_cache and connection.name in self._resource_cache:
                resources_by_server[connection.name] = _copy_object_list(
                    self._resource_cache[connection.name]
                )
                continue
            try:
                resources = fetch_resources_for_connection(connection)
                resources_by_server[connection.name] = resources
                self._resource_cache[connection.name] = _copy_object_list(resources)
            except McpConnectionError as exc:
                self._mark_failed(connection, str(exc))
                resources_by_server[connection.name] = []
        return resources_by_server

    def read_resource(self, server_name: str, uri: str) -> Any:
        """读取指定 server 暴露的 resource，不做本地文件兜底。"""

        connection = self._require_connected_server(server_name)
        if not _supports_capability(connection.capabilities, "resources"):
            raise McpConnectionError(f"MCP server '{server_name}' does not support resources.")
        return connection.read_resource(uri)

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        args: dict[str, Any],
        *,
        tool_call_id: str = "",
    ) -> Any:
        """调用指定 server 的 MCP tool。"""

        connection = self._require_connected_server(server_name)
        if not _supports_capability(connection.capabilities, "tools"):
            raise McpConnectionError(f"MCP server '{server_name}' does not support tools.")
        meta = {"zzcode/toolUseId": tool_call_id} if tool_call_id else None
        return connection.call_tool(tool_name, args, meta=meta)

    def reconnect(self, server_name: str) -> McpConnection:
        """清理缓存并重新连接指定 server。"""

        connection = self.get_connection(server_name)
        if connection is None:
            raise McpConnectionError(f"Unknown MCP server: {server_name}")
        connection.close()
        self.clear_server_cache(server_name)
        return connection.connect()

    def _require_connected_server(self, server_name: str) -> McpConnection:
        connection = self.get_connection(server_name)
        if connection is None:
            raise McpConnectionError(f"Unknown MCP server: {server_name}")
        if not connection.is_connected:
            raise McpConnectionError(
                f"MCP server '{server_name}' is not connected "
                f"(status: {connection.status})."
            )
        return connection

    def _mark_failed(self, connection: McpConnection, error: str) -> None:
        connection.status = "failed"
        connection.error = error
        connection.close()
        self.clear_server_cache(connection.name)


def _supports_capability(capabilities: dict[str, Any], name: str) -> bool:
    return isinstance(capabilities.get(name), dict)


def _copy_object_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]
