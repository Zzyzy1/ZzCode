import os
import urllib.error
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zzcode.tools.base import ToolCall, ToolContext
from zzcode.tools.builtin import build_builtin_tool_registry
from zzcode.tools.local.search_session import WebSearchSession
from zzcode.tools.local.web_fetch import MAX_HTTP_BODY_BYTES, MAX_TEXT_LENGTH, WebFetchTool
from zzcode.tools.local.web_fetch_cache import WebFetchCache, WebFetchCacheEntry, clear_web_fetch_cache
from zzcode.tools.local.web_fetch_extract import extract_fetch_text, looks_like_html, strip_html
from zzcode.tools.local.web_fetch_preapproved import is_preapproved_url
from zzcode.tools.local.web_fetch_summarizer import LLMWebFetchSummarizer, WebFetchSummary, build_web_fetch_summary_prompt
from zzcode.tools.local.web_search import WebSearchTool
from zzcode.tools.local.search import GlobTool, GrepTool
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.runner import ToolRunner


class SearchToolTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_web_fetch_cache()

    def test_builtin_registry_contains_search_tools_before_read_file(self) -> None:
        registry = build_builtin_tool_registry()

        self.assertEqual(
            [tool.name for tool in registry.list()],
            [
                "list_files",
                "glob",
                "grep",
                "read_file",
                "write_file",
                "edit_file",
                "append_file",
                "run_shell",
                "run_powershell",
                "web_search",
                "web_fetch",
            ],
        )

    def test_glob_finds_file_inside_project(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests" / "tool_test").mkdir(parents=True)
            (root / "tests" / "tool_test" / "1.txt").write_text("hello", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["tests/tool_test/1.txt"])
        self.assertFalse(result.metadata["truncated"])

    def test_glob_respects_search_root_and_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "1.txt").write_text("a", encoding="utf-8")
            (root / "b" / "1.txt").write_text("b", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt", "path": "a", "limit": 1})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["a/1.txt"])
        self.assertTrue(result.metadata["truncated"])

    def test_glob_rejects_path_outside_project(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(GlobTool(), Path(tmp), {"pattern": "**/*.txt", "path": ".."})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "path_outside_project")

    def test_glob_skips_heavy_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules").mkdir()
            (root / "node_modules" / "1.txt").write_text("skip", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "1.txt").write_text("keep", encoding="utf-8")

            result = _run(GlobTool(), root, {"pattern": "**/1.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["src/1.txt"])

    def test_grep_returns_matching_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.txt").write_text("first\nneedle here\n", encoding="utf-8")
            (root / "src" / "b.py").write_text("needle ignored by include\n", encoding="utf-8")

            result = _run(GrepTool(), root, {"pattern": "needle", "include": "**/*.txt"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], [{"path": "src/a.txt", "line": 2, "text": "needle here"}])
        self.assertIn("src/a.txt:2: needle here", result.content)

    def test_grep_missing_path_returns_structured_error(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(GrepTool(), Path(tmp), {"pattern": "needle", "path": "missing"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "path_not_found")

    def test_web_search_schema_includes_current_month_year_guidance(self) -> None:
        previous = os.environ.get("ZZCODE_OVERRIDE_DATE")
        os.environ["ZZCODE_OVERRIDE_DATE"] = "2026-06-24"
        try:
            schema = WebSearchTool().to_openai_tool()
        finally:
            if previous is None:
                os.environ.pop("ZZCODE_OVERRIDE_DATE", None)
            else:
                os.environ["ZZCODE_OVERRIDE_DATE"] = previous

        description = schema["function"]["description"]
        self.assertIn("The current month is June 2026", description)
        self.assertIn("If the user asks about today", description)
        self.assertIn("full current date", description)
        self.assertIn('final answer MUST include a "Sources:" section', description)

    def test_web_search_result_keeps_structured_source_urls(self) -> None:
        previous = os.environ.get("BOCHA_API_KEY")
        os.environ["BOCHA_API_KEY"] = "test-key"
        body = {
            "code": 200,
            "data": {
                "webPages": {
                    "totalEstimatedMatches": 1,
                    "value": [
                        {
                            "name": "A股行情",
                            "url": "https://example.com/a-stock",
                            "snippet": "今日涨幅榜。",
                            "siteName": "Example Finance",
                            "datePublished": "2026-06-24T09:30:00Z",
                        }
                    ],
                }
            },
        }
        try:
            with TemporaryDirectory() as tmp, patch(
                "zzcode.tools.local.search_session.urllib.request.urlopen",
                return_value=_FakeHttpResponse(body),
            ):
                result = _run(WebSearchTool(), Path(tmp), {"query": "2026-06-24 A股 涨幅榜", "count": 1})
        finally:
            if previous is None:
                os.environ.pop("BOCHA_API_KEY", None)
            else:
                os.environ["BOCHA_API_KEY"] = previous

        self.assertTrue(result.ok)
        self.assertIn("[A股行情](https://example.com/a-stock)", result.content)
        self.assertIn("cite the relevant source URLs", result.content)
        self.assertEqual(result.data["sources"][0]["title"], "A股行情")
        self.assertEqual(result.data["sources"][0]["url"], "https://example.com/a-stock")
        self.assertEqual(result.data["searchCount"], 1)
        self.assertIsInstance(result.data["durationSeconds"], float)
        self.assertEqual(result.data["results"][0]["content"][0]["url"], "https://example.com/a-stock")

    def test_web_search_session_enforces_internal_max_uses(self) -> None:
        session = WebSearchSession(api_key="test-key", http_client=_FakeSearchClient(), max_uses=1)

        first = session.search("first", 1)
        second = session.search("second", 1)

        self.assertFalse(first.exhausted)
        self.assertEqual(first.search_count, 1)
        self.assertEqual(first.sources[0]["url"], "https://example.com/first")
        self.assertTrue(second.exhausted)
        self.assertEqual(second.search_count, 1)
        self.assertIn("max_uses", second.error)

    def test_web_fetch_upgrades_http_url_before_requesting(self) -> None:
        seen_urls: list[str] = []

        def fake_urlopen(request, timeout):
            seen_urls.append(request.full_url)
            return _FakeFetchResponse(b"<html><body>Hello</body></html>", "https://example.com/a")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "http://example.com/a", "prompt": "summarize"})

        self.assertTrue(result.ok)
        self.assertEqual(seen_urls, ["https://example.com/a"])
        self.assertEqual(result.data["originalUrl"], "http://example.com/a")
        self.assertEqual(result.data["requestUrl"], "https://example.com/a")
        self.assertTrue(result.data["upgraded"])
        self.assertTrue(result.metadata["httpsUpgraded"])
        self.assertFalse(result.metadata["cacheHit"])

    def test_web_fetch_reuses_cached_content_for_same_url(self) -> None:
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            return _FakeFetchResponse(b"<html><body>Cached page</body></html>", "https://example.com/cache")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            first = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/cache", "prompt": "first"})
            second = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/cache", "prompt": "second"})

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(calls, ["https://example.com/cache"])
        self.assertFalse(first.metadata["cacheHit"])
        self.assertTrue(second.metadata["cacheHit"])
        self.assertIn('Prompt: "second"', second.content)
        self.assertIn("Cached page", second.content)

    def test_web_fetch_uses_injected_summarizer_result(self) -> None:
        summarizer = _FakeWebFetchSummarizer()

        def fake_urlopen(request, timeout):
            return _FakeFetchResponse(
                b"<html><body>Long page content that should not be returned directly</body></html>",
                "https://example.com/summary",
            )

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            registry = ToolRegistry()
            tool = WebFetchTool()
            registry.register(tool)
            context = ToolContext(project_root=Path(tmp), metadata={"web_fetch_summarizer": summarizer})
            result = ToolRunner(registry).run(
                ToolCall(id="call_1", name=tool.name, args={"url": "https://example.com/summary", "prompt": "extract title"}),
                context,
            )

        self.assertTrue(result.ok)
        self.assertEqual(summarizer.calls, [("extract title", "Long page content that should not be returned directly")])
        self.assertIn("short extracted answer", result.content)
        self.assertNotIn("Long page content that should not be returned directly", result.content)
        self.assertEqual(result.metadata["summarySource"], "fake")
        self.assertFalse(result.metadata["preapproved"])
        self.assertEqual(result.data["summaryChars"], len("short extracted answer"))

    def test_web_fetch_marks_preapproved_domain_for_summarizer(self) -> None:
        summarizer = _FakeWebFetchSummarizer()

        def fake_urlopen(request, timeout):
            return _FakeFetchResponse(b"Python docs", "https://docs.python.org/3/library/pathlib.html", content_type="text/plain")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            registry = ToolRegistry()
            tool = WebFetchTool()
            registry.register(tool)
            context = ToolContext(project_root=Path(tmp), metadata={"web_fetch_summarizer": summarizer})
            result = ToolRunner(registry).run(
                ToolCall(
                    id="call_1",
                    name=tool.name,
                    args={"url": "https://docs.python.org/3/library/pathlib.html", "prompt": "extract docs"},
                ),
                context,
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["preapproved"])
        self.assertEqual(summarizer.preapproved_values, [True])

    def test_llm_web_fetch_summarizer_calls_chat_without_tools(self) -> None:
        llm = _FakeSummaryLLM("model extracted answer")
        summarizer = LLMWebFetchSummarizer(llm)

        summary = summarizer.summarize(prompt="extract", content="page content", content_type="text/plain")

        self.assertEqual(summary.text, "model extracted answer")
        self.assertEqual(summary.source, "llm")
        self.assertEqual(llm.calls[0]["tools"], [])
        self.assertIn("page content", llm.calls[0]["messages"][0]["content"])

    def test_web_fetch_summary_prompt_adds_copyright_limits_for_non_preapproved_domains(self) -> None:
        prompt = build_web_fetch_summary_prompt(
            prompt="extract facts",
            content="article text",
            content_type="text/html",
            is_preapproved_domain=False,
        )

        self.assertIn("125-character maximum", prompt)
        self.assertIn("Never produce or reproduce exact song lyrics", prompt)
        self.assertIn("based only on the content above", prompt)

    def test_web_fetch_summary_prompt_is_looser_for_preapproved_domains(self) -> None:
        prompt = build_web_fetch_summary_prompt(
            prompt="extract docs",
            content="documentation",
            content_type="text/markdown",
            is_preapproved_domain=True,
        )

        self.assertIn("documentation excerpts", prompt)
        self.assertNotIn("125-character maximum", prompt)

    def test_web_fetch_preapproved_url_matches_host_and_path_boundaries(self) -> None:
        self.assertTrue(is_preapproved_url("https://docs.python.org/3/library/pathlib.html"))
        self.assertTrue(is_preapproved_url("https://github.com/anthropics/claude-code"))
        self.assertFalse(is_preapproved_url("https://github.com/anthropics-evil/project"))
        self.assertFalse(is_preapproved_url("https://example.com/article"))

    def test_web_fetch_cache_expires_entries(self) -> None:
        now = 1000.0
        cache = WebFetchCache(ttl_seconds=10, max_bytes=100, time_fn=lambda: now)
        entry = WebFetchCacheEntry(
            url="https://example.com/a",
            content_type="text/plain",
            bytes_count=3,
            text="abc",
            original_text_chars=3,
            text_truncated=False,
            size_bytes=3,
        )

        cache.set("https://example.com/a", entry)
        self.assertIs(cache.get("https://example.com/a"), entry)

        now = 1011.0
        self.assertIsNone(cache.get("https://example.com/a"))
        self.assertEqual(cache.current_bytes, 0)

    def test_web_fetch_cache_evicts_lru_entries_when_size_exceeded(self) -> None:
        cache = WebFetchCache(ttl_seconds=60, max_bytes=5, time_fn=lambda: 1000.0)
        first = WebFetchCacheEntry(
            url="https://example.com/a",
            content_type="text/plain",
            bytes_count=3,
            text="aaa",
            original_text_chars=3,
            text_truncated=False,
            size_bytes=3,
        )
        second = WebFetchCacheEntry(
            url="https://example.com/b",
            content_type="text/plain",
            bytes_count=3,
            text="bbb",
            original_text_chars=3,
            text_truncated=False,
            size_bytes=3,
        )

        cache.set("https://example.com/a", first)
        cache.set("https://example.com/b", second)

        self.assertIsNone(cache.get("https://example.com/a"))
        self.assertIs(cache.get("https://example.com/b"), second)
        self.assertEqual(cache.current_bytes, 3)

    def test_web_fetch_rejects_invalid_url_shapes(self) -> None:
        with TemporaryDirectory() as tmp:
            credential_result = _run(
                WebFetchTool(),
                Path(tmp),
                {"url": "https://user:pass@example.com/a", "prompt": "summarize"},
            )
            single_host_result = _run(
                WebFetchTool(),
                Path(tmp),
                {"url": "https://localhost/a", "prompt": "summarize"},
            )

        self.assertFalse(credential_result.ok)
        self.assertIn("credentials", credential_result.content)
        self.assertFalse(single_host_result.ok)
        self.assertIn("valid hostname", single_host_result.content)

    def test_web_fetch_rejects_body_larger_than_limit(self) -> None:
        body = b"x" * (MAX_HTTP_BODY_BYTES + 1)

        def fake_urlopen(request, timeout):
            return _FakeFetchResponse(body, "https://example.com/large")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/large", "prompt": "summarize"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "web_fetch_body_too_large")
        self.assertEqual(result.data["limitBytes"], MAX_HTTP_BODY_BYTES)

    def test_web_fetch_returns_structured_timeout_failure(self) -> None:
        def fake_urlopen(request, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/slow", "prompt": "summarize"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "web_fetch_timeout")
        self.assertEqual(result.data["timeoutSeconds"], 60)

    def test_web_fetch_truncates_text_longer_than_limit(self) -> None:
        body = b"x" * (MAX_TEXT_LENGTH + 1)

        def fake_urlopen(request, timeout):
            return _FakeFetchResponse(body, "https://example.com/text", content_type="text/plain")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/text", "prompt": "summarize"})

        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["textTruncated"])
        self.assertTrue(result.data["textTruncated"])
        self.assertEqual(result.data["maxTextLength"], MAX_TEXT_LENGTH)
        self.assertTrue(result.metadata["summaryTruncated"])
        self.assertIn("[WebFetch result truncated by local summarizer...]", result.content)

    def test_web_fetch_extract_converts_html_to_text(self) -> None:
        html = b"<html><body><nav>skip</nav><h1>Title</h1><p>A &amp; B</p><script>x()</script></body></html>"

        extracted = extract_fetch_text(html, "text/html; charset=utf-8")

        self.assertEqual(extracted.text, "Title\n\nA & B")
        self.assertEqual(extracted.original_text_chars, len("Title\n\nA & B"))
        self.assertFalse(extracted.text_truncated)
        self.assertTrue(looks_like_html(html.decode("utf-8")))
        self.assertEqual(strip_html("<p>Hello&nbsp;world</p>"), "Hello world")

    def test_web_fetch_extract_keeps_plain_text_and_truncates(self) -> None:
        extracted = extract_fetch_text(b"abcdef", "text/plain", max_text_length=3)

        self.assertEqual(extracted.original_text_chars, 6)
        self.assertTrue(extracted.text_truncated)
        self.assertEqual(extracted.max_text_length, 3)
        self.assertEqual(extracted.text, "abc\n\n[Content truncated due to length...]")

    def test_web_fetch_follows_same_host_redirect(self) -> None:
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            if request.full_url == "https://example.com/start":
                raise _FakeRedirectError("https://example.com/start", 302, "/final")
            return _FakeFetchResponse(b"<html><body>Redirected page</body></html>", "https://example.com/final")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/start", "prompt": "summarize"})

        self.assertTrue(result.ok)
        self.assertEqual(calls, ["https://example.com/start", "https://example.com/final"])
        self.assertEqual(result.data["url"], "https://example.com/final")
        self.assertIn("Redirected page", result.content)

    def test_web_fetch_returns_cross_host_redirect_result(self) -> None:
        def fake_urlopen(request, timeout):
            raise _FakeRedirectError("https://example.com/start", 302, "https://other.example.org/final")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/start", "prompt": "summarize"})

        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["redirect"])
        self.assertEqual(result.metadata["reason"], "web_fetch_redirect")
        self.assertEqual(result.data["redirectUrl"], "https://other.example.org/final")
        self.assertIn("REDIRECT DETECTED", result.content)
        self.assertIn('- url: "https://other.example.org/final"', result.content)

    def test_web_fetch_rejects_redirect_loop_after_limit(self) -> None:
        def fake_urlopen(request, timeout):
            raise _FakeRedirectError(request.full_url, 302, "/next")

        with TemporaryDirectory() as tmp, patch("zzcode.tools.local.web_fetch._open_url_no_redirect", fake_urlopen):
            result = _run(WebFetchTool(), Path(tmp), {"url": "https://example.com/start", "prompt": "summarize"})

        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["reason"], "web_fetch_too_many_redirects")
        self.assertIn("Too many redirects", result.content)


def _run(tool, root: Path, args: dict):
    registry = ToolRegistry()
    registry.register(tool)
    context = ToolContext(project_root=root)
    return ToolRunner(registry).run(ToolCall(id="call_1", name=tool.name, args=args), context)


class _FakeHttpResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self.body).encode("utf-8")


