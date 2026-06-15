"""当前会话的磁盘路径和 transcript 记录。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


DEFAULT_SESSION_MEMORY_TEMPLATE = """# Session Title
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

# Key Results
_If the user asked for a specific output, keep the exact result here._

# Worklog
_Step by step, what was attempted and completed? Keep this terse._
"""

DEFAULT_SESSION_MEMORY_MAX_CHARS = 8000
SESSION_MEMORY_MAX_SECTION_TOKENS = 2000
SESSION_MEMORY_MAX_TOTAL_TOKENS = 12000


@dataclass(frozen=True)
class SessionScope:
    """一次 ZzCode 后端会话对应的磁盘位置。"""

    session_id: str
    session_dir: Path
    transcript_path: Path
    session_memory_dir: Path
    session_memory_path: Path


@dataclass(frozen=True)
class SessionMemoryTruncateResult:
    """Session memory 截断结果。"""

    content: str
    was_truncated: bool


def create_session_scope(project_root: Path, session_id: str | None = None) -> SessionScope:
    """创建当前会话目录，返回本次会话的路径集合。"""

    resolved_id = session_id or str(uuid4())
    session_dir = get_session_dir(project_root, resolved_id)
    memory_dir = session_dir / "session-memory"
    scope = SessionScope(
        session_id=resolved_id,
        session_dir=session_dir,
        transcript_path=session_dir / "transcript.jsonl",
        session_memory_dir=memory_dir,
        session_memory_path=memory_dir / "summary.md",
    )
    ensure_session_scope(scope)
    return scope


def get_sessions_dir(project_root: Path) -> Path:
    """返回项目内所有会话记录目录。"""

    return project_root / ".zzcode" / "sessions"


def get_session_dir(project_root: Path, session_id: str) -> Path:
    """返回指定 sessionId 对应的会话目录。"""

    return get_sessions_dir(project_root) / session_id


def ensure_session_scope(scope: SessionScope) -> None:
    """确保当前会话 transcript 和 session memory 文件存在。"""

    scope.session_memory_dir.mkdir(parents=True, exist_ok=True)
    scope.transcript_path.touch(exist_ok=True)
    if not scope.session_memory_path.exists():
        scope.session_memory_path.write_text(DEFAULT_SESSION_MEMORY_TEMPLATE, encoding="utf-8")


def read_current_session_memory(
    scope: SessionScope | None,
    max_chars: int = DEFAULT_SESSION_MEMORY_MAX_CHARS,
) -> str:
    """读取当前 session memory，默认模板视为空内容。"""

    if scope is None:
        return ""
    try:
        content = scope.session_memory_path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return ""
    if is_session_memory_empty(content):
        return ""
    if max_chars >= 0 and len(content) > max_chars:
        return content[:max_chars] + "\n\n[current session memory truncated]"
    return content


def is_session_memory_empty(content: str) -> bool:
    """判断 session memory 是否仍是默认模板。"""

    return content.strip() == DEFAULT_SESSION_MEMORY_TEMPLATE.strip()


def analyze_session_memory_sections(content: str) -> dict[str, int]:
    """按 section 估算 session memory 内容体量。"""

    sections: dict[str, int] = {}
    current_section = ""
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("# "):
            _store_session_memory_section_size(sections, current_section, current_lines)
            current_section = line
            current_lines = []
        else:
            current_lines.append(line)
    _store_session_memory_section_size(sections, current_section, current_lines)
    return sections


def build_session_memory_size_reminders(content: str) -> str:
    """生成 session memory 过长提醒，供后续 updater prompt 使用。"""

    section_sizes = analyze_session_memory_sections(content)
    total_tokens = _rough_token_count(content)
    oversized = sorted(
        (
            (section, tokens)
            for section, tokens in section_sizes.items()
            if tokens > SESSION_MEMORY_MAX_SECTION_TOKENS
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    over_budget = total_tokens > SESSION_MEMORY_MAX_TOTAL_TOKENS
    if not oversized and not over_budget:
        return ""

    parts: list[str] = []
    if over_budget:
        parts.append(
            "CRITICAL: The session memory file is currently "
            f"~{total_tokens} tokens, which exceeds the maximum of "
            f"{SESSION_MEMORY_MAX_TOTAL_TOKENS} tokens. Condense oversized sections."
        )
    if oversized:
        lines = [
            f'- "{section}" is ~{tokens} tokens (limit: {SESSION_MEMORY_MAX_SECTION_TOKENS})'
            for section, tokens in oversized
        ]
        header = "Oversized sections to condense:" if over_budget else "IMPORTANT: The following sections exceed the per-section limit:"
        parts.append(header + "\n" + "\n".join(lines))
    return "\n\n".join(parts)


def truncate_session_memory_for_compact(
    content: str,
    max_section_tokens: int = SESSION_MEMORY_MAX_SECTION_TOKENS,
) -> SessionMemoryTruncateResult:
    """按 section 截断 session memory，避免 compact summary 占满上下文。"""

    max_section_chars = max_section_tokens * 4
    output_lines: list[str] = []
    current_header = ""
    current_lines: list[str] = []
    was_truncated = False
    for line in content.splitlines():
        if line.startswith("# "):
            lines, truncated = _flush_session_memory_section(current_header, current_lines, max_section_chars)
            output_lines.extend(lines)
            was_truncated = was_truncated or truncated
            current_header = line
            current_lines = []
        else:
            current_lines.append(line)
    lines, truncated = _flush_session_memory_section(current_header, current_lines, max_section_chars)
    output_lines.extend(lines)
    was_truncated = was_truncated or truncated
    return SessionMemoryTruncateResult(content="\n".join(output_lines), was_truncated=was_truncated)


class TranscriptRecorder:
    """向当前 session 的 transcript.jsonl 追加事件。"""

    def __init__(self, scope: SessionScope) -> None:
        self.scope = scope
        self._sequence = 0
        self._parent_event_id: str | None = None
        self._current_turn_id: str | None = None
        self._restore_state_from_existing_transcript()

    def begin_turn(self) -> str:
        """开始一轮用户请求，返回本轮 turnId。"""

        self._current_turn_id = str(uuid4())
        return self._current_turn_id

    def end_turn(self) -> None:
        """结束当前 turn。"""

        self._current_turn_id = None

    def record_user(self, text: str) -> None:
        """记录用户输入。"""

        self.record("user", text=text)

    def record_assistant(self, text: str) -> None:
        """记录 assistant 最终回答。"""

        self.record("assistant", text=text)

    def record_tool_use(self, tool_name: str, tool_input: str) -> None:
        """记录一次工具调用。"""

        self.record("tool_use", toolName=tool_name, input=tool_input)

    def record_tool_result(self, tool_name: str, output: str, ok: bool = True) -> None:
        """记录一次工具执行结果。"""

        self.record("tool_result", toolName=tool_name, output=output, ok=ok)

    def record_compact(
        self,
        *,
        trigger: str,
        removed_items: int,
        kept_items: int,
        summary: str,
    ) -> None:
        """记录一次 compact boundary 和 compact summary。"""

        boundary = self.record(
            "compact_boundary",
            reset_parent=True,
            trigger=trigger,
            removedItems=removed_items,
            keptItems=kept_items,
        )
        self.record(
            "compact_summary",
            compactBoundaryEventId=boundary["eventId"],
            summary=summary,
        )

    def record(self, event_type: str, **fields: object) -> dict[str, object]:
        """追加一条 transcript JSONL 事件。"""

        reset_parent = bool(fields.pop("reset_parent", False))
        event_id = str(uuid4())
        parent_event_id = None if reset_parent else self._parent_event_id
        logical_parent_event_id = self._parent_event_id if reset_parent else None
        turn_id = self._current_turn_id
        event = {
            "type": event_type,
            "eventId": event_id,
            "parentEventId": parent_event_id,
            "logicalParentEventId": logical_parent_event_id,
            "turnId": turn_id,
            "sequence": self._sequence,
            "sessionId": self.scope.session_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        line = json.dumps(event, ensure_ascii=False)
        with self.scope.transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self._sequence += 1
        self._parent_event_id = event_id
        return event

    def _restore_state_from_existing_transcript(self) -> None:
        """从已有 transcript 恢复 sequence 和父事件游标。"""

        try:
            lines = self.scope.transcript_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        self._sequence = len(lines)
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = event.get("eventId")
            if isinstance(event_id, str) and event_id:
                self._parent_event_id = event_id
                break


def _store_session_memory_section_size(sections: dict[str, int], section: str, lines: list[str]) -> None:
    if not section:
        return
    section_content = "\n".join(lines).strip()
    if section_content:
        sections[section] = _rough_token_count(section_content)


def _rough_token_count(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _flush_session_memory_section(
    section_header: str,
    section_lines: list[str],
    max_section_chars: int,
) -> tuple[list[str], bool]:
    if not section_header:
        return (section_lines, False)

    section_content = "\n".join(section_lines)
    if len(section_content) <= max_section_chars:
        return ([section_header, *section_lines], False)

    kept_lines = [section_header]
    char_count = 0
    for line in section_lines:
        if char_count + len(line) + 1 > max_section_chars:
            break
        kept_lines.append(line)
        char_count += len(line) + 1
    kept_lines.append("[section truncated for compact]")
    return (kept_lines, True)
