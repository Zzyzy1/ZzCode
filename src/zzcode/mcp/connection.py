"""MCP SDK 连接封装。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from zzcode.logging import log_mcp_debug, log_mcp_error

from .config import McpServerConfig
from .runtime import McpRuntime


MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "zzcode"
MCP_CLIENT_VERSION = "0.1.0"

McpConnectionStatus = Literal["pending", "connected", "failed", "disabled", "needs_auth", "closed"]


class McpConnectionError(RuntimeError):
    """表示 MCP 连接、请求或响应失败。"""


@dataclass
class McpConnection:
    """表示一个 MCP server SDK 连接及其状态。

    runtime 在后台 event loop 中运行 MCP Python SDK；同步工具层通过本对象调用。
    """

    config: McpServerConfig
    project_root: Path
    runtime: McpRuntime
    status: McpConnectionStatus = "pending"
    capabilities: dict[str, Any] = field(default_factory=dict)
    server_info: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""
    error: str = ""
    _session: Any | None = field(default=None, init=False, repr=False)
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _stderr_file: Any | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        """返回 MCP server 名称。"""

        return self.config.name

    @property
    def is_connected(self) -> bool:
        """返回当前连接是否可用。"""

        return self.status == "connected" and self._session is not None

    def connect(self) -> "McpConnection":
        """启动 server 并完成 SDK initialize。"""

        if not self.config.enabled:
            self.status = "disabled"
            self.error = ""
            return self
        if self.is_connected:
            return self

        self.status = "pending"
        self.error = ""
        log_mcp_debug(self.name, "starting connection", operation="connect")
        try:
            self.runtime.run(
                self._connect_with_timeout(),
                timeout=self.config.timeout_seconds + 5,
            )
        except Exception as exc:
            self.status = "failed"
            self.error = self._format_error(exc)
            log_mcp_error(self.name, exc, operation="connect", context={"error": self.error})
            try:
                self.runtime.run(self._close_async(), timeout=5)
            except Exception:
                pass
            return self

        self.status = "connected"
        log_mcp_debug(self.name, "connection established", operation="connect")
        return self

    def close(self) -> None:
        """关闭 MCP SDK session 和 transport。"""

        was_connected = self.status == "connected"
        log_mcp_debug(self.name, "closing connection", operation="close")
        try:
            self.runtime.run(self._close_async(), timeout=5)
        except Exception as exc:
            self.error = self._format_error(exc)
            log_mcp_error(self.name, exc, operation="close", context={"error": self.error})
        if was_connected:
            self.status = "closed"

    def list_tools(self) -> Any:
        """调用 SDK tools/list。"""

        log_mcp_debug(self.name, "list_tools", operation="list_tools")
        return self._run_request(self._session.list_tools())

    def list_resources(self) -> Any:
        """调用 SDK resources/list。"""

        log_mcp_debug(self.name, "list_resources", operation="list_resources")
        return self._run_request(self._session.list_resources())

    def read_resource(self, uri: str) -> Any:
        """调用 SDK resources/read。"""

        log_mcp_debug(self.name, f"read_resource uri={uri}", operation="read_resource")
        return self._run_request(self._session.read_resource(uri))

    def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """调用 SDK tools/call。"""

        log_mcp_debug(self.name, f"call_tool name={tool_name}", operation="call_tool")
        return self._run_request(
            self._session.call_tool(
                tool_name,
                args,
                read_timeout_seconds=_sdk_timeout(self.config.timeout_seconds),
                meta=meta,
            )
        )

    def stderr_output(self) -> str:
        """返回 server stderr 摘要。"""

        stderr_file = self._stderr_file
        if stderr_file is not None:
            try:
                stderr_file.flush()
            except OSError:
                pass
        from .transport import read_mcp_stderr_tail

        return read_mcp_stderr_tail(self.project_root, self.name)

    async def _connect_async(self) -> None:
        try:
            from mcp import ClientSession, types
            from mcp.client.stdio import stdio_client
        except ModuleNotFoundError as exc:
            raise McpConnectionError(
                "Python MCP SDK is not installed. Install project dependencies from requirements.txt."
            ) from exc

        from .transport import create_stdio_parameters, open_mcp_stderr_log

        stack = AsyncExitStack()
        stderr_file = open_mcp_stderr_log(self.project_root, self.name)
        self._stderr_file = stderr_file
        try:
            params = create_stdio_parameters(self.config, self.project_root)
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params, errlog=stderr_file)
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=_sdk_timeout(self.config.timeout_seconds),
                    client_info=types.Implementation(
                        name=MCP_CLIENT_NAME,
                        version=MCP_CLIENT_VERSION,
                    ),
                )
            )
            initialize_result = await asyncio.wait_for(
                session.initialize(),
                timeout=self.config.timeout_seconds,
            )
        except Exception:
            await stack.aclose()
            self._flush_stderr_file()
            raise

        self._exit_stack = stack
        self._session = session
        result = model_to_dict(initialize_result)
        self.capabilities = _as_dict(result.get("capabilities"))
        self.server_info = _as_dict(result.get("serverInfo", result.get("server_info")))
        instructions = result.get("instructions")
        self.instructions = instructions if isinstance(instructions, str) else ""

    async def _connect_with_timeout(self) -> None:
        try:
            await asyncio.wait_for(self._connect_async(), timeout=self.config.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise McpConnectionError(
                f"MCP server '{self.name}' connection timed out after "
                f"{self.config.timeout_seconds:g}s."
            ) from exc

    async def _close_async(self) -> None:
        stack = self._exit_stack
        self._exit_stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()
        self._close_stderr_file()

    def _run_request(self, awaitable: Any) -> Any:
        if not self.is_connected or self._session is None:
            raise McpConnectionError(
                f"MCP server '{self.name}' is not connected (status: {self.status})."
            )
        try:
            return self.runtime.run(awaitable, timeout=self.config.timeout_seconds + 2)
        except Exception as exc:
            self.status = "failed"
            self.error = self._format_error(exc)
            log_mcp_error(self.name, exc, operation="request", context={"error": self.error})
            try:
                self.runtime.run(self._close_async(), timeout=3)
            except Exception:
                pass
            raise McpConnectionError(self.error) from exc

    def _format_error(self, exc: BaseException) -> str:
        message = str(exc) or exc.__class__.__name__
        stderr = self.stderr_output().strip()
        if stderr:
            return f"{message}\nMCP server stderr:\n{stderr}"
        return message

    def _flush_stderr_file(self) -> None:
        stderr_file = self._stderr_file
        if stderr_file is None:
            return
        try:
            stderr_file.flush()
        except OSError:
            pass

    def _close_stderr_file(self) -> None:
        stderr_file = self._stderr_file
        self._stderr_file = None
        if stderr_file is None:
            return
        try:
            stderr_file.flush()
            stderr_file.close()
        except OSError:
            pass


def model_to_dict(value: Any) -> dict[str, Any]:
    """把 SDK pydantic model 或普通 dict 转成 JSON dict。"""

    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump(by_alias=True, mode="json", exclude_none=True))
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return model_to_dict(value)


def _sdk_timeout(seconds: float) -> timedelta:
    """返回当前 Python MCP SDK 版本兼容的 timeout 值。

    mcp 1.27.2 在部分路径会调用 timeout.total_seconds()，因此 SDK 参数传
    timedelta；外层 asyncio/anyio timeout 仍继续使用 float 秒数。
    """

    return timedelta(seconds=seconds)
