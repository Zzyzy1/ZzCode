"""WebFetch URL cache。"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable


DEFAULT_WEB_FETCH_CACHE_TTL_SECONDS = 15 * 60
DEFAULT_WEB_FETCH_CACHE_MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class WebFetchCacheEntry:
    """缓存一次 WebFetch 抓取和文本转换后的内容。"""

    url: str
    content_type: str
    bytes_count: int
    text: str
    original_text_chars: int
    text_truncated: bool
    size_bytes: int


@dataclass
class _StoredEntry:
    entry: WebFetchCacheEntry
    expires_at: float


class WebFetchCache:
    """提供 Claude 风格 TTL + size limit 的 URL cache。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_WEB_FETCH_CACHE_TTL_SECONDS,
        max_bytes: int = DEFAULT_WEB_FETCH_CACHE_MAX_BYTES,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._time_fn = time_fn or time.time
        self._entries: OrderedDict[str, _StoredEntry] = OrderedDict()
        self._current_bytes = 0

    def get(self, key: str) -> WebFetchCacheEntry | None:
        """读取缓存；过期或不存在时返回 None。"""

        stored = self._entries.get(key)
        if stored is None:
            return None

        now = self._time_fn()
        if stored.expires_at <= now:
            self._remove(key)
            return None

        self._entries.move_to_end(key)
        return stored.entry

    def set(self, key: str, entry: WebFetchCacheEntry) -> None:
        """写入缓存，并按 LRU 策略清理超限内容。"""

        if entry.size_bytes > self._max_bytes:
            self._remove(key)
            return

        self._remove(key)
        self._entries[key] = _StoredEntry(entry=entry, expires_at=self._time_fn() + self._ttl_seconds)
        self._current_bytes += entry.size_bytes
        self._evict_expired()
        self._evict_to_size()

    def clear(self) -> None:
        """清空缓存，主要用于测试和长进程重置。"""

        self._entries.clear()
        self._current_bytes = 0

    @property
    def current_bytes(self) -> int:
        return self._current_bytes

    def _remove(self, key: str) -> None:
        stored = self._entries.pop(key, None)
        if stored is not None:
            self._current_bytes -= stored.entry.size_bytes

    def _evict_expired(self) -> None:
        now = self._time_fn()
        expired_keys = [key for key, stored in self._entries.items() if stored.expires_at <= now]
        for key in expired_keys:
            self._remove(key)

    def _evict_to_size(self) -> None:
        while self._current_bytes > self._max_bytes and self._entries:
            key, _ = next(iter(self._entries.items()))
            self._remove(key)


WEB_FETCH_CACHE = WebFetchCache()


def clear_web_fetch_cache() -> None:
    """清空默认 WebFetch cache。"""

    WEB_FETCH_CACHE.clear()
