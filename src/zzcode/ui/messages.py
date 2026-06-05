"""Small UI message model inspired by Claude Code's message rendering tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True)
class StepStarted:
    step: int
    max_steps: int


@dataclass(frozen=True)
class AssistantThought:
    text: str


@dataclass(frozen=True)
class ToolUse:
    name: str
    tool_input: str
    display_name: str | None = None


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: str


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class SystemNotice:
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
