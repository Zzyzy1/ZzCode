"""Inline terminal renderers for UI messages."""

from __future__ import annotations

import json
from typing import Protocol

from .messages import (
    AssistantThought,
    FinalAnswer,
    StepStarted,
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

    def _step(self, message: StepStarted) -> None:
        self.console.print(f"\n[dim]Step {message.step}/{message.max_steps}[/dim]")

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


def _format_tool_input(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
