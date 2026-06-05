"""Inline terminal renderers for UI messages."""

from __future__ import annotations

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
        """Render a UI message."""


class PlainInlineRenderer:
    """Plain text fallback renderer."""

    def render(self, message: UiMessage) -> None:
        if isinstance(message, StepStarted):
            print(f"\n--- Step {message.step}/{message.max_steps} ---")
        elif isinstance(message, AssistantThought):
            print(f"● Thought\n  {message.text}")
        elif isinstance(message, ToolUse):
            label = message.display_name or message.name
            print(f"● {label}({message.tool_input})")
        elif isinstance(message, ToolResult):
            print(f"  ⎿ {message.output}")
        elif isinstance(message, FinalAnswer):
            print(f"● Final\n  {message.text}")
        elif isinstance(message, SystemNotice):
            print(f"● {message.level.title()}\n  ⎿ {message.text}")


class RichInlineRenderer:
    """Rich renderer with Claude-like inline message styling."""

    def __init__(self, console: object | None = None) -> None:
        if console is None:
            from rich.console import Console

            console = Console()
        self.console = console

    def render(self, message: UiMessage) -> None:
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
        self.console.print(
            f"[bold yellow]● {escape(label)}[/bold yellow]([dim]{escape(message.tool_input)}[/dim])"
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
