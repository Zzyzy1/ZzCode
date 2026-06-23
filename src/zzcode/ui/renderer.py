"""Inline terminal renderers for UI messages."""

from __future__ import annotations

import json
from typing import Protocol

from .messages import (
    AssistantDelta,
    AssistantThought,
    FinalAnswer,
    StepStarted,
    SubagentDone,
    SubagentStarted,
    SubagentToolResult,
    SubagentToolUse,
    SystemNotice,
    ToolResult,
    ToolUse,
    UiMessage,
)


class InlineRenderer(Protocol):
    def render(self, message: UiMessage) -> None:
        """渲染一条 UI 消息。

        message 是 Agent 产生的 UI 消息；无返回值。
        """


class PlainInlineRenderer:
    """纯文本 renderer。

    在未安装 Rich 时使用，保证 CLI 仍然可运行。
    """

    def render(self, message: UiMessage) -> None:
        """按消息类型输出纯文本。

        message 是 UI 消息对象；无返回值。
        """

        if isinstance(message, StepStarted):
            print(f"\n--- Step {message.step}/{message.max_steps} ---")
        elif isinstance(message, AssistantDelta):
            print(message.text, end="", flush=True)
        elif isinstance(message, AssistantThought):
            print(f"● Thought\n  {message.text}")
        elif isinstance(message, ToolUse):
            label = message.display_name or message.name
            print(f"● {label}({_format_tool_input(message.tool_input)})")
        elif isinstance(message, ToolResult):
            print(f"  ⎿ {message.output}")
        elif isinstance(message, FinalAnswer):
            print(f"● Final\n  {message.text}")
        elif isinstance(message, SystemNotice):
            print(f"● {message.level.title()}\n  ⎿ {message.text}")
        elif isinstance(message, SubagentStarted):
            print(f"● Subagent {message.name} started ({message.agent_id})")
        elif isinstance(message, SubagentToolUse):
            print(f"  ● {message.name}({_format_tool_input(message.tool_input)})")
        elif isinstance(message, SubagentToolResult):
            print(f"    ⎿ {_truncate_for_terminal(message.output)}")
        elif isinstance(message, SubagentDone):
            status = "completed" if message.ok else "failed"
            print(f"● Subagent {message.name} {status}: {message.transcript_path}")


class RichInlineRenderer:
    """Rich 版 inline renderer。

    用轻量的 ● 和 ⎿ 风格模拟 Claude Code 的消息流。
    """

    def __init__(self, console: object | None = None) -> None:
        if console is None:
            from rich.console import Console

            console = Console()
        self.console = console

    def render(self, message: UiMessage) -> None:
        """按消息类型分发到具体渲染方法。

        message 是 UI 消息对象；无返回值。
        """

        if isinstance(message, StepStarted):
            self._step(message)
        elif isinstance(message, AssistantDelta):
            self._delta(message)
        elif isinstance(message, AssistantThought):
            self._thought(message)
        elif isinstance(message, ToolUse):
            self._tool_use(message)
        elif isinstance(message, ToolResult):
            self._tool_result(message)
        elif isinstance(message, FinalAnswer):
            self._final(message)
        elif isinstance(message, SystemNotice):
            self._notice(message)
        elif isinstance(message, SubagentStarted):
            self._subagent_started(message)
        elif isinstance(message, SubagentToolUse):
            self._subagent_tool_use(message)
        elif isinstance(message, SubagentToolResult):
            self._subagent_tool_result(message)
        elif isinstance(message, SubagentDone):
            self._subagent_done(message)

    def _step(self, message: StepStarted) -> None:
        self.console.print(f"\n[dim]Step {message.step}/{message.max_steps}[/dim]")

    def _delta(self, message: AssistantDelta) -> None:
        self.console.print(message.text, end="")

    def _thought(self, message: AssistantThought) -> None:
        from rich.markup import escape

        self.console.print("[bold blue]● Thought[/bold blue]")
        self.console.print(f"  {escape(message.text)}")

    def _tool_use(self, message: ToolUse) -> None:
        from rich.markup import escape

        label = message.display_name or message.name
        # 模型输出可能包含 [] 等 Rich markup 字符，必须转义后再渲染。
        self.console.print(
            f"[bold yellow]● {escape(label)}[/bold yellow]([dim]{escape(_format_tool_input(message.tool_input))}[/dim])"
        )

    def _tool_result(self, message: ToolResult) -> None:
        from rich.markup import escape

        self.console.print(f"[dim]  ⎿[/dim] {escape(message.output)}")

    def _final(self, message: FinalAnswer) -> None:
        from rich.markup import escape

        self.console.print("[bold magenta]● Final[/bold magenta]")
        self.console.print(f"  {escape(message.text)}")

    def _notice(self, message: SystemNotice) -> None:
        from rich.markup import escape

        color = {
            "info": "cyan",
            "warning": "yellow",
            "error": "red",
        }[message.level]
        self.console.print(f"[bold {color}]● {message.level.title()}[/bold {color}]")
        self.console.print(f"[dim]  ⎿[/dim] {escape(message.text)}")

    def _subagent_started(self, message: SubagentStarted) -> None:
        from rich.markup import escape

        label = escape(message.name)
        self.console.print(f"[bold cyan]● Subagent[/bold cyan] {label} [dim]started[/dim]")

    def _subagent_tool_use(self, message: SubagentToolUse) -> None:
        from rich.markup import escape

        label = message.display_name or message.name
        self.console.print(
            f"[dim]  ●[/dim] [yellow]{escape(label)}[/yellow]([dim]{escape(_format_tool_input(message.tool_input))}[/dim])"
        )

    def _subagent_tool_result(self, message: SubagentToolResult) -> None:
        from rich.markup import escape

        self.console.print(f"[dim]    ⎿[/dim] {escape(_truncate_for_terminal(message.output))}")

    def _subagent_done(self, message: SubagentDone) -> None:
        from rich.markup import escape

        status = "completed" if message.ok else "failed"
        self.console.print(
            f"[bold cyan]● Subagent[/bold cyan] {escape(message.name)} [dim]{status}: {escape(message.transcript_path)}[/dim]"
        )


def _format_tool_input(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _truncate_for_terminal(text: str, max_length: int = 1000) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n... (truncated)"
