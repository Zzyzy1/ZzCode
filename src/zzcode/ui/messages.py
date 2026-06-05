"""Small UI message model inspired by Claude Code's message rendering tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


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
class ToolUse:
    """模型请求调用工具时的 UI 消息。"""

    name: str
    tool_input: str
    display_name: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """工具执行完成后的 UI 消息。"""

    tool_name: str
    output: str


@dataclass(frozen=True)
class FinalAnswer:
    """Agent 完成任务后的最终回答。"""

    text: str


@dataclass(frozen=True)
class SystemNotice:
    """系统提示消息，覆盖 info、warning、error 三种级别。"""

    text: str
    level: Literal["info", "warning", "error"] = "info"


UiMessage: TypeAlias = (
    StepStarted
    | AssistantThought
    | ToolUse
    | ToolResult
    | FinalAnswer
    | SystemNotice
)
