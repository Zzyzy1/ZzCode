"""Simple text-action tool executor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


ToolFunc = Callable[[str], str]


@dataclass(frozen=True)
class RegisteredTool:
    """注册到 Agent 的工具描述。

    name 是模型调用名；description 会进入提示词；func 接收字符串参数并返回文本。
    """

    name: str
    description: str
    func: ToolFunc
    display_name: str | None = None


class ToolExecutor:
    """工具注册表和执行入口。

    负责把工具暴露给提示词，并根据模型 Action 中的工具名执行对应函数。
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        func: ToolFunc,
        display_name: str | None = None,
    ) -> None:
        """注册一个工具。

        name/description 给模型识别工具；func 是本地执行函数；display_name 用于 UI 展示。
        """

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
        """按名称获取完整工具描述。

        name 是工具名；返回 RegisteredTool，找不到时返回 None。
        """

        return self._tools.get(name)

    def get_tool(self, name: str) -> ToolFunc | None:
        """按名称获取工具执行函数。

        name 是工具名；返回可调用函数，找不到时返回 None。
        """

        tool = self._tools.get(name)
        return tool.func if tool else None

    def get_available_tools(self) -> str:
        """生成写入 ReAct 提示词的工具说明。

        返回多行文本，每行包含工具名和用途。
        """

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
        """执行模型请求的工具。

        name 是工具名；tool_input 是 Action 方括号中的文本；返回工具结果文本。
        """

        tool = self.get_tool(name)
        if tool is None:
            return f"Error: tool '{name}' was not found."

        # 工具异常转成 Observation 文本，让模型有机会调整下一步，而不是中断 CLI。
        try:
            return str(tool(tool_input))
        except Exception as exc:
            return f"Error while running tool '{name}': {exc}"
