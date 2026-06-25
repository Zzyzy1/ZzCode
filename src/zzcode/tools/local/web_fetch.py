"""Structured Web Fetch tool for fetching and extracting URL content."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request

from zzcode.logging import log_debug, log_error
from zzcode.tools.base import BaseTool, JsonObject, ToolContext, ToolPermissionResult, ToolValidationResult
from zzcode.tools.local.web_fetch_cache import WEB_FETCH_CACHE, WebFetchCacheEntry
from zzcode.tools.local.web_fetch_extract import DEFAULT_MAX_EXTRACTED_TEXT_LENGTH, extract_fetch_text
from zzcode.tools.local.web_fetch_http import (
    MAX_REDIRECTS,
    REDIRECT_STATUS_CODES,
    NormalizedFetchUrl,
    is_permitted_redirect,
    normalize_fetch_url,
    resolve_redirect_url,
)
from zzcode.tools.local.web_fetch_preapproved import is_preapproved_url
from zzcode.tools.local.web_fetch_summarizer import ExtractiveWebFetchSummarizer, WebFetchSummarizer
from zzcode.tools.results import ToolResult


MAX_HTTP_BODY_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = DEFAULT_MAX_EXTRACTED_TEXT_LENGTH
FETCH_TIMEOUT = 60
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
        try:
            normalize_fetch_url(url)
        except ValueError as exc:
            return ToolValidationResult.failure(str(exc))

        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolValidationResult.failure("prompt must be a non-empty string")
        return ToolValidationResult.success()

    def check_permission(self, args: JsonObject, context: ToolContext) -> ToolPermissionResult:
        """按 Claude WebFetch 思路对非预批准域名请求权限。"""

        rule = _web_fetch_domain_rule(args)
        url = str(args.get("url") or "").strip()
        if url and is_preapproved_url(url):
            return ToolPermissionResult.allow(reason="web_fetch_preapproved_domain")
        return ToolPermissionResult.ask(
            f"Web Fetch wants to access {rule or 'this domain'}.",
            reason="web_fetch_domain_permission",
        )

    def permission_summary(self, args: JsonObject) -> str:
        """生成 domain 级 WebFetch 权限摘要。"""

        rule = _web_fetch_domain_rule(args)
        if rule:
            return f"Web Fetch wants to access {rule}"
        return "Web Fetch wants to access this URL"

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str = "") -> ToolResult:
        url = str(args["url"]).strip()
        prompt = str(args["prompt"]).strip()
        tid = tool_call_id or context.tool_call_id
        tool_name = self.name

        start_time = time.perf_counter()
        normalized_url = normalize_fetch_url(url)

        log_debug(
            f"web fetch start url={normalized_url.request_url[:120]} prompt={prompt[:80]}",
            level="info",
            component="web_fetch",
        )

        cached = WEB_FETCH_CACHE.get(normalized_url.original_url)
        cache_hit = cached is not None
        if cached is not None:
            final_url = cached.url
            content_type = cached.content_type
            bytes_count = cached.bytes_count
            text = cached.text
            original_len = cached.original_text_chars
            text_truncated = cached.text_truncated
        else:
            fetched = _fetch_and_extract(normalized_url.request_url)
            if not fetched.ok:
                if fetched.redirect_url:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return _build_redirect_result(
                        tid=tid,
                        tool_name=tool_name,
                        prompt=prompt,
                        normalized_url=normalized_url,
                        fetched=fetched,
                        duration_ms=elapsed_ms,
                    )
                return ToolResult.failure(
                    tid,
                    tool_name,
                    fetched.error or f"Failed to fetch {normalized_url.request_url}",
                    data={
                        "originalUrl": normalized_url.original_url,
                        "requestUrl": normalized_url.request_url,
                        "upgraded": normalized_url.upgraded,
                        "limitBytes": fetched.limit_bytes,
                        "timeoutSeconds": FETCH_TIMEOUT,
                    },
                    metadata={
                        "httpsUpgraded": normalized_url.upgraded,
                        "cacheHit": False,
                        "reason": fetched.error_reason or "web_fetch_failed",
                    },
                )

            final_url = fetched.url
            content_type = fetched.content_type
            bytes_count = fetched.bytes_count
            text = fetched.text
            original_len = fetched.original_text_chars
            text_truncated = fetched.text_truncated

            WEB_FETCH_CACHE.set(
                normalized_url.original_url,
                WebFetchCacheEntry(
                    url=final_url,
                    content_type=content_type,
                    bytes_count=bytes_count,
                    text=text,
                    original_text_chars=original_len,
                    text_truncated=text_truncated,
                    size_bytes=max(1, len(text.encode("utf-8", errors="replace"))),
                ),
            )

        is_preapproved = is_preapproved_url(final_url)
        summary = _summarize_fetch_result(
            context=context,
            prompt=prompt,
            content=text,
            content_type=content_type,
            is_preapproved_domain=is_preapproved,
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Step 4: Return content with the prompt for the LLM to act on
        # Claude WebFetch 会先把网页内容按 prompt 提取/压缩，再回灌主模型。
        result_lines = [
            f"Fetched URL: {final_url}",
            f"Content-Type: {content_type or 'unknown'}",
            f"Size: {bytes_count} bytes ({original_len} chars after text extraction; {summary.result_chars} chars returned)",
            f"Duration: {elapsed_ms:.0f}ms",
            "",
            "--- Extracted Content ---",
            "",
            summary.text,
            "",
            "--- End of Extracted Content ---",
            "",
            f'Prompt: "{prompt}"',
        ]

        content = "\n".join(result_lines)

        log_debug(
            f"web fetch end url={final_url[:80]} bytes={bytes_count} chars={original_len} elapsed_ms={elapsed_ms:.0f}",
            level="info",
            component="web_fetch",
        )

        return ToolResult.success(
            tid,
            tool_name,
            content,
            data={
                "url": final_url,
                "originalUrl": normalized_url.original_url,
                "requestUrl": normalized_url.request_url,
                "upgraded": normalized_url.upgraded,
                "bytes": bytes_count,
                "contentType": content_type or "unknown",
                "durationMs": elapsed_ms,
                "cacheHit": cache_hit,
                "textTruncated": text_truncated,
                "maxTextLength": MAX_TEXT_LENGTH,
                "summarySource": summary.source,
                "summaryChars": summary.result_chars,
                "summaryTruncated": summary.truncated,
                "extractedTextChars": summary.original_chars,
                "preapproved": is_preapproved,
            },
            metadata={
                "httpsUpgraded": normalized_url.upgraded,
                "cacheHit": cache_hit,
                "textTruncated": text_truncated,
                "summarySource": summary.source,
                "summaryTruncated": summary.truncated,
                "preapproved": is_preapproved,
            },
        )


class _FetchedPage:
    """封装一次 HTTP 抓取和文本转换结果。"""

    def __init__(
        self,
        *,
        ok: bool,
        url: str = "",
        content_type: str = "",
        bytes_count: int = 0,
        text: str = "",
        original_text_chars: int = 0,
        text_truncated: bool = False,
        error: str | None = None,
        error_reason: str | None = None,
        limit_bytes: int | None = None,
        raw_bytes: bytes = b"",
        redirect_url: str = "",
        redirect_status: int = 0,
    ) -> None:
        self.ok = ok
        self.url = url
        self.content_type = content_type
        self.bytes_count = bytes_count
        self.text = text
        self.original_text_chars = original_text_chars
        self.text_truncated = text_truncated
        self.error = error
        self.error_reason = error_reason
        self.limit_bytes = limit_bytes
        self.raw_bytes = raw_bytes
        self.redirect_url = redirect_url
        self.redirect_status = redirect_status


def _fetch_and_extract(url: str) -> _FetchedPage:
    """抓取 URL 并转换为 WebFetch 可回灌的文本。"""

    fetched = _fetch_url_with_redirects(url)
    if not fetched.ok:
        return fetched

    raw_bytes = fetched.raw_bytes
    content_type = fetched.content_type
    final_url = fetched.url
    bytes_count = len(raw_bytes)
    extracted = extract_fetch_text(raw_bytes, content_type, max_text_length=MAX_TEXT_LENGTH)

    return _FetchedPage(
        ok=True,
        url=final_url,
        content_type=content_type,
        bytes_count=bytes_count,
        text=extracted.text,
        original_text_chars=extracted.original_text_chars,
        text_truncated=extracted.text_truncated,
    )


def _fetch_url_with_redirects(url: str, depth: int = 0) -> _FetchedPage:
    """抓取 URL，并只自动跟随允许的 redirect。"""

    if depth > MAX_REDIRECTS:
        return _FetchedPage(
            ok=False,
            error=f"Too many redirects fetching {url}; exceeded {MAX_REDIRECTS}",
            error_reason="web_fetch_too_many_redirects",
        )

    try:
        request = urllib.request.Request(url=url, headers=HTTP_HEADERS, method="GET")
        with _open_url_no_redirect(request, timeout=FETCH_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type") or ""
            raw_bytes = _read_limited_response_body(response)
            final_url = response.geturl()

    except urllib.error.HTTPError as exc:
        if exc.code in REDIRECT_STATUS_CODES:
            location = exc.headers.get("Location")
            if not location:
                return _FetchedPage(
                    ok=False,
                    error=f"Redirect from {url} missing Location header",
                    error_reason="web_fetch_redirect_missing_location",
                )
            redirect_url = resolve_redirect_url(url, location)
            if is_permitted_redirect(url, redirect_url):
                return _fetch_url_with_redirects(redirect_url, depth + 1)
            return _FetchedPage(
                ok=False,
                url=url,
                error_reason="web_fetch_redirect",
                redirect_url=redirect_url,
                redirect_status=exc.code,
            )

        log_error(exc, component="web_fetch", context={"url": url, "status": exc.code})
        return _FetchedPage(ok=False, error=f"HTTP {exc.code} when fetching {url}", error_reason="web_fetch_http_error")
    except urllib.error.URLError as exc:
        log_error(exc, component="web_fetch", context={"url": url})
        if _is_timeout_reason(exc.reason):
            return _FetchedPage(
                ok=False,
                error=f"Timed out fetching {url} after {FETCH_TIMEOUT} seconds",
                error_reason="web_fetch_timeout",
            )
        return _FetchedPage(ok=False, error=f"Failed to connect to {url}: {exc.reason}", error_reason="web_fetch_url_error")
    except (TimeoutError, socket.timeout) as exc:
        log_error(exc, component="web_fetch", context={"url": url})
        return _FetchedPage(
            ok=False,
            error=f"Timed out fetching {url} after {FETCH_TIMEOUT} seconds",
            error_reason="web_fetch_timeout",
        )
    except _BodyTooLargeError as exc:
        log_error(exc, component="web_fetch", context={"url": url, "limit_bytes": MAX_HTTP_BODY_BYTES})
        return _FetchedPage(
            ok=False,
            error=f"Response body from {url} exceeds maximum size of {MAX_HTTP_BODY_BYTES} bytes",
            error_reason="web_fetch_body_too_large",
            limit_bytes=MAX_HTTP_BODY_BYTES,
        )
    except Exception as exc:
        log_error(exc, component="web_fetch", context={"url": url})
        return _FetchedPage(ok=False, error=f"Unexpected error fetching {url}: {exc}", error_reason="web_fetch_unexpected_error")

    return _FetchedPage(
        ok=True,
        url=final_url,
        content_type=content_type,
        raw_bytes=raw_bytes,
    )


def _summarize_fetch_result(
    *,
    context: ToolContext,
    prompt: str,
    content: str,
    content_type: str,
    is_preapproved_domain: bool,
):
    """按 prompt 提取 WebFetch 结果，优先使用注入的 secondary summarizer。"""

    candidate = context.metadata.get("web_fetch_summarizer")
    summarizer: WebFetchSummarizer
    if candidate is not None and hasattr(candidate, "summarize"):
        summarizer = candidate
    else:
        summarizer = ExtractiveWebFetchSummarizer()
    return summarizer.summarize(
        prompt=prompt,
        content=content,
        content_type=content_type,
        is_preapproved_domain=is_preapproved_domain,
    )


def _web_fetch_domain_rule(args: JsonObject) -> str:
    """从 WebFetch 输入生成 Claude 风格 domain rule。"""

    url = str(args.get("url") or "").strip()
    if not url:
        return ""
    try:
        normalized = normalize_fetch_url(url)
    except ValueError:
        return ""
    return f"domain:{normalized.hostname}"


class _BodyTooLargeError(Exception):
    """表示 HTTP body 超过 WebFetch 允许的最大字节数。"""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁用 urllib 默认 redirect，让 WebFetch 自己判断是否允许跟随。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_url_no_redirect(request: urllib.request.Request, timeout: int):
    """以禁用自动 redirect 的方式打开 URL。"""

    opener = urllib.request.build_opener(_NoRedirectHandler)
    return opener.open(request, timeout=timeout)


def _build_redirect_result(
    *,
    tid: str,
    tool_name: str,
    prompt: str,
    normalized_url: NormalizedFetchUrl,
    fetched: _FetchedPage,
    duration_ms: float,
) -> ToolResult:
    """构造跨 host redirect 的 Claude 风格结果。"""

    status_text = _redirect_status_text(fetched.redirect_status)
    message = "\n".join(
        [
            "REDIRECT DETECTED: The URL redirects to a different host.",
            "",
            f"Original URL: {fetched.url}",
            f"Redirect URL: {fetched.redirect_url}",
            f"Status: {fetched.redirect_status} {status_text}",
            "",
            "To complete your request, use WebFetch again with these parameters:",
            f'- url: "{fetched.redirect_url}"',
            f'- prompt: "{prompt}"',
        ]
    )

    return ToolResult.success(
        tid,
        tool_name,
        message,
        data={
            "url": normalized_url.original_url,
            "originalUrl": normalized_url.original_url,
            "requestUrl": normalized_url.request_url,
            "redirectUrl": fetched.redirect_url,
            "redirectStatus": fetched.redirect_status,
            "code": fetched.redirect_status,
            "codeText": status_text,
            "bytes": len(message.encode("utf-8")),
            "durationMs": duration_ms,
            "cacheHit": False,
            "redirect": True,
        },
        metadata={
            "httpsUpgraded": normalized_url.upgraded,
            "cacheHit": False,
            "redirect": True,
            "reason": "web_fetch_redirect",
        },
    )


def _redirect_status_text(status: int) -> str:
    """返回常见 redirect 状态文本。"""

    if status == 301:
        return "Moved Permanently"
    if status == 307:
        return "Temporary Redirect"
    if status == 308:
        return "Permanent Redirect"
    return "Found"


def _read_limited_response_body(response) -> bytes:
    """读取 HTTP body，并在超过 10MB 时中断。"""

    body = response.read(MAX_HTTP_BODY_BYTES + 1)
    if len(body) > MAX_HTTP_BODY_BYTES:
        raise _BodyTooLargeError()
    return body


def _is_timeout_reason(reason: object) -> bool:
    """判断 urllib 包装的错误是否是超时。"""

    return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()
