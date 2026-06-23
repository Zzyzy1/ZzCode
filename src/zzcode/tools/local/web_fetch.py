"""Structured Web Fetch tool for fetching and extracting URL content."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from zzcode.logging import log_debug, log_error
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolValidationResult
from zzcode.tools.results import ToolResult


MAX_CONTENT_LENGTH = 100_000
MAX_URL_LENGTH = 2000
FETCH_TIMEOUT = 30
HTTP_HEADERS = {
    "User-Agent": "ZzCode/0.1 (AI Agent; +https://github.com/ZzCode)",
    "Accept": "text/html, text/plain, application/json, */*",
}


class WebFetchTool(BaseTool):
    """抓取 URL 内容，提取文本并可选地按 prompt 做摘要。"""

    name = "web_fetch"
    description = (
        "Fetch and extract content from a URL. "
        "Converts HTML pages to plain text. "
        "Use this to read the full content of pages found by web_search. "
        "IMPORTANT: Will fail for authenticated/private URLs."
    )
    display_name = "Web Fetch"
    is_read_only = True

    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch content from",
            },
            "prompt": {
                "type": "string",
                "description": "What information to extract from the page (e.g., 'Summarize the main points')",
            },
        },
        "required": ["url", "prompt"],
        "additionalProperties": False,
    }

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        url = args.get("url")
        if not isinstance(url, str) or not url.strip():
            return ToolValidationResult.failure("url must be a non-empty string")
        if len(url) > MAX_URL_LENGTH:
            return ToolValidationResult.failure(f"URL exceeds maximum length of {MAX_URL_LENGTH}")
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme not in ("http", "https"):
                return ToolValidationResult.failure("URL must use http or https scheme")
            if not parsed.hostname or "." not in parsed.hostname:
                return ToolValidationResult.failure("URL must have a valid hostname")
            if parsed.username or parsed.password:
                return ToolValidationResult.failure("URL must not contain credentials")
        except Exception:
            return ToolValidationResult.failure("Invalid URL format")

        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolValidationResult.failure("prompt must be a non-empty string")
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str = "") -> ToolResult:
        url = str(args["url"]).strip()
        prompt = str(args["prompt"]).strip()
        tid = tool_call_id or context.tool_call_id
        tool_name = self.name

        start_time = time.perf_counter()

        log_debug(
            f"web fetch start url={url[:120]} prompt={prompt[:80]}",
            level="info",
            component="web_fetch",
        )

        # Step 1: Fetch the URL
        try:
            # Upgrade HTTP → HTTPS
            if url.startswith("http://"):
                url = "https://" + url[7:]

            request = urllib.request.Request(url=url, headers=HTTP_HEADERS, method="GET")
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
                content_type = response.headers.get("Content-Type") or ""
                raw_bytes = response.read()

                # Handle redirects (urllib follows 3xx by default)
                final_url = response.geturl()
                if final_url != url:
                    url = final_url

        except urllib.error.HTTPError as exc:
            log_error(exc, component="web_fetch", context={"url": url, "status": exc.code})
            return ToolResult.failure(
                tid,
                tool_name,
                f"HTTP {exc.code} when fetching {url}",
            )
        except urllib.error.URLError as exc:
            log_error(exc, component="web_fetch", context={"url": url})
            return ToolResult.failure(
                tid,
                tool_name,
                f"Failed to connect to {url}: {exc.reason}",
            )
        except Exception as exc:
            log_error(exc, component="web_fetch", context={"url": url})
            return ToolResult.failure(
                tid,
                tool_name,
                f"Unexpected error fetching {url}: {exc}",
            )

        bytes_count = len(raw_bytes)

        # Step 2: Convert to text
        try:
            raw_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            raw_text = raw_bytes.decode("latin-1", errors="replace")

        is_html = "text/html" in content_type.lower() or (
            len(raw_text) > 20 and _looks_like_html(raw_text)
        )

        if is_html:
            text = _strip_html(raw_text)
        else:
            text = raw_text

        # Step 3: Truncate to avoid overwhelming context
        original_len = len(text)
        if original_len > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated due to length...]"

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Step 4: Return content with the prompt for the LLM to act on
        # The model will read this result and apply the prompt itself
        result_lines = [
            f"Fetched URL: {url}",
            f"Content-Type: {content_type or 'unknown'}",
            f"Size: {bytes_count} bytes ({original_len} chars after text extraction)",
            f"Duration: {elapsed_ms:.0f}ms",
            "",
            "--- Content ---",
            "",
            text,
            "",
            "--- End of Content ---",
            "",
            f'Prompt: "{prompt}"',
            "Please apply the above prompt to the fetched content and provide your analysis.",
        ]

        content = "\n".join(result_lines)

        log_debug(
            f"web fetch end url={url[:80]} bytes={bytes_count} chars={original_len} elapsed_ms={elapsed_ms:.0f}",
            level="info",
            component="web_fetch",
        )

        return ToolResult.success(tid, tool_name, content)


def _looks_like_html(text: str) -> bool:
    """Quick heuristic to detect HTML content."""
    head = text[:200].lower().strip()
    return bool(
        re.search(r"<!doctype\s+html", head)
        or re.search(r"<html[\s>]", head)
        or re.search(r"<head[\s>]", head)
        or re.search(r"<body[\s>]", head)
    )


def _strip_html(html: str) -> str:
    """Convert HTML to plain text using simple regex-based stripping."""
    # Remove scripts and styles
    for tag in ("script", "style", "noscript", "iframe", "svg", "nav", "footer"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Replace block elements with newlines
    for tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "section", "article", "header"):
        html = re.sub(rf"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    html = re.sub(r"<[^>]+>", "", html)

    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'")
    html = html.replace("&nbsp;", " ").replace("&#160;", " ")

    # Collapse whitespace
    html = re.sub(r" +", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"^\s+", "", html)

    return html.strip()
