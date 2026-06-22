"""调试日志入口。"""

from __future__ import annotations

import atexit
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .paths import get_debug_log_path, get_latest_debug_log_path, resolve_log_override
from .process import write_to_stderr
from .writer import BufferedFileWriter


DebugLogLevel = Literal["verbose", "debug", "info", "warn", "error"]

_LEVEL_ORDER: dict[DebugLogLevel, int] = {
    "verbose": 0,
    "debug": 1,
    "info": 2,
    "warn": 3,
    "error": 4,
}


@dataclass
class LoggingContext:
    """当前进程的日志上下文。"""

    session_id: str = f"bootstrap-{os.getpid()}"
    project_root: str = ""
    cwd: str = ""


_context = LoggingContext(cwd=os.getcwd())
_writer: BufferedFileWriter | None = None
_registered_exit_hook = False
_logging_failed = False


def configure_logging_context(
    *,
    session_id: str | None = None,
    project_root: Path | None = None,
) -> None:
    """更新当前进程日志上下文。"""

    global _context, _writer

    if session_id:
        previous = _context.session_id
        _context.session_id = session_id
        if _writer is not None and previous != session_id:
            _writer.close()
            _writer = None
    if project_root is not None:
        resolved = str(project_root.resolve())
        _context.project_root = resolved
        _context.cwd = resolved


def get_logging_context() -> LoggingContext:
    """返回当前日志上下文。"""

    return LoggingContext(
        session_id=_context.session_id,
        project_root=_context.project_root,
        cwd=_context.cwd or os.getcwd(),
    )


def is_debug_enabled() -> bool:
    """返回当前是否记录 debug 日志。"""

    raw = os.getenv("ZZCODE_DEBUG", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def is_debug_to_stderr() -> bool:
    """返回当前是否同时输出到 stderr。"""

    raw = os.getenv("ZZCODE_DEBUG_TO_STDERR", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_min_debug_level() -> DebugLogLevel:
    """返回最小输出级别。"""

    raw = os.getenv("ZZCODE_DEBUG_LEVEL", "debug").strip().lower()
    if raw in _LEVEL_ORDER:
        return raw  # type: ignore[return-value]
    return "debug"


def get_current_debug_log_path() -> Path:
    """返回当前会话 debug 日志路径。"""

    override = os.getenv("ZZCODE_DEBUG_FILE")
    if override:
        return resolve_log_override(override)
    return get_debug_log_path(_context.session_id)


def flush_debug_logs() -> None:
    """主动刷盘 debug 日志。"""

    if _writer is not None:
        try:
            _writer.flush()
        except OSError:
            pass


def log_debug(message: str, *, level: DebugLogLevel = "debug", component: str | None = None) -> None:
    """写入一条调试日志。"""

    global _logging_failed

    if _logging_failed:
        return
    if _LEVEL_ORDER[level] < _LEVEL_ORDER[get_min_debug_level()]:
        return
    if not is_debug_enabled():
        return

    normalized = _normalize_debug_message(message)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_text = level.upper().ljust(5)
    component_text = (component or "-")[:14].ljust(14)
    line = f"{timestamp} | {level_text} | {component_text} | {normalized}\n"
    try:
        writer = _get_writer()
        writer.write(line)
    except OSError:
        # 调试日志不能影响 Agent 主流程；路径不可写时本进程后续跳过 debug 写入。
        _logging_failed = True
        return
    if is_debug_to_stderr():
        write_to_stderr(line)


def _normalize_debug_message(message: str) -> str:
    stripped = message.strip()
    if not stripped:
        return "-"
    if "\n" in stripped:
        stripped = json.dumps(stripped, ensure_ascii=False)
    compacted = re.sub(r"\s+", " ", stripped).strip()
    if len(compacted) <= 240:
        return compacted
    return f"{compacted[:237]}..."


def _get_writer() -> BufferedFileWriter:
    global _writer, _registered_exit_hook

    if _writer is None:
        _writer = BufferedFileWriter(
            get_current_debug_log_path(),
            mirror_path=get_latest_debug_log_path(),
            flush_interval_seconds=1.0,
            immediate=is_debug_to_stderr(),
        )
    if not _registered_exit_hook:
        atexit.register(flush_debug_logs)
        _registered_exit_hook = True
    return _writer
