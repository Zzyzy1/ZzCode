"""结构化错误日志。"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .debug import get_logging_context, log_debug
from .paths import get_error_log_path, get_mcp_jsonl_path


def log_error(error: object, *, component: str, context: dict[str, Any] | None = None) -> None:
    """记录一条结构化错误日志。"""

    message = _error_message(error)
    payload = _base_payload(kind="error", component=component, message=message)
    payload["traceback"] = _error_traceback(error)
    if context:
        payload.update(context)
    _append_jsonl(get_error_log_path(), payload)
    log_debug(message, level="error", component=component)


def log_mcp_error(
    server_name: str,
    error: object,
    *,
    operation: str,
    context: dict[str, Any] | None = None,
) -> None:
    """记录一条 MCP 结构化错误日志。"""

    message = _error_message(error)
    payload = _base_payload(kind="mcp_error", component="mcp", message=message)
    payload["traceback"] = _error_traceback(error)
    payload["server_name"] = server_name
    payload["operation"] = operation
    if context:
        payload.update(context)
    _append_jsonl(get_mcp_jsonl_path(server_name), payload)
    log_debug(f'MCP server "{server_name}" {operation} failed: {message}', level="error", component="mcp")


def log_mcp_debug(
    server_name: str,
    message: str,
    *,
    operation: str,
    context: dict[str, Any] | None = None,
) -> None:
    """记录一条 MCP 调试日志。"""

    payload = _base_payload(kind="mcp_debug", component="mcp", message=message)
    payload["server_name"] = server_name
    payload["operation"] = operation
    if context:
        payload.update(context)
    _append_jsonl(get_mcp_jsonl_path(server_name), payload)
    log_debug(f'MCP server "{server_name}" {operation}: {message}', level="debug", component="mcp")


def _base_payload(*, kind: str, component: str, message: str) -> dict[str, Any]:
    current = get_logging_context()
    return {
        "timestamp": datetime.now().isoformat(),
        "level": "error" if kind.endswith("error") or kind == "error" else "debug",
        "kind": kind,
        "session_id": current.session_id,
        "cwd": current.cwd,
        "project_root": current.project_root,
        "component": component,
        "message": message,
    }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _error_message(error: object) -> str:
    return str(error) if str(error) else error.__class__.__name__


def _error_traceback(error: object) -> str:
    if isinstance(error, BaseException):
        return "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()
    return ""
