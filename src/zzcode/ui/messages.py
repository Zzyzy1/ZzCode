"""Small UI message model inspired by Claude Code's message rendering tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True)
class StepStarted:
    """Agent 进入新一步时的 UI 消息。"""

    step: int
    max_steps: int


@dataclass(frozen=True)
class AssistantThought:
    """模型 Thought 文本，用于展示推理摘要。"""

    text: str


@dataclass(frozen=True)
class AssistantDelta:
    """模型最终回答的增量文本。"""

    text: str


@dataclass(frozen=True)
class ToolUse:
    """模型请求调用工具时的 UI 消息。"""

    name: str
    tool_input: Any
    display_name: str | None = None
    id: str | None = None
    source: str = "local"
    mcp_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolResult:
    """工具执行完成后的 UI 消息。"""

    tool_name: str
    output: str
    id: str | None = None
    ok: bool | None = None
    source: str = "local"
    mcp_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class FinalAnswer:
    """Agent 完成任务后的最终回答。"""

    text: str


@dataclass(frozen=True)
class SystemNotice:
    """系统提示消息，覆盖 info、warning、error 三种级别。"""

    text: str
    level: Literal["info", "warning", "error"] = "info"


@dataclass(frozen=True)
class SubagentStarted:
    """子 Agent 开始执行。"""

    agent_id: str
    name: str
    description: str | None = None
    transcript_path: str | None = None


@dataclass(frozen=True)
class SubagentToolUse:
    """子 Agent 内部工具调用。"""

    agent_id: str
    name: str
    tool_input: Any
    display_name: str | None = None
    id: str | None = None
    source: str = "local"
    mcp_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubagentToolResult:
    """子 Agent 内部工具结果。"""

    agent_id: str
    tool_name: str
    output: str
    id: str | None = None
    ok: bool | None = None
    source: str = "local"
    mcp_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubagentDone:
    """子 Agent 执行结束。"""

    agent_id: str
    name: str
    ok: bool
    transcript_path: str
    error: str | None = None


UiMessage: TypeAlias = (
    StepStarted
    | AssistantDelta
    | AssistantThought
    | ToolUse
    | ToolResult
    | FinalAnswer
    | SystemNotice
    | SubagentStarted
    | SubagentToolUse
    | SubagentToolResult
    | SubagentDone
)
