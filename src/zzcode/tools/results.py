"""Structured tool results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    """表示一次工具调用的结构化结果。

    tool_call_id 对应模型返回的调用 id；content 是回灌给模型的文本。
    """

    tool_call_id: str
    tool_name: str
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        tool_call_id: str,
        tool_name: str,
        content: str,
        *,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        """构造成功工具结果。"""

        return cls(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            ok=True,
            content=content,
            data=data or {},
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        tool_call_id: str,
        tool_name: str,
        error: str,
        *,
        content: str | None = None,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        """构造失败工具结果。"""

        return cls(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            ok=False,
            content=content or error,
            data=data or {},
            error=error,
            metadata=metadata or {},
        )

    def to_openai_message(self) -> dict[str, Any]:
        """转换为 OpenAI-compatible tool result message。"""

        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.tool_name,
            "content": self.content,
        }
