"""Interactive CLI for the structured tool-call agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from zzcode.agent.context_budget import max_turns_from_env
from zzcode.agent.tool_call_agent import ToolCallAgent
from zzcode.cli.ui import create_ui
from zzcode.llm.client import ZzCodeLLM
from zzcode.memory import create_session_scope
from zzcode.mcp import McpConfigError, McpManager
from zzcode.tools.base import ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.builtin import build_tool_registry as build_structured_tool_registry
from zzcode.tools.local.agent import AgentTool
from zzcode.tools.registry import ToolRegistry


def main() -> int:
    """启动交互式 CLI。

    负责创建 UI、LLM、工具注册表和 Agent；返回进程退出码。
    """

    ui = create_ui()
    try:
        llm = ZzCodeLLM(stream=_streaming_enabled())
    except Exception as exc:
        ui.error(f"Failed to initialize LLM: {exc}")
        return 1

    project_root = Path.cwd()
    mcp_manager = create_mcp_manager(
        project_root,
        reporter=lambda level, message: getattr(ui, level)(message),
    )
    tools = build_tool_registry(project_root, mcp_manager=mcp_manager)
    session_scope = create_session_scope(project_root)
    tools.register(
        AgentTool(
            project_root=project_root,
            llm_client=llm,
            session_scope=session_scope,
            base_registry=tools,
            permission_checker=_request_cli_permission,
            session_context_provider=lambda: "",
            renderer=ui,
        )
    )
    ui.banner(model=llm.model or "(unknown)", tools=tools)
    agent = ToolCallAgent(
        llm_client=llm,
        tool_registry=tools,
        project_root=project_root,
        max_turns=max_turns_from_env(),
        renderer=ui,
        permission_checker=_request_cli_permission,
    )

    try:
        ui.info("输入 /help 查看命令，输入 /exit 退出。")
        while True:
            try:
                user_input = ui.prompt().strip()
            except (EOFError, KeyboardInterrupt):
                ui.goodbye()
                return 0

            if not user_input:
                continue

            # 斜杠命令由 CLI 自己处理，普通输入才交给 Agent。
            command = user_input.lower()
            if command in {"/exit", "/quit", "exit", "quit"}:
                ui.goodbye()
                return 0
            if command == "/help":
                ui.help(tools)
                continue
            if command == "/clear":
                agent.messages = []
                ui.info("history cleared")
                continue

            agent.run(user_input)
    finally:
        if mcp_manager is not None:
            mcp_manager.close_all()


def build_tool_registry(
    project_root: Path | None = None,
    mcp_manager: McpManager | None = None,
) -> ToolRegistry:
    """创建结构化工具集合。"""

    return build_structured_tool_registry(project_root, mcp_manager=mcp_manager)


def create_mcp_manager(
    project_root: Path,
    reporter: Callable[[str, str], None] | None = None,
) -> McpManager | None:
    """按项目配置创建并连接 MCP manager。"""

    try:
        manager = McpManager(project_root)
    except McpConfigError as exc:
        if reporter is not None:
            reporter("error", f"MCP config error: {exc}")
        return None

    if not manager.config.servers:
        return None

    connected = manager.connect_all()
    failed = [status for status in manager.statuses() if status.status == "failed"]
    if reporter is not None:
        if connected:
            reporter("info", f"MCP connected: {', '.join(connection.name for connection in connected)}")
        for status in failed:
            reporter("error", f"MCP server failed: {status.name}: {status.error}")
    return manager


def _request_cli_permission(request: ToolPermissionRequest) -> ToolPermissionResult:
    """在终端请求结构化工具权限。"""

    print(f"Permission required: {request.display_name} - {request.summary}")
    answer = input("Allow once? [y/N] ").strip().lower()
    if answer in {"y", "yes"}:
        return ToolPermissionResult.allow(reason="cli_allow_once")
    return ToolPermissionResult.deny("Tool execution denied by user.", reason="cli_denied")


def _streaming_enabled() -> bool:
    """读取流式输出开关。"""

    raw = os.getenv("ZZCODE_STREAM", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    raise SystemExit(main())
