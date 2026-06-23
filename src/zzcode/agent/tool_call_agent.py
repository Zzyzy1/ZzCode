"""Structured tool-call agent."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from zzcode.agent.context_budget import (
    ContextBudgetConfig,
    check_context_budget,
    max_turns_from_env,
)
from zzcode.llm.client import ChatClient, LLMToolCall
from zzcode.logging import log_debug
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
        max_steps: int | None = None,
        max_turns: int | None = None,
        renderer: object | None = None,
        permission_checker: PermissionChecker | None = None,
        transcript_sink: TranscriptSink | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        runner: ToolRunner | None = None,
        session_id: str = "",
        context_budget: ContextBudgetConfig | None = None,
        max_consecutive_failures: int = 3,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.project_root = project_root.resolve()
        self.max_steps = max_turns if max_turns is not None else (max_steps if max_steps is not None else max_turns_from_env())
        self.renderer = renderer or PlainInlineRenderer()
        self.permission_checker = permission_checker
        self.transcript_sink = transcript_sink
        self.system_prompt = system_prompt
        self.runner = runner or ToolRunner(tool_registry)
        self.session_id = session_id
        self.context_budget = context_budget or ContextBudgetConfig.from_env()
        self.max_consecutive_failures = max_consecutive_failures
        self.messages: list[dict[str, Any]] = []

    def run(self, question: str, session_context: str = "") -> str | None:
        """执行结构化 tool call 循环。"""

        run_started_at = time.perf_counter()
        self.messages = self._initial_messages(question, session_context)
        tools = self.tool_registry.to_openai_tools()
        consecutive_failures = 0
        log_debug(
            "run start "
            f"question_chars={len(question)} "
            f"session_context_chars={len(session_context)} "
            f"initial_messages={len(self.messages)} "
            f"tools={len(tools)} "
            f"max_turns={self.max_steps}",
            level="info",
            component="agent",
        )

        for step in range(1, self.max_steps + 1):
            step_started_at = time.perf_counter()
            budget_state = check_context_budget(self.messages, tools=tools, config=self.context_budget)
            log_debug(
                "context budget "
                f"step={step} "
                f"estimated_tokens={budget_state.estimated_tokens} "
                f"percent_left={budget_state.percent_left} "
                f"auto_compact_at={budget_state.config.auto_compact_threshold} "
                f"blocking_at={budget_state.config.blocking_threshold} "
                f"blocking={budget_state.is_at_blocking_limit}",
                level="info",
                component="agent",
            )
            if budget_state.is_at_blocking_limit:
                message = (
                    "Stopped: context budget exceeded "
                    f"({budget_state.estimated_tokens}/{budget_state.config.blocking_threshold} tokens)."
                )
                self.renderer.render(SystemNotice(message, "warning"))
                log_debug(
                    "run end "
                    "reason=context_budget_exceeded "
                    f"step={step} "
                    f"estimated_tokens={budget_state.estimated_tokens} "
                    f"elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
                    level="warn",
                    component="agent",
                )
                return None
            log_debug(
                f"step start step={step} messages={len(self.messages)}",
                level="info",
                component="agent",
            )
            self.renderer.render(StepStarted(step, self.max_steps))
            llm_started_at = time.perf_counter()
            response = self.llm_client.chat(
                self.messages,
                tools=tools,
            )
            log_debug(
                f"step llm returned step={step} ok={response is not None} elapsed_ms={(time.perf_counter() - llm_started_at) * 1000:.1f}",
                level="info",
                component="agent",
            )
            if response is None:
                self.renderer.render(SystemNotice("LLM returned no response.", "error"))
                log_debug(
                    f"run end reason=llm_none elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
                    level="warn",
                    component="agent",
                )
                return None

            if response.content and response.tool_calls:
                self.renderer.render(AssistantThought(response.content))

            assistant_message = _assistant_message(response.content, response.tool_calls)
            self.messages.append(assistant_message)

            if not response.tool_calls:
                final_answer = response.content
                self.renderer.render(FinalAnswer(final_answer))
                log_debug(
                    "run end "
                    "reason=final_answer "
                    f"step={step} "
                    f"answer_chars={len(final_answer)} "
                    f"step_elapsed_ms={(time.perf_counter() - step_started_at) * 1000:.1f} "
                    f"elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
                    level="info",
                    component="agent",
                )
                return final_answer

            log_debug(
                f"step tool_calls step={step} count={len(response.tool_calls)} content_chars={len(response.content)}",
                level="info",
                component="agent",
            )
            for llm_tool_call in response.tool_calls:
                result = self._run_tool_call(llm_tool_call)
                self.messages.append(result.to_openai_message())
                if _is_user_denied_tool_result(result):
                    self.renderer.render(SystemNotice("用户已拒绝工具执行，本轮任务已停止。", "warning"))
                    log_debug(
                        f"run end reason=user_denied step={step} elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
                        level="warn",
                        component="agent",
                    )
                    return None
                if _counts_as_loop_failure(result):
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                if consecutive_failures >= self.max_consecutive_failures:
                    self.renderer.render(SystemNotice("Stopped: repeated tool failures.", "warning"))
                    log_debug(
                        "run end "
                        "reason=repeated_tool_failures "
                        f"step={step} "
                        f"consecutive_failures={consecutive_failures} "
                        f"elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
                        level="warn",
                        component="agent",
                    )
                    return None
            log_debug(
                f"step end step={step} elapsed_ms={(time.perf_counter() - step_started_at) * 1000:.1f} messages={len(self.messages)}",
                level="info",
                component="agent",
            )

        self.renderer.render(SystemNotice(f"Stopped: maximum turns reached ({self.max_steps}).", "warning"))
        log_debug(
            f"run end reason=max_turns max_turns={self.max_steps} elapsed_ms={(time.perf_counter() - run_started_at) * 1000:.1f}",
            level="warn",
            component="agent",
        )
        return None

    def estimate_context_tokens(self, question: str, session_context: str = "") -> int:
        """估算一次新 turn 初始上下文 token 数。"""

        return check_context_budget(
            self._initial_messages(question, session_context),
            tools=self.tool_registry.to_openai_tools(),
            config=self.context_budget,
        ).estimated_tokens

    def _run_tool_call(self, llm_tool_call: LLMToolCall) -> StructuredToolResult:
        tool_started_at = time.perf_counter()
        tool = self.tool_registry.get(llm_tool_call.name)
        display_name = tool.display_name if tool else None
        source = getattr(tool, "source", "local") if tool else "unknown"
        mcp_info = getattr(tool, "mcp_info", None) if tool else None
        log_debug(
            "tool call start "
            f"id={llm_tool_call.id} "
            f"name={llm_tool_call.name} "
            f"source={source} "
            f"arg_keys={','.join(sorted(str(key) for key in llm_tool_call.arguments.keys()))}",
            level="info",
            component="agent",
        )
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
        log_debug(
            "tool call end "
            f"id={llm_tool_call.id} "
            f"name={llm_tool_call.name} "
            f"ok={result.ok} "
            f"result_chars={len(result.content)} "
            f"elapsed_ms={(time.perf_counter() - tool_started_at) * 1000:.1f}",
            level="info",
            component="agent",
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


def _counts_as_loop_failure(result: StructuredToolResult) -> bool:
    if result.ok:
        return False
    return result.metadata.get("reason") in {
        "arguments_parse_error",
        "invalid_arguments",
        "unknown_tool",
        "validation_failed",
        "tool_exception",
    }
