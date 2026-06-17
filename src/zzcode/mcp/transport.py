"""MCP SDK transport 创建辅助。"""

from __future__ import annotations

from pathlib import Path

from zzcode.logging import get_mcp_stderr_path

from .config import McpServerConfig


MCP_STDERR_TAIL_BYTES = 64 * 1024


def mcp_stderr_log_path(project_root: Path, server_name: str) -> Path:
    """返回某个 MCP server 的 stderr 日志路径。"""

    _ = project_root
    return get_mcp_stderr_path(server_name)


def open_mcp_stderr_log(project_root: Path, server_name: str):
    """打开真实 stderr 日志文件，供 MCP SDK subprocess 使用。"""

    path = mcp_stderr_log_path(project_root, server_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", errors="replace")


def read_mcp_stderr_tail(project_root: Path, server_name: str, limit: int = MCP_STDERR_TAIL_BYTES) -> str:
    """读取 stderr 日志尾部，避免错误信息过大。"""

    path = mcp_stderr_log_path(project_root, server_name)
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def create_stdio_parameters(config: McpServerConfig, project_root: Path) -> object:
    """创建官方 MCP SDK stdio server 参数。"""

    from .connection import McpConnectionError

    try:
        from mcp.client.stdio import StdioServerParameters
    except ModuleNotFoundError as exc:
        raise McpConnectionError(
            "Python MCP SDK is not installed. Install project dependencies from requirements.txt."
        ) from exc

    if config.type != "stdio":
        raise McpConnectionError(f"Unsupported MCP transport: {config.type}")
    return StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) if config.env else None,
        cwd=project_root,
    )
