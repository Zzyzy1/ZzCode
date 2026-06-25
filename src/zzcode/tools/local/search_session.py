"""Claude 风格 WebSearch 内部搜索会话。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


BOCHA_SEARCH_URL = "https://api.bocha.cn/v1/web-search"
DEFAULT_WEB_SEARCH_MAX_USES = 8


class SearchHttpClient(Protocol):
    """WebSearch HTTP 客户端协议。"""

    def search(self, query: str, count: int, api_key: str) -> dict[str, Any]:
        """执行一次搜索请求并返回 API JSON。"""


class BochaSearchHttpClient:
    """调用 Bocha Web Search API。"""

    def search(self, query: str, count: int, api_key: str) -> dict[str, Any]:
        """执行一次 Bocha 搜索。"""

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
            return json.loads(response.read().decode("utf-8"))


@dataclass
class SearchHit:
    """一次搜索结果项。"""

    title: str
    url: str
    snippet: str = ""
    site: str = ""
    date: str = ""

    def to_source(self) -> dict[str, str]:
        """转换为可回灌模型和 UI 的 source block。"""

        return {
            "title": self.title,
            "url": self.url,
            "site": self.site,
            "date": self.date,
        }


@dataclass
class WebSearchSessionResult:
    """一次 WebSearch 内部会话结果。"""

    query: str
    hits: list[SearchHit]
    total_estimated_matches: int
    duration_seconds: float
    search_count: int
    exhausted: bool = False
    error: str = ""

    @property
    def sources(self) -> list[dict[str, str]]:
        return [hit.to_source() for hit in self.hits]


@dataclass
class WebSearchSession:
    """限制单次 WebSearch 内部搜索次数。"""

    api_key: str
    http_client: SearchHttpClient = field(default_factory=BochaSearchHttpClient)
    max_uses: int = DEFAULT_WEB_SEARCH_MAX_USES
    used: int = 0

    def search(self, query: str, count: int) -> WebSearchSessionResult:
        """执行一次受预算控制的搜索。"""

        started_at = time.perf_counter()
        if self.used >= self.max_uses:
            return WebSearchSessionResult(
                query=query,
                hits=[],
                total_estimated_matches=0,
                duration_seconds=0.0,
                search_count=self.used,
                exhausted=True,
                error="WebSearch internal max_uses exhausted.",
            )
        self.used += 1

        try:
            body = self.http_client.search(query, count, self.api_key)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            return WebSearchSessionResult(
                query=query,
                hits=[],
                total_estimated_matches=0,
                duration_seconds=time.perf_counter() - started_at,
                search_count=self.used,
                error=f"Search API returned HTTP {exc.code}: {error_body[:300]}",
            )
        except Exception as exc:
            return WebSearchSessionResult(
                query=query,
                hits=[],
                total_estimated_matches=0,
                duration_seconds=time.perf_counter() - started_at,
                search_count=self.used,
                error=f"Search request failed: {exc}",
            )

        code = body.get("code")
        if code != 200:
            msg = body.get("msg") or body.get("message") or "unknown error"
            return WebSearchSessionResult(
                query=query,
                hits=[],
                total_estimated_matches=0,
                duration_seconds=time.perf_counter() - started_at,
                search_count=self.used,
                error=f"Search API error: {msg}",
            )

        data = body.get("data") or {}
        web_pages = data.get("webPages") or {}
        raw_results = web_pages.get("value") or []
        hits = [_normalize_hit(item) for item in raw_results]
        total = int(web_pages.get("totalEstimatedMatches", len(hits)) or len(hits))
        return WebSearchSessionResult(
            query=query,
            hits=hits,
            total_estimated_matches=total,
            duration_seconds=time.perf_counter() - started_at,
            search_count=self.used,
        )


def _normalize_hit(item: dict[str, Any]) -> SearchHit:
    date = item.get("datePublished") or ""
    return SearchHit(
        title=str(item.get("name") or "Untitled"),
        url=str(item.get("url") or ""),
        snippet=str(item.get("snippet") or ""),
        site=str(item.get("siteName") or ""),
        date=str(date[:10]) if date else "",
    )
