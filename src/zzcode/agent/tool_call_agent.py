"""Structured tool-call agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from zzcode.llm.client import ChatClient, LLMToolCall
from zzcode.tools.base import PermissionChecker, ToolCall, ToolContext
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult as StructuredToolResult
from zzcode.tools.runner import ToolRunner
from zzcode.ui.messages import (
    AssistantThought,
    FinalAnswer,
    StepStarted,
    SystemNotice,
    ToolResult,
    ToolUse,
)
from zzcode.ui.renderer import PlainInlineRenderer


DEFAULT_SYSTEM_PROMPT = """
你是 ZzCode，一个可以通过结构化工具调用帮助用户阅读、修改和验证代码的编程助手。

规则：
1. 需要查看文件、写文件或运行命令时，使用可用 tools，不要编造结果。
2. 工具参数必须是 JSON object。
3. 工具返回后，根据 tool result 继续判断下一步；如果已经足够回答，直接给出最终答案。
4. 不要输出旧文本 ReAct 的 Action 协议。
""".strip()


class TranscriptSink(Protocol):
    """Agent 可选的 transcript 记录接口。"""

    def record_tool_use(self, tool_name: str, tool_input: object) -> None: ...

    def record_tool_result(self, tool_name: str, output: str, ok: bool = True) -> None: ...


class ToolCallAgent:
    """OpenAI-compatible tool_calls Agent。

    llm_client 负责返回结构化 tool_calls；runner 负责执行工具；
    run() 返回最终答案，模型未完成时返回 None。
    """

    def __init__(
        self,
        llm_client: ChatClient,
        tool_registry: ToolRegistry,
        project_root: Path,
        max_steps: int = 5,
        renderer: object | None = None,
        permission_checker: PermissionChecker | None = None,
        transcript_sink: TranscriptSink | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        runner: ToolRunner | None = None,
        session_id: str = "",
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.project_root = project_root.resolve()
        self.max_steps = max_steps
        self.renderer = renderer or PlainInlineRenderer()
        self.permission_checker = permission_checker
        self.transcript_sink = transcript_sink
        self.system_prompt = system_prompt
        self.runner = runner or ToolRunner(tool_registry)
        self.session_id = session_id
        self.messages: list[dict[str, Any]] = []

    def run(self, question: str, session_context: str = "") -> str | None:
        """执行结构化 tool call 循环。"""

        self.messages = self._initial_messages(question, session_context)

        for step in range(1, self.max_steps + 1):
            self.renderer.render(StepStarted(step, self.max_steps))
            response = self.llm_client.chat(
                self.messages,
                tools=self.tool_registry.to_openai_tools(),
            )
            if response is None:
                self.renderer.render(SystemNotice("LLM returned no response.", "error"))
                return None

            if response.content and response.tool_calls:
                self.renderer.render(AssistantThought(response.content))

            assistant_message = _assistant_message(response.content, response.tool_calls)
            self.messages.append(assistant_message)

            if not response.tool_calls:
                final_answer = response.content
                self.renderer.render(FinalAnswer(final_answer))
                return final_answer

            for llm_tool_call in response.tool_calls:
                result = self._run_tool_call(llm_tool_call)
                self.messages.append(result.to_openai_message())
                if _is_user_denied_tool_result(result):
                    self.renderer.render(SystemNotice("用户已拒绝工具执行，本轮任务已停止。", "warning"))
                    return None

        self.renderer.render(SystemNotice("Stopped: max steps reached.", "warning"))
        return None

    def _run_tool_call(self, llm_tool_call: LLMToolCall) -> StructuredToolResult:
        tool = self.tool_registry.get(llm_tool_call.name)
        display_name = tool.display_name if tool else None
        source = getattr(tool, "source", "local") if tool else "unknown"
        mcp_info = getattr(tool, "mcp_info", None) if tool else None
        self.renderer.render(
            ToolUse(
                llm_tool_call.name,
                llm_tool_call.arguments,
                display_name,
                id=llm_tool_call.id,
                source=source,
                mcp_info=mcp_info,
            )
        )
        if self.transcript_sink:
            self.transcript_sink.record_tool_use(llm_tool_call.name, llm_tool_call.arguments)

        if llm_tool_call.parse_error:
            result = StructuredToolResult.failure(
                llm_tool_call.id,
                llm_tool_call.name,
                llm_tool_call.parse_error,
                metadata={"reason": "arguments_parse_error"},
            )
        else:
            context = ToolContext(
                project_root=self.project_root,
                session_id=self.session_id,
                permission_checker=self.permission_checker,
            )
            result = self.runner.run(
                ToolCall(
                    id=llm_tool_call.id,
                    name=llm_tool_call.name,
                    args=llm_tool_call.arguments,
                    raw=llm_tool_call.raw,
                ),
                context,
            )

        if self.transcript_sink:
            self.transcript_sink.record_tool_result(llm_tool_call.name, result.content, ok=result.ok)
        self.renderer.render(
            ToolResult(
                llm_tool_call.name,
                result.content,
                id=llm_tool_call.id,
                ok=result.ok,
                source=source,
                mcp_info=mcp_info,
            )
        )
        return result

    def _initial_messages(self, question: str, session_context: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        if session_context:
            messages.append({"role": "system", "content": f"Session context:\n{session_context}"})
        messages.append({"role": "user", "content": question})
        return messages


def _assistant_message(content: str, tool_calls: list[LLMToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = [_openai_tool_call(tool_call) for tool_call in tool_calls]
    return message


def _openai_tool_call(tool_call: LLMToolCall) -> dict[str, Any]:
    if tool_call.raw:
        return tool_call.raw
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
        },
    }


def _is_user_denied_tool_result(result: StructuredToolResult) -> bool:
    return result.metadata.get("reason") == "user_denied"
