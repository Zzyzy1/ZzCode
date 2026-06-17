"""Structured tool registry."""

from __future__ import annotations

from collections import OrderedDict

from .base import Tool


class ToolRegistry:
    """管理结构化工具集合。

    registry 只负责注册、查找和 schema 输出，不负责权限和执行。
    """

    def __init__(self) -> None:
        self._tools: OrderedDict[str, Tool] = OrderedDict()

    def register(self, tool: Tool) -> None:
        """注册一个结构化工具。"""

        name = getattr(tool, "name", "")
        if not name:
            raise ValueError("Tool name cannot be empty.")
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称查找工具。"""

        return self._tools.get(name)

    def list(self) -> list[Tool]:
        """按注册顺序返回工具列表。"""

        return list(self._tools.values())

    def iter_tools(self) -> list[Tool]:
        """兼容 CLI UI 的工具迭代接口。"""

        return self.list()

    def tool_names_text(self) -> str:
        """返回用于 CLI 展示的工具名列表。"""

        if not self._tools:
            return "(none)"
        return ", ".join(self._tools)

    def get_available_tools(self) -> str:
        """返回用于帮助信息的工具说明。"""

        if not self._tools:
            return "(no tools registered)"
        return "\n".join(
            f"- {tool.name}: {tool.description}" for tool in self._tools.values()
        )

    def to_openai_tools(self) -> list[dict]:
        """生成 OpenAI-compatible tools schema。"""

        return [tool.to_openai_tool() for tool in self._tools.values()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
