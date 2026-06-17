"""缓冲日志写入器。"""

from __future__ import annotations

import threading
import time
from pathlib import Path


class BufferedFileWriter:
    """向单个文件追加文本，并按批次刷盘。"""

    def __init__(
        self,
        path: Path,
        *,
        mirror_path: Path | None = None,
        flush_interval_seconds: float = 1.0,
        immediate: bool = False,
    ) -> None:
        self.path = path
        self.mirror_path = mirror_path
        self.flush_interval_seconds = flush_interval_seconds
        self.immediate = immediate
        self._buffer: list[str] = []
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        if self.mirror_path is not None:
            self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
            self.mirror_path.write_text("", encoding="utf-8")

    def write(self, content: str) -> None:
        """追加一段文本。"""

        if not content:
            return
        with self._lock:
            self._buffer.append(content)
            should_flush = self.immediate or (
                time.monotonic() - self._last_flush >= self.flush_interval_seconds
            )
            if should_flush:
                self._flush_locked()

    def flush(self) -> None:
        """把缓冲区落盘。"""

        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        """关闭前刷盘。"""

        self.flush()

    def _flush_locked(self) -> None:
        if not self._buffer:
            return
        content = "".join(self._buffer)
        self._buffer.clear()
        self._last_flush = time.monotonic()
        self._append(self.path, content)
        if self.mirror_path is not None:
            self._append(self.mirror_path, content)

    @staticmethod
    def _append(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(content)
