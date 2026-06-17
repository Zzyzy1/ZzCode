"""MCP 配置读取和校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


MCP_CONFIG_RELATIVE_PATH = Path(".zzcode") / "mcp.json"
DEFAULT_MCP_TIMEOUT_SECONDS = 30.0
SUPPORTED_MCP_TRANSPORTS = {"stdio"}

McpTransportType = Literal["stdio"]


class McpConfigError(ValueError):
    """表示 MCP 配置文件不可读取或内容非法。"""


@dataclass(frozen=True)
class McpServerConfig:
    """描述一个 MCP server 配置。

    name 是配置中的 server 名；type 第一版只支持 stdio；
    command/args/env 用于后续连接层启动 server。
    """

    name: str
    type: McpTransportType
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class McpConfig:
    """项目级 MCP 配置。"""

    path: Path
    servers: tuple[McpServerConfig, ...] = ()

    @property
    def enabled_servers(self) -> tuple[McpServerConfig, ...]:
        """返回需要进入连接队列的 server。"""

        return tuple(server for server in self.servers if server.enabled)


def get_mcp_config_path(project_root: Path) -> Path:
    """返回项目级 MCP 配置固定路径。"""

    return project_root / MCP_CONFIG_RELATIVE_PATH


def load_mcp_config(project_root: Path) -> McpConfig:
    """读取并校验项目级 .zzcode/mcp.json。

    project_root 是当前项目根目录；配置不存在时返回空配置。
    """

    path = get_mcp_config_path(project_root)
    if not path.is_file():
        return McpConfig(path=path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"Invalid MCP config JSON at {path}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})."
        ) from exc
    except OSError as exc:
        raise McpConfigError(f"Cannot read MCP config at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise McpConfigError(f"Invalid MCP config at {path}: root value must be an object.")

    servers_raw = raw.get("mcpServers", {})
    if not isinstance(servers_raw, dict):
        raise McpConfigError(f"Invalid MCP config at {path}: 'mcpServers' must be an object.")

    servers = tuple(
        _parse_server_config(name, value, path)
        for name, value in sorted(servers_raw.items(), key=lambda item: item[0])
    )
    return McpConfig(path=path, servers=servers)


def _parse_server_config(name: Any, value: Any, path: Path) -> McpServerConfig:
    """解析单个 MCP server 配置。"""

    server_name = _require_server_name(name, path)
    if not isinstance(value, dict):
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: server config must be an object."
        )

    enabled = _parse_bool_field(value, "enabled", True, server_name, path)
    transport = _parse_transport(value.get("type", "stdio"), server_name, path)
    command = _parse_command(value.get("command"), enabled, server_name, path)
    args = _parse_string_list_field(value, "args", server_name, path)
    env = _parse_env_field(value, server_name, path)
    timeout_seconds = _parse_timeout_seconds(value, server_name, path)

    return McpServerConfig(
        name=server_name,
        type=transport,
        command=command,
        args=args,
        env=env,
        enabled=enabled,
        timeout_seconds=timeout_seconds,
    )


def _require_server_name(value: Any, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpConfigError(f"Invalid MCP config at {path}: server name must be a non-empty string.")
    return value.strip()


def _parse_transport(value: Any, server_name: str, path: Path) -> McpTransportType:
    if not isinstance(value, str) or not value.strip():
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: 'type' must be a non-empty string."
        )
    transport = value.strip()
    if transport not in SUPPORTED_MCP_TRANSPORTS:
        supported = ", ".join(sorted(SUPPORTED_MCP_TRANSPORTS))
        raise McpConfigError(
            f"Unsupported MCP transport for server '{server_name}' in {path}: "
            f"{transport!r}. Supported transports: {supported}."
        )
    return "stdio"


def _parse_command(value: Any, enabled: bool, server_name: str, path: Path) -> str:
    if value is None and not enabled:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: 'command' must be a non-empty string."
        )
    return value.strip()


def _parse_string_list_field(
    server_config: dict[str, Any],
    field_name: str,
    server_name: str,
    path: Path,
) -> tuple[str, ...]:
    value = server_config.get(field_name, [])
    if not isinstance(value, list):
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: '{field_name}' must be a list of strings."
        )
    if not all(isinstance(item, str) for item in value):
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: '{field_name}' must be a list of strings."
        )
    return tuple(value)


def _parse_env_field(server_config: dict[str, Any], server_name: str, path: Path) -> dict[str, str]:
    value = server_config.get("env", {})
    if not isinstance(value, dict):
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: 'env' must be an object of strings."
        )
    env: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise McpConfigError(
                f"Invalid MCP server '{server_name}' in {path}: 'env' keys and values must be strings."
            )
        env[key] = item
    return env


def _parse_bool_field(
    server_config: dict[str, Any],
    field_name: str,
    default: bool,
    server_name: str,
    path: Path,
) -> bool:
    value = server_config.get(field_name, default)
    if not isinstance(value, bool):
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: '{field_name}' must be a boolean."
        )
    return value


def _parse_timeout_seconds(
    server_config: dict[str, Any],
    server_name: str,
    path: Path,
) -> float:
    value = server_config.get("timeout_seconds", DEFAULT_MCP_TIMEOUT_SECONDS)
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise McpConfigError(
            f"Invalid MCP server '{server_name}' in {path}: 'timeout_seconds' must be a positive number."
        )
    return float(value)

