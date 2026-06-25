import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zzcode.agent.tool_call_agent import ToolCallAgent
from zzcode.llm.client import LLMResponse, LLMToolCall
from zzcode.tools.base import BaseTool
from zzcode.tools.local.shell import RunShellTool
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult
from zzcode.ui.messages import ToolUse


class RecordingWebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information."
    display_name = "Web Search"
    is_read_only = True
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.queries: list[str] = []

    def call(self, args, context, tool_call_id):
        self.queries.append(args["query"])
        return ToolResult.success(
            tool_call_id,
            self.name,
            "Search results for A股涨幅榜:\n## 1. [示例股票](https://example.com/stock)\nWhen answering with web information, cite the relevant source URLs from these results.",
            data={"sources": [{"title": "示例股票", "url": "https://example.com/stock"}]},
        )


class StockQueryChatClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, tools=None, temperature=0):
        self.calls.append({"messages": list(messages), "tools": tools, "temperature": temperature})
        if len(self.calls) == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_search",
                        name="web_search",
                        arguments={"query": "2026-06-24 A股 涨幅最高 股票"},
                    )
                ],
            )
        return LLMResponse(content="截至 2026-06-24，示例股票涨幅最高。来源：https://example.com/stock")


class CapturingRenderer:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def render(self, message) -> None:
        self.messages.append(message)


class Phase09RegressionTest(unittest.TestCase):
    def test_today_a_share_query_uses_dated_web_search_without_shell_date_probe(self) -> None:
        previous = os.environ.get("ZZCODE_OVERRIDE_DATE")
        os.environ["ZZCODE_OVERRIDE_DATE"] = "2026-06-24"
        web_search = RecordingWebSearchTool()
        llm = StockQueryChatClient()
        renderer = CapturingRenderer()
        try:
            with TemporaryDirectory() as tmp:
                agent = ToolCallAgent(
                    llm,
                    _registry(web_search, RunShellTool()),
                    Path(tmp),
                    renderer=renderer,
                )
                answer = agent.run("查一下今天涨幅最高的A股股票")
        finally:
            if previous is None:
                os.environ.pop("ZZCODE_OVERRIDE_DATE", None)
            else:
                os.environ["ZZCODE_OVERRIDE_DATE"] = previous

        self.assertIn("2026-06-24", answer)
        self.assertEqual(web_search.queries, ["2026-06-24 A股 涨幅最高 股票"])
        tool_uses = [message for message in renderer.messages if isinstance(message, ToolUse)]
        self.assertEqual([message.name for message in tool_uses], ["web_search"])
        first_messages = llm.calls[0]["messages"]
        self.assertIn("Today's date is 2026-06-24.", first_messages[-2]["content"])


def _registry(*tools: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


class BudgetConstrainedLLMClient:
    """模拟受预算约束的多轮联网搜索 LLM。"""

    def __init__(self, override_date: str, budget: int = 3) -> None:
        self.calls: list[dict[str, object]] = []
        self.override_date = override_date
        self.max_turns = budget + 1  # 预算用完后还有一次回答机会

    def chat(self, messages, tools=None, temperature=0):
        turn = len(self.calls)
        self.calls.append({"messages": list(messages), "tools": tools, "temperature": temperature})

        if turn >= self.max_turns:
            # 预算用尽后的最终回答
            return LLMResponse(
                content=(
                    "截至查询日期，我未能找到明确涨幅最高的个股排名。"
                    "搜索结果主要包含指数变动和涨停板统计，缺少精确的个股涨幅排序。"
                    "建议访问东方财富或同花顺等专业平台获取实时涨幅排名。\n\n"
                    "Sources:\n"
                    "- [示例来源](https://example.com/stock)"
                )
            )

        # 模拟多轮搜索，query 带日期
        queries = [
            f"{self.override_date} A股 涨幅最高 股票 今日涨幅榜",
            f"site:eastmoney.com {self.override_date} 个股涨幅排名",
            f"{self.override_date} A股 涨停板 涨幅排名 前十",
        ]
        query = queries[min(turn, len(queries) - 1)]
        return LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id=f"call_search_{turn}",
                    name="web_search",
                    arguments={"query": query},
                )
            ],
        )


