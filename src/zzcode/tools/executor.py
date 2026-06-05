"""Simple text-action tool executor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


ToolFunc = Callable[[str], str]


@dataclass(frozen=True)
class RegisteredTool:
    """A tool available to the text ReAct agent."""

    name: str
    description: str
    func: ToolFunc
    display_name: str | None = None


class ToolExecutor:
    """Register and execute tools by name."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        func: ToolFunc,
        display_name: str | None = None,
    ) -> None:
        if not name:
            raise ValueError("Tool name cannot be empty.")
        if not callable(func):
            raise TypeError("Tool func must be callable.")

        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            func=func,
            display_name=display_name,
        )

    def get_registered_tool(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def get_tool(self, name: str) -> ToolFunc | None:
        tool = self._tools.get(name)
        return tool.func if tool else None

    def get_available_tools(self) -> str:
        if not self._tools:
            return "(no tools registered)"
        return "\n".join(
            f"- {tool.name}: {tool.description}" for tool in self._tools.values()
        )

    def iter_tools(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def tool_names_text(self) -> str:
        if not self._tools:
            return "(none)"
        return ", ".join(self._tools)

    def execute(self, name: str, tool_input: str) -> str:
        tool = self.get_tool(name)
        if tool is None:
            return f"Error: tool '{name}' was not found."

        try:
            return str(tool(tool_input))
        except Exception as exc:
            return f"Error while running tool '{name}': {exc}"
