"""Session notes markdown 文件支持。"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SESSION_NOTES_TEMPLATE = """# Session Title
_A short and distinctive 5-10 word descriptive title for the session._

# Current State
_What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps._

# Task Specification
_What did the user ask to build? Any design decisions or other explanatory context._

# Files and Functions
_What are the important files? In short, what do they contain and why are they relevant?_

# Workflow
_What commands are usually run and in what order? How to interpret their output if not obvious?_

# Errors & Corrections
_Errors encountered and how they were fixed. What did the user correct? What approaches failed?_

# Learnings
_What has worked well? What has not? What to avoid?_

# Worklog
_Step by step, what was attempted and completed? Keep this terse._
"""

DEFAULT_SESSION_NOTES_MAX_CHARS = 8000


def get_session_notes_path(project_root: Path) -> Path:
    """返回当前项目的 session notes markdown 路径。"""

    return project_root / ".zzcode" / "session" / "notes.md"


def ensure_session_notes_file(project_root: Path) -> Path:
    """确保 session notes 存在；新建时写入默认模板，已存在时保留原内容。"""

    notes_path = get_session_notes_path(project_root)
    notes_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = os.open(notes_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return notes_path

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(DEFAULT_SESSION_NOTES_TEMPLATE)
    return notes_path


def read_session_notes(project_root: Path, max_chars: int = DEFAULT_SESSION_NOTES_MAX_CHARS) -> str:
    """读取非空 session notes；纯默认模板视为无有效内容。"""

    notes_path = get_session_notes_path(project_root)
    try:
        content = notes_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""

    if _is_default_template(content):
        return ""
    text = content.strip()
    if max_chars >= 0 and len(text) > max_chars:
        return text[:max_chars] + "\n\n[session notes truncated]"
    return text


def _is_default_template(content: str) -> bool:
    """判断 notes 是否仍是默认模板，避免把空模板注入上下文。"""

    return content.strip() == DEFAULT_SESSION_NOTES_TEMPLATE.strip()