class Phase09BudgetConvergenceTest(unittest.TestCase):
    """步骤 32：验证联网工具预算耗尽后 Agent 收敛，不无限循环或超时。"""

    def test_web_search_converges_within_budget_no_timeout(self) -> None:
        """联网工具预算用尽后 Agent 应在有限步内给出回答或不确定。"""
        previous_date = os.environ.get("ZZCODE_OVERRIDE_DATE")
        previous_budget = os.environ.get("ZZCODE_WEB_TOOL_BUDGET")
        os.environ["ZZCODE_OVERRIDE_DATE"] = "2026-06-24"
        os.environ["ZZCODE_WEB_TOOL_BUDGET"] = "3"

        web_search = RecordingWebSearchTool()
        llm = BudgetConstrainedLLMClient(override_date="2026-06-24", budget=3)
        renderer = CapturingRenderer()
        try:
            with TemporaryDirectory() as tmp:
                agent = ToolCallAgent(
                    llm,
                    _registry(web_search, RunShellTool()),
                    Path(tmp),
                    renderer=renderer,
                )
                answer = agent.run("查一下今天涨幅最高的A股股票")
        finally:
            if previous_date is None:
                os.environ.pop("ZZCODE_OVERRIDE_DATE", None)
            else:
                os.environ["ZZCODE_OVERRIDE_DATE"] = previous_date
            if previous_budget is None:
                os.environ.pop("ZZCODE_WEB_TOOL_BUDGET", None)
            else:
                os.environ["ZZCODE_WEB_TOOL_BUDGET"] = previous_budget

        # 验证 1：每次搜索 query 都包含当前日期
        for query in web_search.queries:
            self.assertIn("2026-06-24", query, f"Query should contain date: {query}")

        # 验证 2：搜索次数不超过预算
        self.assertLessEqual(
            len(web_search.queries), 3,
            f"Web search count {len(web_search.queries)} should not exceed budget 3"
        )

        # 验证 3：最终回答非空（Agent 收敛了）
        self.assertTrue(answer, "Agent should produce a final answer after budget exhausted")

        # 验证 4：工具轨迹中只包含 web_search，不包含 shell/run_shell
        tool_uses = [message for message in renderer.messages if isinstance(message, ToolUse)]
        tool_names = [message.name for message in tool_uses]
        self.assertNotIn("run_shell", tool_names, "Should not call shell for date probing")
        self.assertNotIn("run_powershell", tool_names, "Should not call powershell for date probing")
        self.assertTrue(
            all(name == "web_search" for name in tool_names),
            f"All tool calls should be web_search, got: {tool_names}"
        )

        # 验证 5：user context 包含日期
        first_messages = llm.calls[0]["messages"]
        context_texts = [str(m.get("content", "")) for m in first_messages if isinstance(m, dict)]
        date_found = any("Today's date is 2026-06-24" in text for text in context_texts)
        self.assertTrue(date_found, "First turn messages should include date context")

    def test_web_budget_exhausted_agent_stops_searching(self) -> None:
        """预算耗尽后 Agent 不再尝试新的联网工具调用（由 reserve 返回收敛结果）。"""
        previous_budget = os.environ.get("ZZCODE_WEB_TOOL_BUDGET")
        os.environ["ZZCODE_WEB_TOOL_BUDGET"] = "1"

        web_search = RecordingWebSearchTool()
        llm = BudgetConstrainedLLMClient(override_date="2026-06-24", budget=1)
        renderer = CapturingRenderer()
        try:
            with TemporaryDirectory() as tmp:
                agent = ToolCallAgent(
                    llm,
                    _registry(web_search, RunShellTool()),
                    Path(tmp),
                    renderer=renderer,
                )
                answer = agent.run("今天涨幅最高的A股股票")
        finally:
            if previous_budget is None:
                os.environ.pop("ZZCODE_WEB_TOOL_BUDGET", None)
            else:
                os.environ["ZZCODE_WEB_TOOL_BUDGET"] = previous_budget

        # 预算为 1，最多 1 次 web_search
        self.assertLessEqual(len(web_search.queries), 1)
        self.assertTrue(answer, "Agent should produce an answer even with budget=1")

        # 不应调用 shell
        tool_uses = [message for message in renderer.messages if isinstance(message, ToolUse)]
        tool_names = [message.name for message in tool_uses]
        self.assertNotIn("run_shell", tool_names)


if __name__ == "__main__":
    unittest.main()
