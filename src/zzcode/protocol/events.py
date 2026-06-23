"""JSON Lines event helpers shared by protocol server code."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, TextIO

from zzcode.logging import log_debug
from zzcode.ui.messages import (
    AssistantDelta,
    AssistantThought,
    FinalAnswer,
    StepStarted,
    SubagentDone,
    SubagentStarted,
    SubagentToolResult,
    SubagentToolUse,
    SystemNotice,
    ToolResult,
    ToolUse,
    UiMessage,
)


class JsonLineEventWriter:
    """把 UI 消息写成 JSON Lines。

    output 是目标输出流；write() 接收事件字典，不返回值。
    """

    def __init__(self, output: TextIO | None = None) -> None:
        self.output = output or sys.stdout

    def write(self, event: dict[str, Any]) -> None:
        """输出一条协议事件。

        event 是可 JSON 序列化的字典；函数会立即 flush，方便前端实时渲染。
        """

        started_at = time.perf_counter()
        line = json.dumps(event, ensure_ascii=False)
        self.output.write(f"{line}\n")
        self.output.flush()
        log_debug(
            "event written "
            f"type={event.get('type') or 'unknown'} "
            f"bytes={len(line.encode('utf-8'))} "
            f"elapsed_ms={(time.perf_counter() - started_at) * 1000:.1f}",
            level="debug",
            component="protocol",
        )


class JsonLineRenderer:
    """把 Python UI Message 转换成前端 AgentEvent。

    writer 负责实际输出；render() 接收 UiMessage，不返回值。
    """

    def __init__(self, writer: JsonLineEventWriter | None = None) -> None:
        self.writer = writer or JsonLineEventWriter()
        self._tool_call_index = 0
        self._last_tool_id_by_name: dict[str, str] = {}

    def render(self, message: UiMessage) -> None:
        """渲染一条 UI 消息。

        message 是 Python Agent 产生的消息对象；函数会转换并输出 JSONL 事件。
        """

        event = self._to_event(message)
        if event is not None:
            self.writer.write(event)

    def _to_event(self, message: UiMessage) -> dict[str, Any] | None:
        """把内部消息模型转换为协议事件。

        message 是 UiMessage；返回前端可识别的事件字典，StepStarted 当前不展示。
        """

        if isinstance(message, StepStarted):
            return None
        if isinstance(message, AssistantDelta):
            return {"type": "assistant_delta", "text": message.text}
        if isinstance(message, AssistantThought):
            return {"type": "assistant_thought", "text": message.text}
        if isinstance(message, ToolUse):
            tool_id = message.id or self._next_tool_id(message.name)
            self._last_tool_id_by_name[message.name] = tool_id
            return {
                "type": "tool_use",
                "id": tool_id,
                "name": message.name,
                "displayName": message.display_name,
                "input": message.tool_input,
                "source": message.source,
                "mcpInfo": message.mcp_info,
            }
        if isinstance(message, ToolResult):
            return {
                "type": "tool_result",
                "id": message.id or self._last_tool_id_by_name.get(message.tool_name, message.tool_name),
                "name": message.tool_name,
                "ok": message.ok if message.ok is not None else not _looks_like_error(message.output),
                "output": message.output,
                "source": message.source,
                "mcpInfo": message.mcp_info,
            }
        if isinstance(message, FinalAnswer):
            return {"type": "assistant_final", "text": message.text}
        if isinstance(message, SystemNotice):
            return {"type": "system_notice", "level": message.level, "text": message.text}
        if isinstance(message, SubagentStarted):
            return {
                "type": "subagent_start",
                "agentId": message.agent_id,
                "name": message.name,
                "description": message.description,
                "transcriptPath": message.transcript_path,
            }
        if isinstance(message, SubagentToolUse):
            tool_id = message.id or self._next_tool_id(f"subagent-{message.name}")
            self._last_tool_id_by_name[f"{message.agent_id}:{message.name}"] = tool_id
            return {
                "type": "subagent_tool_use",
                "agentId": message.agent_id,
                "id": tool_id,
                "name": message.name,
                "displayName": message.display_name,
                "input": message.tool_input,
                "source": message.source,
                "mcpInfo": message.mcp_info,
            }
        if isinstance(message, SubagentToolResult):
            key = f"{message.agent_id}:{message.tool_name}"
            return {
                "type": "subagent_tool_result",
                "agentId": message.agent_id,
                "id": message.id or self._last_tool_id_by_name.get(key, message.tool_name),
                "name": message.tool_name,
                "ok": message.ok if message.ok is not None else not _looks_like_error(message.output),
                "output": message.output,
                "outputPreview": _preview_text(message.output),
                "source": message.source,
                "mcpInfo": message.mcp_info,
            }
        if isinstance(message, SubagentDone):
            return {
                "type": "subagent_done",
                "agentId": message.agent_id,
                "name": message.name,
                "ok": message.ok,
                "transcriptPath": message.transcript_path,
                "error": message.error,
            }
        return {"type": "system_notice", "level": "warning", "text": "未知 UI 消息类型。"}

    def _next_tool_id(self, tool_name: str) -> str:
        """生成工具调用 id。

        tool_name 用于让 id 可读；返回当前进程内递增的工具调用标识。
        """

        self._tool_call_index += 1
        return f"{tool_name}-{self._tool_call_index}"


def _looks_like_error(output: str) -> bool:
    """粗略判断工具输出是否为错误。

    output 是工具返回文本；返回 True 表示前端应按失败样式展示。
    """

    prefixes = (
        "Error:",
        "错误",
        "失败",
        "写入失败",
        "读取失败",
        "命令被拒绝",
        "Tool execution denied",
        "文件不存在",
        "不是文件",
        "路径不存在",
        "不是目录",
        "参数格式错误",
        "路径越界",
        "文件过大",
    )
    return output.strip().startswith(prefixes)


def _preview_text(text: str, max_length: int = 1000) -> str:
    compact = text.strip()
    if len(compact) <= max_length:
        return compact
    return compact[:max_length] + "\n... (truncated)"
