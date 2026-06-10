"""把指令记忆组装为 Agent 可用的上下文。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .loader import LoadedInstructionMemory, load_instruction_memories
from .session_notes import read_session_notes


MEMORY_INSTRUCTION_PROMPT = (
    "Codebase and user instructions are shown below. "
    "Follow them when they are relevant to the user's task."
)


@dataclass(frozen=True)
class MemoryContext:
    """一次请求使用的记忆上下文。

    text 是注入 Agent 的完整上下文；instruction_count/session_items 供调试展示。
    """

    text: str
    instruction_count: int
    instruction_chars: int
    session_items: int
    compact_summary_chars: int = 0
    session_notes_chars: int = 0


def build_memory_context(
    project_root: Path,
    session_history: Sequence[str],
    compact_summary: str = "",
    home: Path | None = None,
) -> MemoryContext:
    """加载指令记忆并合并当前短期会话历史。

    project_root 是项目根目录；session_history 是当前后端进程内的短期历史；
    返回可直接传入 TextReActAgent.run(session_context=...) 的上下文对象。
    """

    memories = load_instruction_memories(project_root, home=home)
    instruction_context = format_instruction_memories(memories)
    compact_context = format_compact_summary(compact_summary)
    notes_context = format_session_notes(read_session_notes(project_root))
    session_context = format_recent_session(session_history)
    parts = [part for part in [instruction_context, notes_context, compact_context, session_context] if part]
    return MemoryContext(
        text="\n\n".join(parts),
        instruction_count=len(memories),
        instruction_chars=sum(memory.char_count for memory in memories),
        session_items=len(session_history),
        compact_summary_chars=len(compact_summary),
        session_notes_chars=len(notes_context),
    )


def format_instruction_memories(memories: list[LoadedInstructionMemory]) -> str:
    """把已加载的指令记忆格式化为 Claude Code 风格上下文。"""

    entries = []
    for memory in memories:
        if not memory.content.strip():
            continue
        description = _memory_description(memory)
        entries.append(
            f"Contents of {memory.path}{description}:\n\n{memory.content.strip()}"
        )
    if not entries:
        return ""
    return f"{MEMORY_INSTRUCTION_PROMPT}\n\n" + "\n\n".join(entries)


def format_recent_session(session_history: Sequence[str]) -> str:
    """格式化当前进程内的短期会话历史。"""

    if not session_history:
        return ""
    return "Recent session:\n" + "\n".join(session_history)


def format_compact_summary(summary: str) -> str:
    """格式化压缩后的旧会话摘要。"""

    if not summary.strip():
        return ""
    return "Compacted session summary:\n" + summary.strip()


def format_session_notes(notes: str) -> str:
    """格式化 Session Memory Markdown 内容。"""

    if not notes.strip():
        return ""
    return "Session memory notes:\n" + notes.strip()


def _memory_description(memory: LoadedInstructionMemory) -> str:
    """返回记忆文件来源说明。"""

    labels = {
        "user": "user memory shared across projects",
        "project": "project instructions checked into the codebase",
        "rule": "project rule memory",
        "local": "private local project memory",
    }
    label = labels.get(memory.memory_type, memory.description)
    if memory.parent:
        label = f"{label}, included by {memory.parent}"
    if memory.truncated:
        label = f"{label}, truncated"
    return f" ({label})"
