"""Structured Web Search tool via Bocha API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from zzcode.logging import log_debug, log_error
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolValidationResult
from zzcode.tools.results import ToolResult


BOCHA_SEARCH_URL = "https://api.bocha.cn/v1/web-search"
DEFAULT_RESULT_COUNT = 10


class WebSearchTool(BaseTool):
    """通过博查 API 搜索网页，返回结构化搜索结果。"""

    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns titles, URLs, and snippets from search results. "
        "Use this tool for accessing information beyond your knowledge cutoff."
    )
    display_name = "Web Search"
    is_read_only = True

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

        try:
            payload = json.dumps({"query": query, "count": count, "summary": True}).encode("utf-8")
            request = urllib.request.Request(
                url=BOCHA_SEARCH_URL,
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            log_error(exc, component="web_search", context={"status": exc.code, "body": error_body})
            return ToolResult.failure(
                tid,
                self.name,
                f"Search API returned HTTP {exc.code}: {error_body[:300]}",
            )
        except Exception as exc:
            log_error(exc, component="web_search")
            return ToolResult.failure(
                tid,
                self.name,
                f"Search request failed: {exc}",
            )

        code = body.get("code")
        if code != 200:
            msg = body.get("msg") or body.get("message") or "unknown error"
            return ToolResult.failure(
                tid,
                self.name,
                f"Search API error: {msg}",
            )

        data = body.get("data") or {}
        web_pages = data.get("webPages") or {}
        results = web_pages.get("value") or []

        if not results:
            return ToolResult.success(
                tid,
                self.name,
                f'No results found for query: "{query}"',
            )

        # Format results for the LLM
        lines = [f'Search results for "{query}":', ""]
        for i, item in enumerate(results, 1):
            title = item.get("name") or "Untitled"
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            site = item.get("siteName") or ""
            date = item.get("datePublished") or ""

            lines.append(f"## {i}. [{title}]({url})")
            if site:
                lines[-1] += f" ({site}"
                if date:
                    lines[-1] += f", {date[:10]}"
                lines[-1] += ")"
            elif date:
                lines[-1] += f" ({date[:10]})"
            if snippet:
                # Truncate long snippets
                short = snippet[:300].strip()
                if len(snippet) > 300:
                    short += "..."
                lines.append(f"   {short}")
            lines.append("")

        total = web_pages.get("totalEstimatedMatches", len(results))
        lines.append(
            f"— {len(results)} result(s) shown, approximately {total} total matches. "
            "Use web_fetch to read full page content if needed."
        )

        content = "\n".join(lines)

        log_debug(
            f"web search end query={query[:80]} results={len(results)} chars={len(content)}",
            level="info",
            component="web_search",
        )

        return ToolResult.success(tid, self.name, content)
