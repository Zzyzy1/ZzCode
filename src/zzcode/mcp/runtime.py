"""MCP async SDK 的同步桥接运行时。"""

from __future__ import annotations

from typing import Any, Awaitable


class McpRuntimeError(RuntimeError):
    """表示 MCP async runtime 启动或执行失败。"""


class McpRuntime:
    """用 anyio blocking portal 运行 MCP SDK coroutine。

    MCP Python SDK 基于 anyio；blocking portal 是 anyio 官方提供的同步线程调用
    async 代码的桥。这样可以保留 ZzCode 当前同步 Tool.call() 接口。
    """

    def __init__(self) -> None:
        self._portal_context: Any | None = None
        self._portal: Any | None = None
        self._closed = False

    def run(self, awaitable: Awaitable[Any], *, timeout: float | None = None) -> Any:
        """同步等待 awaitable 完成。"""

        if self._closed:
            _close_awaitable(awaitable)
            raise McpRuntimeError("MCP runtime is closed.")
        try:
            portal = self._ensure_portal()
        except Exception:
            _close_awaitable(awaitable)
            raise
        return portal.call(_await_with_timeout, awaitable, timeout)

    def close(self) -> None:
        """关闭 blocking portal。"""

        if self._closed:
            return
        self._closed = True
        context = self._portal_context
        self._portal_context = None
        self._portal = None
        if context is not None:
            context.__exit__(None, None, None)

    def _ensure_portal(self) -> Any:
        if self._portal is not None:
            return self._portal
        try:
            from anyio.from_thread import start_blocking_portal
        except ModuleNotFoundError as exc:
            raise McpRuntimeError(
                "Python MCP SDK dependencies are not installed. "
                "Install project dependencies from requirements.txt."
            ) from exc
        self._portal_context = start_blocking_portal()
        self._portal = self._portal_context.__enter__()
        return self._portal


async def _await_with_timeout(awaitable: Awaitable[Any], timeout: float | None) -> Any:
    if timeout is None:
        return await awaitable
    import anyio

    with anyio.fail_after(timeout):
        return await awaitable


def _close_awaitable(awaitable: Awaitable[Any]) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()
