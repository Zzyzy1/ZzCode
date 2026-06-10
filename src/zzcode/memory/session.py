"""当前后端进程内的短期会话记忆。"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SESSION_HISTORY_LIMIT = 12
DEFAULT_COMPACT_CHAR_THRESHOLD = 16000
DEFAULT_COMPACT_KEEP_ITEMS = 6
DEFAULT_COMPACT_SUMMARY_LIMIT = 8000


@dataclass(frozen=True)
class SessionCompactResult:
    """一次短期会话压缩的结果。"""

    compacted: bool
    reason: str
    removed_items: int = 0
    kept_items: int = 0
    summary_chars: int = 0


class ShortTermSessionMemory:
    """维护最近几轮 User/Assistant 文本。

    limit 是最多保留的历史条数；内容只存在于当前 Python 后端进程内。
    """

    def __init__(
        self,
        limit: int = DEFAULT_SESSION_HISTORY_LIMIT,
        compact_char_threshold: int = DEFAULT_COMPACT_CHAR_THRESHOLD,
        compact_keep_items: int = DEFAULT_COMPACT_KEEP_ITEMS,
        compact_summary_limit: int = DEFAULT_COMPACT_SUMMARY_LIMIT,
    ) -> None:
        self.limit = limit
        self.compact_char_threshold = compact_char_threshold
        self.compact_keep_items = compact_keep_items
        self.compact_summary_limit = compact_summary_limit
        self._items: list[str] = []
        self._compact_summary = ""

    def clear(self) -> None:
        """清空当前会话短期记忆。"""

        self._items.clear()
        self._compact_summary = ""

    def record_turn(self, user_text: str, assistant_text: str) -> int:
        """记录一轮成功对话，返回被裁剪的历史条数。"""

        self._items.append(f"User: {user_text}")
        self._items.append(f"Assistant: {assistant_text}")
        return self._trim()

    def as_list(self) -> list[str]:
        """返回当前短期记忆副本。"""

        return list(self._items)

    def compact_summary(self) -> str:
        """返回已压缩的旧会话摘要。"""

        return self._compact_summary

    def compact_if_needed(self) -> SessionCompactResult:
        """超过字符阈值时压缩旧历史，未超过时返回空结果。"""

        if self.compact_char_threshold < 0:
            return SessionCompactResult(compacted=False, reason="disabled")
        if self.context_char_count() <= self.compact_char_threshold:
            return SessionCompactResult(compacted=False, reason="below_threshold")
        return self.compact(reason="auto_threshold")

    def compact(self, reason: str = "manual") -> SessionCompactResult:
        """把较早历史折叠为摘要，并保留最近若干条上下文。"""

        keep_count = max(0, min(self.compact_keep_items, len(self._items)))
        if keep_count >= len(self._items):
            return SessionCompactResult(compacted=False, reason="not_enough_history", kept_items=len(self._items))

        old_items = self._items[:-keep_count] if keep_count else list(self._items)
        kept_items = self._items[-keep_count:] if keep_count else []
        self._compact_summary = self._merge_compact_summary(old_items)
        self._items = kept_items
        return SessionCompactResult(
            compacted=True,
            reason=reason,
            removed_items=len(old_items),
            kept_items=len(kept_items),
            summary_chars=len(self._compact_summary),
        )

    def context_char_count(self) -> int:
        """返回短期历史和压缩摘要的近似字符量。"""

        return len(self._compact_summary) + sum(len(item) for item in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def _trim(self) -> int:
        """按容量裁剪旧历史，返回删除数量。"""

        if self.limit < 0 or len(self._items) <= self.limit:
            return 0
        removed_count = len(self._items) - self.limit
        del self._items[:-self.limit]
        return removed_count

    def _merge_compact_summary(self, old_items: list[str]) -> str:
        """合并旧摘要和本次被压缩历史，控制摘要最大长度。"""

        parts = []
        if self._compact_summary.strip():
            parts.append(self._compact_summary.strip())
        parts.append("Compacted previous session:")
        parts.extend(old_items)
        summary = "\n".join(parts).strip()
        if self.compact_summary_limit >= 0 and len(summary) > self.compact_summary_limit:
            summary = summary[-self.compact_summary_limit :]
            summary = "[older compacted session omitted]\n" + summary
        return summary