class _FakeFetchResponse:
    def __init__(self, body: bytes, url: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.body = body
        self.url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, size: int | None = None) -> bytes:
        if size is None or size < 0:
            return self.body
        return self.body[:size]

    def geturl(self) -> str:
        return self.url


class _FakeRedirectError(urllib.error.HTTPError):
    def __init__(self, url: str, status: int, location: str) -> None:
        super().__init__(url, status, "redirect", {"Location": location}, None)


class _FakeWebFetchSummarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.preapproved_values: list[bool] = []

    def summarize(
        self,
        *,
        prompt: str,
        content: str,
        content_type: str,
        is_preapproved_domain: bool = False,
    ) -> WebFetchSummary:
        self.calls.append((prompt, content))
        self.preapproved_values.append(is_preapproved_domain)
        return WebFetchSummary(
            text="short extracted answer",
            source="fake",
            original_chars=len(content),
            result_chars=len("short extracted answer"),
            truncated=False,
        )


class _FakeSummaryLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0):
        self.calls.append({"messages": messages, "tools": tools, "temperature": temperature})
        return type("Response", (), {"content": self.content})()


class _FakeSearchClient:
    def search(self, query: str, count: int, api_key: str):
        return {
            "code": 200,
            "data": {
                "webPages": {
                    "totalEstimatedMatches": 1,
                    "value": [
                        {
                            "name": query,
                            "url": f"https://example.com/{query}",
                            "snippet": "snippet",
                        }
                    ],
                }
            },
        }


if __name__ == "__main__":
    unittest.main()
