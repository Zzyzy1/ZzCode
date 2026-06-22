"""日志路径解析。"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


def get_log_root_dir() -> Path:
    """返回全局日志根目录。

    优先读取显式环境变量；未配置时按平台选择用户级目录。
    """

    override = os.getenv("ZZCODE_LOG_DIR") or _read_dotenv_override()
    if override:
        return resolve_log_override(override)

    project_override = _infer_wsl_project_log_dir()
    if project_override is not None:
        return project_override

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


def _read_dotenv_override() -> str | None:
    """从项目 .env 中读取日志目录覆盖。"""

    env_path = _resolve_project_root() / ".env"
    if not env_path.exists():
        return None

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != "ZZCODE_LOG_DIR":
                continue
            return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _infer_wsl_project_log_dir() -> Path | None:
    """在 WSL 下默认把日志写到项目同级的 Windows 目录。"""

    if os.name == "nt":
        return None
    if "WSL_DISTRO_NAME" not in os.environ:
        return None

    project_root = _resolve_project_root()
    parts = project_root.parts
    if len(parts) < 3 or parts[1] != "mnt":
        return None
    return project_root.parent / f"{project_root.name}-logs"


def _resolve_project_root() -> Path:
    """返回当前进程对应的项目根目录。"""

    raw = os.getenv("ZZCODE_PROJECT_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_log_override(raw: str) -> Path:
    """解析显式日志目录，兼容 WSL 下的 Windows 盘符路径。"""

    value = raw.strip()
    if os.name != "nt":
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
        if match:
            drive = match.group(1).lower()
            tail = match.group(2).replace("\\", "/")
            return Path(f"/mnt/{drive}/{tail}").resolve()
    return Path(value).expanduser().resolve()
