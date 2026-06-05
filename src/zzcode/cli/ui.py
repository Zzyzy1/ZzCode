"""Terminal UI helpers for ZzCode."""

from __future__ import annotations

from typing import Protocol

from zzcode import __version__
from zzcode.tools.executor import ToolExecutor
from zzcode.ui.messages import (
    AssistantThought,
    FinalAnswer,
    StepStarted,
    SystemNotice,
    ToolResult,
    ToolUse,
    UiMessage,
)
from zzcode.ui.renderer import PlainInlineRenderer, RichInlineRenderer


class AgentRenderer(Protocol):
    """Message renderer used by TextReActAgent."""

    def render(self, message: UiMessage) -> None: ...


class PlainUI:
    """CLI 外壳的纯文本实现。

    负责 banner/help/prompt 等交互外壳，并把 Agent 消息交给 inline renderer。
    """

    def __init__(self) -> None:
        self.inline = PlainInlineRenderer()

    def banner(self, model: str, tools: ToolExecutor) -> None:
        """打印启动信息。

        model 是当前模型名；tools 是本次会话工具集合；无返回值。
        """

        print(f"ZzCode {__version__} - Text ReAct CLI")
        print(f"Model: {model}")
        print(f"Tools: {tools.tool_names_text()}")

    def help(self, tools: ToolExecutor) -> None:
        """打印帮助信息。

        tools 是本次会话工具集合；无返回值。
        """

        print(
            """
Commands:
  /help      show this help
  /clear     clear current agent history
  /exit      exit ZzCode

Tools:
{tools}
""".strip().format(tools=tools.get_available_tools())
        )

    def info(self, text: str) -> None:
        print(text)

    def goodbye(self) -> None:
        print("bye")

    def prompt(self) -> str:
        """读取一行用户输入。

        返回用户输入的原始字符串。
        """

        return input("\nzzcode> ")

    def step(self, step: int, max_steps: int) -> None:
        print(f"\n--- Step {step}/{max_steps} ---")

    def thought(self, text: str) -> None:
        print(f"Thought: {text}")

    def action(self, name: str, tool_input: str) -> None:
        print(f"Action: {name}[{tool_input}]")

    def observation(self, text: str) -> None:
        print(f"Observation: {text}")

    def final(self, text: str) -> None:
        print(f"Final: {text}")

    def warning(self, text: str) -> None:
        print(f"Warning: {text}")

    def error(self, text: str) -> None:
        self.render(SystemNotice(text=text, level="error"))

    def render(self, message: UiMessage) -> None:
        """渲染 Agent 产生的 UI 消息。

        message 是统一消息模型；无返回值。
        """

        self.inline.render(message)

    def step(self, step: int, max_steps: int) -> None:
        self.render(StepStarted(step, max_steps))

    def thought(self, text: str) -> None:
        self.render(AssistantThought(text))

    def action(self, name: str, tool_input: str) -> None:
        self.render(ToolUse(name=name, tool_input=tool_input))

    def observation(self, text: str) -> None:
        self.render(ToolResult(tool_name="", output=text))

    def final(self, text: str) -> None:
        self.render(FinalAnswer(text))

    def warning(self, text: str) -> None:
        self.render(SystemNotice(text=text, level="warning"))


class RichUI(PlainUI):
    """CLI 外壳的 Rich 实现。"""

    def __init__(self) -> None:
        from rich.console import Console

        self.console = Console()
        self.inline = RichInlineRenderer(self.console)

    def banner(self, model: str, tools: ToolExecutor) -> None:
        from rich.panel import Panel
        from rich.table import Table

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column()
        grid.add_row("Version", __version__)
        grid.add_row("Mode", "Text ReAct")
        grid.add_row("Model", model)
        grid.add_row("Tools", tools.tool_names_text())
        self.console.print(Panel(grid, title="[bold]ZzCode[/bold]", border_style="cyan"))

    def help(self, tools: ToolExecutor) -> None:
        from rich.panel import Panel
        from rich.table import Table
        from rich.markup import escape

        # help 保留表格形态，方便用户快速扫描命令和工具说明。
        commands = Table(show_header=True, header_style="bold cyan")
        commands.add_column("Command", style="bold")
        commands.add_column("Description")
        commands.add_row("/help", "查看帮助")
        commands.add_row("/clear", "清空当前 Agent 历史")
        commands.add_row("/exit", "退出 CLI")

        tool_table = Table(show_header=True, header_style="bold cyan")
        tool_table.add_column("Tool", style="bold")
        tool_table.add_column("Description")
        for tool in tools.iter_tools():
            tool_table.add_row(escape(tool.name), escape(tool.description))

        self.console.print(Panel(commands, title="Commands", border_style="cyan"))
        self.console.print(Panel(tool_table, title="Tools", border_style="green"))

    def info(self, text: str) -> None:
        from rich.markup import escape

        self.console.print(f"[dim]{escape(text)}[/dim]")

    def goodbye(self) -> None:
        self.console.print("[dim]bye[/dim]")

    def prompt(self) -> str:
        return self.console.input("\n[bold cyan]zzcode>[/bold cyan] ")

    def warning(self, text: str) -> None:
        self.render(SystemNotice(text=text, level="warning"))

    def error(self, text: str) -> None:
        self.render(SystemNotice(text=text, level="error"))


def create_ui() -> PlainUI:
    """创建可用的 CLI UI。

    优先返回 RichUI；如果本地没安装 Rich，则退回 PlainUI。
    """

    try:
        return RichUI()
    except ImportError:
        return PlainUI()
