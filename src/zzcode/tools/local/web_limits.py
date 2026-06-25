"""联网工具预算和收敛提示。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from zzcode.tools.results import ToolResult


WEB_TOOL_NAMES = {"web_search", "web_fetch"}
DEFAULT_WEB_TOOL_BUDGET = 8
WEB_TOOL_BUDGET_ENV = "ZZCODE_WEB_TOOL_BUDGET"


@dataclass
class WebToolBudget:
    """记录一次 Agent turn 内 WebSearch/WebFetch 的使用预算。"""

    max_uses: int = DEFAULT_WEB_TOOL_BUDGET
    used: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "WebToolBudget":
        """从环境变量读取联网工具预算。"""

        raw = os.getenv(WEB_TOOL_BUDGET_ENV)
        if raw is None:
            return cls()
        try:
            value = int(raw)
        except ValueError:
            return cls()
        return cls(max_uses=max(0, value))

    def should_track(self, tool_name: str) -> bool:
        """判断工具是否消耗联网预算。"""

        return tool_name in WEB_TOOL_NAMES

    def reserve(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult | None:
        """尝试占用一次联网预算，超限时返回收敛 tool result。"""

        if not self.should_track(tool_name):
            return None
        if self.used >= self.max_uses:
            return _web_budget_exhausted_result(tool_name, arguments, self)
        self.used += 1
        self.calls.append(_summarize_web_call(tool_name, arguments))
        return None


def _summarize_web_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "web_search":
        return {"tool": tool_name, "query": str(arguments.get("query") or "")}
    if tool_name == "web_fetch":
        return {"tool": tool_name, "url": str(arguments.get("url") or "")}
    return {"tool": tool_name}


def _web_budget_exhausted_result(tool_name: str, arguments: dict[str, Any], budget: WebToolBudget) -> ToolResult:
    attempted = _summarize_web_call(tool_name, arguments)
    lines = [
        "Web tool budget exhausted for this turn.",
        f"Budget: {budget.used}/{budget.max_uses} web tool calls already used.",
        f"Attempted next call: {attempted}",
        "",
        "Stop searching or fetching new pages now. Based on the sources and tool results already available,",
        "answer the user with the best supported conclusion. If the evidence is insufficient, say so clearly",
        "and include a Sources section with the relevant URLs already found.",
    ]
    return ToolResult.success(
        "",
        tool_name,
        "\n".join(lines),
        data={
            "budget_used": budget.used,
            "budget_max": budget.max_uses,
            "attempted": attempted,
            "previous_calls": list(budget.calls),
        },
        metadata={"reason": "web_tool_budget_exhausted"},
    )
