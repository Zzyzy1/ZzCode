"""JSON Lines backend used by the React + Ink frontend."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, TextIO

from zzcode.agent.context_budget import calculate_context_budget_state, max_turns_from_env
from zzcode.agent.tool_call_agent import ToolCallAgent
from zzcode.cli.main import build_tool_registry, create_mcp_manager
from zzcode.llm.client import ZzCodeLLM
from zzcode.logging import (
    configure_logging_context,
    flush_debug_logs,
    get_current_debug_log_path,
    log_debug,
    log_error,
)
from zzcode.memory import ShortTermSessionMemory, TranscriptRecorder, build_memory_context, create_session_scope
from zzcode.protocol.events import JsonLineEventWriter, JsonLineRenderer
from zzcode.subagents import SystemAgentScheduler, SystemAgentScheduleResult, SystemAgentSchedulerResult
from zzcode.tools.base import ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.builtin import WRITE_FILE_SEPARATOR
from zzcode.tools.local.agent import AgentTool
from zzcode.tools.safety import resolve_project_path


MAX_DIFF_PREVIEW_LINES = 80


def main(argv: list[str] | None = None) -> int:
    """启动 JSONL 协议服务。

    argv 是命令行参数；返回进程退出码。
    """

    _configure_stdio()

    parser = argparse.ArgumentParser(description="Run ZzCode Agent over JSON Lines.")
    parser.add_argument("--once", action="store_true", help="process stdin until EOF and exit")
    args = parser.parse_args(argv)

    writer = JsonLineEventWriter()
    project_root = Path(os.getenv("ZZCODE_PROJECT_ROOT") or Path.cwd()).resolve()
    configure_logging_context(project_root=project_root)

    session_scope = create_session_scope(project_root)
    configure_logging_context(session_id=session_scope.session_id, project_root=project_root)
    log_debug(
        "server bootstrap "
        f"project_root={project_root} "
        f"session_id={session_scope.session_id} "
        f"debug_log={get_current_debug_log_path()}",
        level="info",
        component="protocol",
    )

    try:
        llm = ZzCodeLLM(stream=False)
    except Exception as exc:
        log_error(exc, component="llm", context={"phase": "initialize"})
        writer.write({"type": "system_notice", "level": "error", "text": f"LLM 初始化失败: {exc}"})
        return 1

    mcp_manager = create_mcp_manager(
        project_root,
        reporter=lambda level, message: writer.write(
            {"type": "system_notice", "level": level, "text": message}
        ),
    )
    transcript = TranscriptRecorder(session_scope)
    _debug_memory(
        "server started "
        f"project_root={project_root} "
        f"session_id={session_scope.session_id} "
        f"transcript={session_scope.transcript_path} "
        f"session_memory={session_scope.session_memory_path}"
    )
    permission_bridge = PermissionBridge(sys.stdin, writer, session_scope.session_id)
    session_memory = ShortTermSessionMemory()
    system_agents = SystemAgentScheduler(
        project_root=project_root,
        parent_scope=session_scope,
        llm_client=llm,
    )
    tools = build_tool_registry(project_root, mcp_manager=mcp_manager)
    tools.register(
        AgentTool(
            project_root=project_root,
            llm_client=llm,
            session_scope=session_scope,
            base_registry=tools,
            permission_checker=permission_bridge.request_structured_permission,
            session_context_provider=lambda: build_memory_context(
                project_root,
                session_memory.as_list(),
                compact_summary=session_memory.compact_summary(),
                current_session=session_scope,
            ).text,
        )
    )
    log_debug(
        f"tool registry ready tool_count={len(tools.to_openai_tools())}",
        level="info",
        component="protocol",
    )
    renderer = JsonLineRenderer(writer)
    agent = ToolCallAgent(
        llm_client=llm,
        tool_registry=tools,
        project_root=project_root,
        max_turns=max_turns_from_env(),
        renderer=renderer,
        permission_checker=permission_bridge.request_structured_permission,
        transcript_sink=transcript,
        session_id=session_scope.session_id,
    )

    for request in _read_requests(sys.stdin):
        turn_started_at = time.perf_counter()
        request_type = request.get("type")
        log_debug(
            f"request received type={request_type or 'unknown'} keys={','.join(sorted(str(key) for key in request.keys()))}",
            level="debug",
            component="protocol",
        )
        if request_type == "clear_history":
            _debug_memory(f"clear history previous_items={len(session_memory)}")
            session_memory.clear()
            agent.messages = []
            writer.write({"type": "system_notice", "level": "info", "text": "会话历史已清空。"})
            writer.write({"type": "request_done", "ok": True})
            continue
        if request_type == "compact_history":
            compact_update = system_agents.before_compact()
            _debug_system_agents("before compact", compact_update)
            result = session_memory.compact(reason="manual")
            _debug_memory(
                "manual compact "
                f"compacted={result.compacted} "
                f"reason={result.reason} "
                f"removed_items={result.removed_items} "
                f"kept_items={result.kept_items} "
                f"summary_chars={result.summary_chars}"
            )
            if result.compacted:
                transcript.record_compact(
                    trigger="manual",
                    removed_items=result.removed_items,
                    kept_items=result.kept_items,
                    summary=session_memory.compact_summary(),
                )
                writer.write(
                    {
                        "type": "system_notice",
                        "level": "info",
                        "text": (
                            "会话已压缩："
                            f"折叠 {result.removed_items} 条历史，"
                            f"保留 {result.kept_items} 条最近上下文。"
                        ),
                    }
                )
            else:
                writer.write({"type": "system_notice", "level": "info", "text": "当前会话历史还不需要压缩。"})
            writer.write({"type": "request_done", "ok": True})
            continue
        if request_type == "shutdown":
            writer.write({"type": "system_notice", "level": "info", "text": "Python 后端已关闭。"})
            writer.write({"type": "request_done", "ok": True})
            break

        text = _extract_user_text(request)
        if not text:
            writer.write({"type": "system_notice", "level": "warning", "text": "收到空任务，已忽略。"})
            writer.write({"type": "request_done", "ok": False})
            continue

        # 前端通过 user_message 发起请求；后端回显同一事件，让消息流完全来自协议。
        log_debug(
            f"turn start text_chars={len(text)} session_items={len(session_memory)}",
            level="info",
            component="protocol",
        )
        writer.write({"type": "user_message", "text": text})
        log_debug("turn user_message echoed", level="debug", component="protocol")
        transcript.begin_turn()
        transcript.record_user(text)
        memory_started_at = time.perf_counter()
        memory_context = build_memory_context(
            project_root,
            session_memory.as_list(),
            compact_summary=session_memory.compact_summary(),
            current_session=session_scope,
        )
        memory_elapsed_ms = (time.perf_counter() - memory_started_at) * 1000
        _debug_memory(
            "request "
            f"user={_compact_debug_text(text)} "
            f"session_id={session_scope.session_id} "
            f"instruction_files={memory_context.instruction_count} "
            f"instruction_chars={memory_context.instruction_chars} "
            f"session_items={memory_context.session_items} "
            f"auto_memory_chars={memory_context.auto_memory_chars} "
            f"current_session_memory_chars={memory_context.current_session_memory_chars} "
            f"compact_summary_chars={memory_context.compact_summary_chars} "
            f"session_notes_chars={memory_context.session_notes_chars} "
            f"context_chars={len(memory_context.text)} "
            f"elapsed_ms={memory_elapsed_ms:.1f}"
        )
        if memory_context.text:
            _debug_memory(f"context {_compact_debug_text(memory_context.text, max_length=500)}")

        estimated_tokens = agent.estimate_context_tokens(text, session_context=memory_context.text)
        budget_state = calculate_context_budget_state(estimated_tokens, config=agent.context_budget)
        log_debug(
            "turn context budget "
            f"estimated_tokens={budget_state.estimated_tokens} "
            f"percent_left={budget_state.percent_left} "
            f"auto_compact_at={budget_state.config.auto_compact_threshold} "
            f"blocking_at={budget_state.config.blocking_threshold} "
            f"auto_compact={budget_state.is_above_auto_compact_threshold} "
            f"blocking={budget_state.is_at_blocking_limit}",
            level="info",
            component="protocol",
        )
        if budget_state.is_above_auto_compact_threshold:
            compact_update = system_agents.before_compact()
            _debug_system_agents("before budget compact", compact_update)
            compact_result = session_memory.compact(reason="auto_context_budget")
            _debug_memory(
                "budget compact "
                f"compacted={compact_result.compacted} "
                f"reason={compact_result.reason} "
                f"removed_items={compact_result.removed_items} "
                f"kept_items={compact_result.kept_items} "
                f"summary_chars={compact_result.summary_chars}"
            )
            if compact_result.compacted:
                transcript.record_compact(
                    trigger="auto_context_budget",
                    removed_items=compact_result.removed_items,
                    kept_items=compact_result.kept_items,
                    summary=session_memory.compact_summary(),
                )
                writer.write(
                    {
                        "type": "system_notice",
                        "level": "info",
                        "text": (
                            "上下文接近上限，已自动压缩短期会话历史："
                            f"折叠 {compact_result.removed_items} 条，"
                            f"保留 {compact_result.kept_items} 条。"
                        ),
                    }
                )
                memory_context = build_memory_context(
                    project_root,
                    session_memory.as_list(),
                    compact_summary=session_memory.compact_summary(),
                    current_session=session_scope,
                )
                estimated_tokens = agent.estimate_context_tokens(text, session_context=memory_context.text)
                budget_state = calculate_context_budget_state(estimated_tokens, config=agent.context_budget)
                log_debug(
                    "turn context budget after compact "
                    f"estimated_tokens={budget_state.estimated_tokens} "
                    f"percent_left={budget_state.percent_left} "
                    f"blocking={budget_state.is_at_blocking_limit}",
                    level="info",
                    component="protocol",
                )

        if budget_state.is_at_blocking_limit:
            message = (
                "上下文已经接近模型上限，已停止本轮请求。"
                f"估算 {budget_state.estimated_tokens} tokens，"
                f"阻断阈值 {budget_state.config.blocking_threshold} tokens。"
                "请先 /compact 或清理会话历史后继续。"
            )
            writer.write({"type": "system_notice", "level": "warning", "text": message})
            log_debug(
                "turn blocked by context budget "
                f"estimated_tokens={budget_state.estimated_tokens} "
                f"blocking_at={budget_state.config.blocking_threshold}",
                level="warn",
                component="protocol",
            )
            transcript.end_turn()
            writer.write({"type": "request_done", "ok": False})
            continue

        agent_started_at = time.perf_counter()
        log_debug("agent run start", level="info", component="protocol")
        answer = agent.run(text, session_context=memory_context.text)
        agent_elapsed_ms = (time.perf_counter() - agent_started_at) * 1000
        log_debug(
            f"agent run end ok={answer is not None} answer_chars={len(answer or '')} elapsed_ms={agent_elapsed_ms:.1f}",
            level="info",
            component="protocol",
        )
        if answer:
            transcript.record_assistant(answer)
            removed_count = session_memory.record_turn(text, answer)
            if removed_count:
                _debug_memory(f"trimmed history removed_items={removed_count}")
            compact_result = session_memory.compact_if_needed()
            if compact_result.compacted:
                transcript.record_compact(
                    trigger="auto",
                    removed_items=compact_result.removed_items,
                    kept_items=compact_result.kept_items,
                    summary=session_memory.compact_summary(),
                )
                _debug_memory(
                    "auto compact "
                    f"removed_items={compact_result.removed_items} "
                    f"kept_items={compact_result.kept_items} "
                    f"summary_chars={compact_result.summary_chars}"
                )
                writer.write(
                    {
                        "type": "system_notice",
                        "level": "info",
                        "text": (
                            "已自动压缩短期会话历史："
                            f"折叠 {compact_result.removed_items} 条，"
                            f"保留 {compact_result.kept_items} 条。"
                        ),
                    }
                )
            _debug_memory(
                "saved turn "
                f"answer={_compact_debug_text(answer)} "
                f"session_items={len(session_memory)}"
            )
        else:
            _debug_memory("request finished without answer; turn was not saved")
        transcript.end_turn()
        writer.write({"type": "request_done", "ok": answer is not None})
        total_elapsed_ms = (time.perf_counter() - turn_started_at) * 1000
        log_debug(
            f"turn done ok={answer is not None} elapsed_ms={total_elapsed_ms:.1f}",
            level="info",
            component="protocol",
        )
        if answer:
            scheduled = system_agents.schedule_turn_finished()
            _debug_system_agents_schedule("turn finished", scheduled)

        if args.once:
            break

    drain_timeout = float(os.getenv("ZZCODE_SYSTEM_AGENTS_DRAIN_TIMEOUT") or "5")
    system_agents.close(timeout_seconds=drain_timeout)
    if mcp_manager is not None:
        mcp_manager.close_all()
    flush_debug_logs()
    return 0


def _read_requests(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    """读取 stdin 中的 JSON Lines 请求。

    lines 是输入行迭代器；返回解析后的请求字典，非法 JSON 会转为错误事件。
    """

    writer = JsonLineEventWriter()
    for raw_line in lines:
        received_at = time.perf_counter()
        line = raw_line.strip()
        if not line:
            continue
        log_debug(
            f"stdin line received bytes={len(raw_line.encode('utf-8'))}",
            level="debug",
            component="protocol",
        )
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            writer.write({"type": "system_notice", "level": "error", "text": f"请求 JSON 解析失败: {exc}"})
            continue
        if isinstance(value, dict):
            log_debug(
                f"stdin json parsed type={value.get('type') or 'unknown'} elapsed_ms={(time.perf_counter() - received_at) * 1000:.1f}",
                level="debug",
                component="protocol",
            )
            yield value
        else:
            writer.write({"type": "system_notice", "level": "warning", "text": "请求必须是 JSON object。"})


def _extract_user_text(request: dict[str, Any]) -> str:
    """从请求事件中提取用户文本。

    request 是前端发来的 JSON 对象；返回用户输入文本，不匹配时返回空字符串。
    """

    if request.get("type") != "user_message":
        return ""
    text = request.get("text")
    return text.strip() if isinstance(text, str) else ""


def _debug_memory(message: str) -> None:
    """输出记忆调试日志。"""

    if os.getenv("ZZCODE_DEBUG_MEMORY", "1").lower() in {"0", "false", "no"}:
        return
    log_debug(message, level="debug", component="memory")


def _debug_system_agents(label: str, result: SystemAgentSchedulerResult) -> None:
    """输出系统子 Agent 调度结果。"""

    session = result.session_memory
    auto = result.auto_memory
    parts = [label]
    if session is not None:
        parts.append(
            "session_memory="
            f"ran:{session.ran} updated:{session.updated} events:{session.event_count}"
        )
    if auto is not None:
        parts.append(
            "auto_memory="
            f"ran:{auto.ran} updated:{auto.updated} skipped:{auto.skipped} events:{auto.event_count}"
        )
    if result.errors:
        parts.append("errors=" + " | ".join(result.errors))
    log_debug(" ".join(parts), level="debug", component="system-agents")


def _debug_system_agents_schedule(label: str, result: SystemAgentScheduleResult) -> None:
    """输出系统子 Agent 后台调度结果。"""

    log_debug(
        f"{label} scheduled={result.scheduled} pending={result.pending} "
        f"disabled={result.disabled} reason={result.reason or '-'}",
        level="debug",
        component="system-agents",
    )


def _compact_debug_text(text: str, max_length: int = 160) -> str:
    """压缩调试文本，避免长对话把控制台刷满。"""

    compacted = " ".join(text.split())
    if len(compacted) <= max_length:
        return compacted
    return f"{compacted[:max_length]}..."


class PermissionBridge:
    """在工具执行前向前端请求权限。

    input_stream 是 JSONL 请求输入；writer 用于输出 permission_request；返回用户是否允许。
    """

    def __init__(self, input_stream: TextIO, writer: JsonLineEventWriter, session_id: str | None = None) -> None:
        self.input_stream = input_stream
        self.writer = writer
        self.session_id = session_id
        self._index = 0
        self._session_allowed_tools: set[str] = set()

    def request_permission(self, tool_name: str, tool_input: str, display_name: str | None = None) -> bool:
        """请求一次 legacy 文本工具执行权限。

        tool_name/tool_input 描述即将执行的工具；display_name 是 UI 展示名；返回是否允许执行。
        """

        result = self.request_structured_permission(
            ToolPermissionRequest(
                tool_call_id="",
                tool_name=tool_name,
                display_name=display_name or tool_name,
                args=_legacy_tool_input_to_args(tool_name, tool_input),
                summary=tool_input,
                is_destructive=_classify_tool_risk(tool_name) != "low",
            )
        )
        return result.behavior == "allow"

    def request_structured_permission(self, request: ToolPermissionRequest) -> ToolPermissionResult:
        """请求一次结构化工具执行权限。"""

        if _is_auto_allowed_memory_tool(request.tool_name, request.args, self.session_id):
            log_debug(
                f"permission auto allowed tool={request.tool_name} reason=memory_tool",
                level="debug",
                component="permission",
            )
            return ToolPermissionResult.allow(reason="auto_allowed_memory_tool")
        if request.tool_name in self._session_allowed_tools:
            log_debug(
                f"permission session allowed tool={request.tool_name}",
                level="debug",
                component="permission",
            )
            return ToolPermissionResult.allow(reason="session_allowed")

        self._index += 1
        request_id = f"permission-{self._index}"
        log_debug(
            f"permission request start id={request_id} tool={request.tool_name} destructive={request.is_destructive}",
            level="info",
            component="permission",
        )
        permission_started_at = time.perf_counter()
        self.writer.write(
            {
                "type": "permission_request",
                "id": request_id,
                "toolCallId": request.tool_call_id,
                "toolName": request.tool_name,
                "displayName": request.display_name,
                "input": request.args,
                "summary": request.summary,
                "isDestructive": request.is_destructive,
                "risk": _classify_tool_risk(request.tool_name),
                "preview": _build_permission_preview(request.tool_name, request.args),
                "source": request.source,
                "mcpInfo": request.mcp_info,
            }
        )

        # Agent 正在等待用户选择，此时 stdin 的下一条有效消息应该是 permission_response。
        for response in _read_requests(self.input_stream):
            if response.get("type") != "permission_response":
                self.writer.write({"type": "system_notice", "level": "warning", "text": "等待权限确认时忽略了非权限响应。"})
                continue
            if response.get("id") != request_id:
                self.writer.write({"type": "system_notice", "level": "warning", "text": "权限响应 id 不匹配，已忽略。"})
                continue

            decision = response.get("decision")
            if decision == "allow_session":
                self._session_allowed_tools.add(request.tool_name)
                log_debug(
                    f"permission request end id={request_id} decision=allow_session elapsed_ms={(time.perf_counter() - permission_started_at) * 1000:.1f}",
                    level="info",
                    component="permission",
                )
                return ToolPermissionResult.allow(reason="allow_session")
            if decision == "allow_once":
                log_debug(
                    f"permission request end id={request_id} decision=allow_once elapsed_ms={(time.perf_counter() - permission_started_at) * 1000:.1f}",
                    level="info",
                    component="permission",
                )
                return ToolPermissionResult.allow(reason="allow_once")
            log_debug(
                f"permission request end id={request_id} decision=deny elapsed_ms={(time.perf_counter() - permission_started_at) * 1000:.1f}",
                level="info",
                component="permission",
            )
            return ToolPermissionResult.deny("Tool execution denied by user.", reason="user_denied")

        log_debug(
            f"permission request end id={request_id} decision=stream_ended elapsed_ms={(time.perf_counter() - permission_started_at) * 1000:.1f}",
            level="warn",
            component="permission",
        )
        return ToolPermissionResult.deny("Permission response stream ended.", reason="permission_stream_ended")


def _classify_tool_risk(tool_name: str) -> str:
    """按工具名粗略分类风险。

    tool_name 是待执行工具；返回 low/medium/high，用于前端选择展示颜色。
    """

    if tool_name == "run_shell":
        return "high"
    if tool_name in {"write_file", "edit_file", "append_file"}:
        return "medium"
    if _is_mcp_tool_name(tool_name):
        return "medium"
    return "low"


def _is_mcp_tool_name(tool_name: str) -> bool:
    return tool_name.startswith("mcp__")


def _mcp_info_from_tool_name(tool_name: str) -> dict[str, str] | None:
    if not _is_mcp_tool_name(tool_name):
        return None
    remainder = tool_name[len("mcp__") :]
    server_name, separator, short_name = remainder.partition("__")
    if separator != "__" or not server_name or not short_name:
        return None
    return {"server_name": server_name, "tool_name": short_name}


def _build_permission_preview(tool_name: str, tool_input: object) -> dict[str, Any] | None:
    """为权限确认生成轻量预览。

    tool_name/tool_input 描述待执行工具；返回前端可渲染的预览对象，普通工具返回 None。
    """

    legacy_input = _tool_input_to_legacy_text(tool_name, tool_input)
    if tool_name == "write_file":
        return _build_write_file_diff_preview(legacy_input)
    if tool_name == "edit_file":
        return _build_edit_file_diff_preview(legacy_input)
    if tool_name == "append_file":
        return _build_append_file_diff_preview(legacy_input)
    return None


def _is_auto_allowed_memory_tool(tool_name: str, tool_input: object, session_id: str | None = None) -> bool:
    """判断普通文件工具是否只访问 Auto Memory markdown。"""

    if tool_name not in {"read_file", "write_file", "edit_file", "append_file"}:
        return False
    path_text = _extract_file_tool_path(tool_name, tool_input)
    if not path_text:
        return False
    try:
        path = resolve_project_path(_project_root(), path_text)
    except Exception:
        return False
    project_root = _project_root()
    memory_dir = (project_root / ".zzcode" / "memory").resolve()
    if _path_is_under(path, memory_dir) and path.suffix.lower() == ".md":
        return True
    if not session_id:
        return False
    session_dir = (project_root / ".zzcode" / "sessions" / session_id).resolve()
    session_memory_dir = (session_dir / "session-memory").resolve()
    if _path_is_under(path, session_memory_dir) and path.suffix.lower() == ".md":
        return True
    return path == session_dir / "transcript.jsonl"


def _path_is_under(path: Path, parent: Path) -> bool:
    """判断 path 是否位于 parent 目录内。"""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _extract_file_tool_path(tool_name: str, tool_input: object) -> str:
    """从普通文件工具参数中提取路径部分。"""

    if isinstance(tool_input, dict):
        path = tool_input.get("path")
        return path.strip() if isinstance(path, str) else ""
    if not isinstance(tool_input, str):
        return ""
    if tool_name == "read_file":
        return tool_input.strip()
    if tool_name in {"write_file", "edit_file", "append_file"}:
        return tool_input.split(WRITE_FILE_SEPARATOR, 1)[0].strip()
    return ""


def _legacy_tool_input_to_args(tool_name: str, tool_input: str) -> dict[str, Any]:
    """把旧文本工具参数转换成结构化权限参数。"""

    if tool_name == "read_file":
        return {"path": tool_input}
    if tool_name in {"write_file", "append_file"} and WRITE_FILE_SEPARATOR in tool_input:
        path, content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
        return {"path": path, "content": content}
    if tool_name == "edit_file":
        parts = tool_input.split(WRITE_FILE_SEPARATOR, 2)
        if len(parts) == 3:
            return {"path": parts[0], "old_text": parts[1], "new_text": parts[2]}
    if tool_name == "run_shell":
        return {"command": tool_input}
    return {"input": tool_input}


def _tool_input_to_legacy_text(tool_name: str, tool_input: object) -> str:
    """把结构化工具参数转换成旧 diff 预览可复用的文本格式。"""

    if isinstance(tool_input, str):
        return tool_input
    if not isinstance(tool_input, dict):
        return str(tool_input)
    if tool_name == "read_file":
        return str(tool_input.get("path") or "")
    if tool_name in {"write_file", "append_file"}:
        return f"{tool_input.get('path') or ''}{WRITE_FILE_SEPARATOR}{tool_input.get('content') or ''}"
    if tool_name == "edit_file":
        return (
            f"{tool_input.get('path') or ''}{WRITE_FILE_SEPARATOR}"
            f"{tool_input.get('old_text') or ''}{WRITE_FILE_SEPARATOR}"
            f"{tool_input.get('new_text') or ''}"
        )
    if tool_name == "run_shell":
        return str(tool_input.get("command") or "")
    return json.dumps(tool_input, ensure_ascii=False)


def _project_root() -> Path:
    """读取当前协议服务的项目根目录。"""

    return Path(os.getenv("ZZCODE_PROJECT_ROOT") or Path.cwd()).resolve()


def _build_write_file_diff_preview(tool_input: str) -> dict[str, Any]:
    """生成 write_file 的写入前 diff。

    tool_input 使用 path|||content 文本协议；返回有限行数的 unified diff 预览。
    """

    if WRITE_FILE_SEPARATOR not in tool_input:
        return {
            "type": "write_file_diff",
            "path": "",
            "fileExists": False,
            "error": f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}content",
        }

    path_text, new_content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
    project_root = _project_root()

    try:
        path = resolve_project_path(project_root, path_text)
        relative_path = str(path.relative_to(project_root))
    except Exception as exc:
        return {
            "type": "write_file_diff",
            "path": path_text.strip(),
            "fileExists": False,
            "error": str(exc),
        }

    old_content = ""
    file_exists = path.exists()
    if file_exists:
        if not path.is_file():
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": "目标路径不是文件。",
            }
        try:
            old_content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": "目标文件不是 UTF-8 文本，无法生成 diff。",
            }
        except OSError as exc:
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": f"读取旧文件失败: {exc}",
            }

    diff_lines = _unified_diff_lines(relative_path, old_content, new_content, file_exists)
    truncated = len(diff_lines) > MAX_DIFF_PREVIEW_LINES
    return {
        "type": "write_file_diff",
        "path": relative_path,
        "fileExists": file_exists,
        "oldLineCount": len(old_content.splitlines()),
        "newLineCount": len(new_content.splitlines()),
        "lines": diff_lines[:MAX_DIFF_PREVIEW_LINES],
        "truncated": truncated,
    }


def _build_edit_file_diff_preview(tool_input: str) -> dict[str, Any]:
    """生成 edit_file 的写入前 diff。"""

    parts = tool_input.split(WRITE_FILE_SEPARATOR, 2)
    if len(parts) != 3:
        return {
            "type": "write_file_diff",
            "path": "",
            "fileExists": False,
            "error": f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}old_text{WRITE_FILE_SEPARATOR}new_text",
        }

    path_text, old_text, new_text = parts
    try:
        path = resolve_project_path(_project_root(), path_text)
        relative_path = str(path.relative_to(_project_root()))
    except Exception as exc:
        return {"type": "write_file_diff", "path": path_text.strip(), "fileExists": False, "error": str(exc)}

    if not path.exists() or not path.is_file():
        return {"type": "write_file_diff", "path": relative_path, "fileExists": path.exists(), "error": "目标文件不存在或不是文件。"}
    try:
        old_content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"type": "write_file_diff", "path": relative_path, "fileExists": True, "error": "目标文件不是 UTF-8 文本。"}
    except OSError as exc:
        return {"type": "write_file_diff", "path": relative_path, "fileExists": True, "error": f"读取旧文件失败: {exc}"}

    count = old_content.count(old_text)
    if count != 1:
        return {
            "type": "write_file_diff",
            "path": relative_path,
            "fileExists": True,
            "error": f"old_text 匹配次数为 {count}，需要唯一匹配。",
        }
    new_content = old_content.replace(old_text, new_text, 1)
    diff_lines = _unified_diff_lines(relative_path, old_content, new_content, True)
    return {
        "type": "write_file_diff",
        "path": relative_path,
        "fileExists": True,
        "oldLineCount": len(old_content.splitlines()),
        "newLineCount": len(new_content.splitlines()),
        "lines": diff_lines[:MAX_DIFF_PREVIEW_LINES],
        "truncated": len(diff_lines) > MAX_DIFF_PREVIEW_LINES,
    }


def _build_append_file_diff_preview(tool_input: str) -> dict[str, Any]:
    """生成 append_file 的写入前 diff。"""

    if WRITE_FILE_SEPARATOR not in tool_input:
        return {
            "type": "write_file_diff",
            "path": "",
            "fileExists": False,
            "error": f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}content",
        }

    path_text, content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
    try:
        project_root = _project_root()
        path = resolve_project_path(project_root, path_text)
        relative_path = str(path.relative_to(project_root))
    except Exception as exc:
        return {"type": "write_file_diff", "path": path_text.strip(), "fileExists": False, "error": str(exc)}

    file_exists = path.exists()
    old_content = ""
    if file_exists:
        if not path.is_file():
            return {"type": "write_file_diff", "path": relative_path, "fileExists": True, "error": "目标路径不是文件。"}
        try:
            old_content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"type": "write_file_diff", "path": relative_path, "fileExists": True, "error": "目标文件不是 UTF-8 文本。"}
        except OSError as exc:
            return {"type": "write_file_diff", "path": relative_path, "fileExists": True, "error": f"读取旧文件失败: {exc}"}

    separator = "\n" if old_content and not old_content.endswith("\n") and content else ""
    new_content = old_content + separator + content
    diff_lines = _unified_diff_lines(relative_path, old_content, new_content, file_exists)
    return {
        "type": "write_file_diff",
        "path": relative_path,
        "fileExists": file_exists,
        "oldLineCount": len(old_content.splitlines()),
        "newLineCount": len(new_content.splitlines()),
        "lines": diff_lines[:MAX_DIFF_PREVIEW_LINES],
        "truncated": len(diff_lines) > MAX_DIFF_PREVIEW_LINES,
    }


def _unified_diff_lines(path: str, old_content: str, new_content: str, file_exists: bool) -> list[dict[str, str]]:
    """把新旧文本转换成前端展示用 diff 行。

    path 是相对路径；old_content/new_content 是写入前后文本；返回带类型的行列表。
    """

    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    if old_content == new_content:
        return [{"kind": "context", "text": "(no changes)"}]

    fromfile = f"a/{path}" if file_exists else "/dev/null"
    tofile = f"b/{path}"
    raw_lines = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, lineterm="")

    diff_lines: list[dict[str, str]] = []
    for line in raw_lines:
        if line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
            kind = "header"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        else:
            kind = "context"
        diff_lines.append({"kind": kind, "text": line})
    return diff_lines


def _configure_stdio() -> None:
    """固定标准输入输出编码。

    无入参；不返回值。Windows 默认编码可能不是 UTF-8，JSONL 协议必须显式统一编码。
    """

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
