"""日志路径解析。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def get_log_root_dir() -> Path:
    """返回全局日志根目录。

    优先读取显式环境变量；未配置时按平台选择用户级目录。
    """

    override = os.getenv("ZZCODE_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata).expanduser().resolve() / "ZzCode" / "logs"
        return Path.home().resolve() / "AppData" / "Local" / "ZzCode" / "logs"

    state_home = os.getenv("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser().resolve() / "zzcode" / "logs"
    return Path.home().resolve() / ".local" / "state" / "zzcode" / "logs"


def get_debug_logs_dir() -> Path:
    """返回 debug 日志目录。"""

    return get_log_root_dir() / "debug"


def get_errors_logs_dir() -> Path:
    """返回错误日志目录。"""

    return get_log_root_dir() / "errors"


def get_mcp_logs_dir(server_name: str | None = None) -> Path:
    """返回 MCP 日志目录。"""

    base = get_log_root_dir() / "mcp"
    if not server_name:
        return base
    return base / sanitize_log_name(server_name)


def get_debug_log_path(session_id: str) -> Path:
    """返回某个会话的 debug 日志路径。"""

    return get_debug_logs_dir() / f"{sanitize_log_name(session_id)}.log"


def get_latest_debug_log_path() -> Path:
    """返回最新 debug 日志入口。"""

    return get_debug_logs_dir() / "latest.log"


def get_error_log_path(now: datetime | None = None) -> Path:
    """返回当天错误日志 JSONL 路径。"""

    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    return get_errors_logs_dir() / f"{stamp}.jsonl"


def get_mcp_jsonl_path(server_name: str, now: datetime | None = None) -> Path:
    """返回某个 MCP server 的结构化日志路径。"""

    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    return get_mcp_logs_dir(server_name) / f"{stamp}.jsonl"


def get_mcp_stderr_path(server_name: str) -> Path:
    """返回某个 MCP server 的原始 stderr 文件路径。"""

    return get_mcp_logs_dir(server_name) / "stderr.log"


def sanitize_log_name(value: str) -> str:
    """把任意字符串转换成稳定文件名。"""

    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value.strip())
    return cleaned or "unknown"
