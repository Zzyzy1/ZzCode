"""Structured Web Search tool via Bocha API."""

from __future__ import annotations

import os
from typing import Any

from zzcode.context import get_local_month_year
from zzcode.logging import log_debug, log_error
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolValidationResult
from zzcode.tools.local.search_session import WebSearchSession, WebSearchSessionResult
from zzcode.tools.results import ToolResult


DEFAULT_RESULT_COUNT = 10


class WebSearchTool(BaseTool):
    """通过博查 API 搜索网页，返回结构化搜索结果。"""

    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns titles, URLs, and snippets from search results. "
        "Use this tool for accessing information beyond your knowledge cutoff. "
        "For recent information, use the current date from the conversation context."
    )
    display_name = "Web Search"
    is_read_only = True
    is_concurrency_safe = True

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to use",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (1-20, default 10)",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def to_openai_tool(self) -> dict[str, Any]:
        """生成带当前年月提示的 WebSearch schema。"""

        current_month_year = get_local_month_year()
        description = (
            f"{self.description}\n\n"
            "IMPORTANT - Use the correct year in search queries:\n"
            f"- The current month is {current_month_year}. "
            "You MUST use this year when searching for recent information, documentation, "
            "or current events.\n"
            "- If the user asks about today, include the full current date from the "
            "conversation context in the query when it improves precision.\n"
            '- Example: if the user asks for "latest React docs", search for '
            '"React documentation" with the current year, NOT last year.\n\n'
            "CRITICAL REQUIREMENT - You MUST follow this after using web_search:\n"
            '- The final answer MUST include a "Sources:" section.\n'
            "- In that section, list relevant URLs from search results as markdown links: [Title](URL).\n"
            "- If the search results are insufficient, say the answer is uncertain and still include the sources checked."
        )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self.input_schema,
            },
        }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolValidationResult.failure("query must be a non-empty string")
        count = args.get("count")
        if count is not None and (not isinstance(count, int) or count < 1 or count > 20):
            return ToolValidationResult.failure("count must be an integer between 1 and 20")
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str = "") -> ToolResult:
        query = str(args["query"]).strip()
        count = int(args.get("count") or DEFAULT_RESULT_COUNT)
        tid = tool_call_id or context.tool_call_id

        api_key = os.getenv("BOCHA_API_KEY")
        if not api_key:
            return ToolResult.failure(
                tid,
                self.name,
                "BOCHA_API_KEY environment variable is not configured.",
            )

        log_debug(
            f"web search start query={query[:120]} count={count}",
            level="info",
            component="web_search",
        )

        session = WebSearchSession(api_key=api_key)
        search_result = session.search(query, count)
        if search_result.error:
            log_error(RuntimeError(search_result.error), component="web_search")
            return ToolResult.failure(
                tid,
                self.name,
                search_result.error,
                data=_search_result_data(tid, search_result),
                metadata={"reason": "web_search_error"},
            )
        if not search_result.hits:
            return ToolResult.success(
                tid,
                self.name,
                f'No results found for query: "{query}"',
                data=_search_result_data(tid, search_result),
            )

        # Format results for the LLM
        lines = [f'Search results for "{query}":', ""]
        for i, hit in enumerate(search_result.hits, 1):
            lines.append(f"## {i}. [{hit.title}]({hit.url})")
            if hit.site:
                lines[-1] += f" ({hit.site}"
                if hit.date:
                    lines[-1] += f", {hit.date}"
                lines[-1] += ")"
            elif hit.date:
                lines[-1] += f" ({hit.date})"
            if hit.snippet:
                # Truncate long snippets
                short = hit.snippet[:300].strip()
                if len(hit.snippet) > 300:
                    short += "..."
                lines.append(f"   {short}")
            lines.append("")

        lines.append(
            f"— {len(search_result.hits)} result(s) shown, approximately {search_result.total_estimated_matches} total matches. "
            "Use web_fetch to read full page content if needed."
        )
        lines.append("When answering with web information, cite the relevant source URLs from these results.")

        content = "\n".join(lines)

        log_debug(
            f"web search end query={query[:80]} results={len(search_result.hits)} chars={len(content)}",
            level="info",
            component="web_search",
        )

        return ToolResult.success(
            tid,
            self.name,
            content,
            data=_search_result_data(tid, search_result),
        )


def _search_result_data(tool_call_id: str, result: WebSearchSessionResult) -> dict[str, Any]:
    sources = result.sources
    return {
        "query": result.query,
        "results": [{"tool_use_id": tool_call_id, "content": sources}] if sources else [],
        "sources": sources,
        "totalEstimatedMatches": result.total_estimated_matches,
        "searchCount": result.search_count,
        "durationSeconds": result.duration_seconds,
        "exhausted": result.exhausted,
    }
