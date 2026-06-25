"""Structured tool-call agent."""

from __future__ import annotations

import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from zzcode.agent.context_budget import (
    ContextBudgetConfig,
    check_context_budget,
    max_turns_from_env,
)
from zzcode.context import (
    build_date_change_context_message,
    build_user_context_message,
    get_runtime_user_context,
)
from zzcode.llm.client import ChatClient, LLMResponse, LLMToolCall
from zzcode.logging import log_debug
from zzcode.tools.base import PermissionChecker, ToolCall, ToolContext
from zzcode.tools.local.web_fetch_summarizer import LLMWebFetchSummarizer
from zzcode.tools.local.web_limits import WebToolBudget
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult as StructuredToolResult
from zzcode.tools.runner import ToolRunner
from zzcode.ui.messages import (
    AssistantDelta,
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

_MAX_TOOL_CONCURRENCY_ENV = "ZZCODE_MAX_TOOL_CONCURRENCY"
_DEFAULT_MAX_TOOL_CONCURRENCY = 10


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
        self._runtime_context_date = ""
        self._web_tool_budget = WebToolBudget.from_env()
        self._max_tool_concurrency = _read_max_tool_concurrency()
        self._state_lock = threading.Lock()

    def run(self, question: str, session_context: str = "") -> str | None:
        """执行结构化 tool call 循环。"""

        run_started_at = time.perf_counter()
        self.messages = self._initial_messages(question, session_context)
        self._web_tool_budget = WebToolBudget.from_env()
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
            if self._refresh_runtime_context_if_date_changed():
                tools = self.tool_registry.to_openai_tools()
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
            response = self._request_llm_response(self.messages, tools)
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
            batches = _partition_tool_calls(response.tool_calls, self.tool_registry)
            for batch in batches:
                should_stop, failures = self._run_tool_call_batch(batch)
                consecutive_failures = 0 if not failures else consecutive_failures + failures
                if should_stop:
                    return None
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

    def _request_llm_response(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse | None:
        """请求模型；可用时流式收集，否则走普通 chat。"""

        if getattr(self.llm_client, "stream", False) and hasattr(self.llm_client, "stream_chat"):
            streamed = self._request_streaming_response(messages, tools)
            if streamed is not None:
                return streamed
            log_debug("stream response failed; falling back to non-stream chat", level="warn", component="agent")
        return self.llm_client.chat(messages, tools=tools)

    def _request_streaming_response(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse | None:
        """收集流式响应，同时把文本 delta 交给 renderer。"""

        stream_chat = getattr(self.llm_client, "stream_chat", None)
        if not callable(stream_chat):
            return None
        accumulator = _StreamResponseAccumulator()
        try:
            for event in stream_chat(messages, tools=tools):
                if event.type == "content_delta":
                    accumulator.add_content(event.text)
                    self.renderer.render(AssistantDelta(event.text))
                elif event.type == "tool_call_delta" and event.tool_call_delta is not None:
                    accumulator.add_tool_call_delta(event.tool_call_delta)
                elif event.type == "error":
                    log_debug(f"stream event error error={event.error}", level="warn", component="agent")
                    return None
                elif event.type == "message_done":
                    break
        except Exception as exc:
            log_debug(f"stream response exception error={exc}", level="warn", component="agent")
            return None
        return accumulator.to_response()

    def estimate_context_tokens(self, question: str, session_context: str = "") -> int:
        """估算一次新 turn 初始上下文 token 数。"""

        return check_context_budget(
            self._initial_messages(question, session_context),
            tools=self.tool_registry.to_openai_tools(),
            config=self.context_budget,
        ).estimated_tokens

    def _run_tool_call_batch(self, batch: dict[str, object]) -> tuple[bool, int]:
        """执行一个工具调用批次，返回 (should_stop, failure_count)。

        concurrency-safe 批次并发执行，非 safe 批次串行执行。
        """
        tool_calls: list[LLMToolCall] = batch["calls"]  # type: ignore[assignment]
        is_safe: bool = batch["safe"]  # type: ignore[assignment]

        if is_safe and len(tool_calls) > 1 and self._max_tool_concurrency > 1:
            return self._run_concurrently(tool_calls)

        failures = 0
        for llm_tool_call in tool_calls:
            result = self._run_tool_call(llm_tool_call)
            self.messages.append(result.to_openai_message())
            if _is_user_denied_tool_result(result):
                self.renderer.render(SystemNotice("用户已拒绝工具执行，本轮任务已停止。", "warning"))
                return True, failures
            if _counts_as_loop_failure(result):
                failures += 1
            else:
                failures = 0
        return False, failures

    def _run_concurrently(self, tool_calls: list[LLMToolCall]) -> tuple[bool, int]:
        """并发执行 concurrency-safe 工具调用。

        预算检查和渲染在锁内串行化，工具执行（call）阶段并发。
        """
        results: dict[str, StructuredToolResult] = {}
        failures = 0

        def _execute(tc: LLMToolCall) -> StructuredToolResult:
            return self._run_tool_call(tc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_tool_concurrency) as executor:
            futures = {executor.submit(_execute, tc): tc for tc in tool_calls}
            for future in concurrent.futures.as_completed(futures):
                tc = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = StructuredToolResult.failure(
                        tc.id,
                        tc.name,
                        f"Concurrent execution error: {exc}",
                        metadata={"reason": "concurrent_execution_error"},
                    )
                results[tc.id] = result

        # 按原始顺序追加结果
        for tc in tool_calls:
            result = results[tc.id]
            self.messages.append(result.to_openai_message())
            if _is_user_denied_tool_result(result):
                self.renderer.render(SystemNotice("用户已拒绝工具执行，本轮任务已停止。", "warning"))
                return True, failures
            if _counts_as_loop_failure(result):
                failures += 1
            else:
                failures = 0
        return False, failures

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

        # ── 预执行阶段（需锁保护共享状态） ──
        with self._state_lock:
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

            budget_result = self._web_tool_budget.reserve(llm_tool_call.name, llm_tool_call.arguments)
            parse_error = llm_tool_call.parse_error

        # ── 预算耗尽 / 参数错误：直接返回，无需解锁执行 ──
        if budget_result is not None:
            result = StructuredToolResult.success(
                llm_tool_call.id,
                llm_tool_call.name,
                budget_result.content,
                data=budget_result.data,
                metadata=budget_result.metadata,
            )
        elif parse_error:
            result = StructuredToolResult.failure(
                llm_tool_call.id,
                llm_tool_call.name,
                parse_error,
                metadata={"reason": "arguments_parse_error"},
            )
        else:
            context = ToolContext(
                project_root=self.project_root,
                session_id=self.session_id,
                permission_checker=self.permission_checker,
                metadata={"web_fetch_summarizer": LLMWebFetchSummarizer(self.llm_client)},
            )
            # ── 工具执行（无锁，可并发） ──
            result = self.runner.run(
                ToolCall(
                    id=llm_tool_call.id,
                    name=llm_tool_call.name,
                    args=llm_tool_call.arguments,
                    raw=llm_tool_call.raw,
                ),
                context,
            )

        # ── 后执行阶段（需锁保护共享状态） ──
        with self._state_lock:
            if self.transcript_sink:
                self.transcript_sink.record_tool_result(llm_tool_call.name, result.content, ok=result.ok)
            self.renderer.render(
                ToolResult(
                    llm_tool_call.name,
                    result.content,
                    id=llm_tool_call.id,
                    ok=result.ok,
                data=result.data,
                metadata=result.metadata,
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
        runtime_context = get_runtime_user_context()
        self._runtime_context_date = runtime_context.current_date
        user_context_message = build_user_context_message(runtime_context.as_sections())
        if user_context_message is not None:
            messages.append(user_context_message)
        messages.append({"role": "user", "content": question})
        return messages

    def _refresh_runtime_context_if_date_changed(self) -> bool:
        """长工具循环跨日期时追加新的 currentDate 提醒。"""

        runtime_context = get_runtime_user_context()
        current_date = runtime_context.current_date
        if not self._runtime_context_date or current_date == self._runtime_context_date:
            return False
        message = build_date_change_context_message(self._runtime_context_date, current_date)
        self._runtime_context_date = current_date
        if message is None:
            return False
        self.messages.append(message)
        log_debug(
            f"runtime context date changed current_date={current_date}",
            level="info",
            component="agent",
        )
        return True


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


class _StreamResponseAccumulator:
    """把 OpenAI-compatible streaming delta 还原为 LLMResponse。"""

    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.tool_calls: dict[int, dict[str, Any]] = {}

    def add_content(self, text: str) -> None:
        self.content_parts.append(text)

    def add_tool_call_delta(self, delta: dict[str, Any]) -> None:
        index = int(delta.get("index") or 0)
        current = self.tool_calls.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if delta.get("id"):
            current["id"] = str(delta["id"])
        if delta.get("type"):
            current["type"] = str(delta["type"])
        function_delta = delta.get("function")
        if isinstance(function_delta, dict):
            function = current.setdefault("function", {"name": "", "arguments": ""})
            if function_delta.get("name"):
                function["name"] = str(function_delta["name"])
            if function_delta.get("arguments"):
                function["arguments"] = str(function.get("arguments") or "") + str(function_delta["arguments"])

    def to_response(self) -> LLMResponse:
        tool_calls: list[LLMToolCall] = []
        for index in sorted(self.tool_calls):
            raw = self.tool_calls[index]
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            name = str(function.get("name") or raw.get("name") or "")
            if not name:
                continue
            arguments, parse_error = _parse_stream_arguments(function.get("arguments", ""))
            raw_id = str(raw.get("id") or f"call_{index}")
            tool_calls.append(
                LLMToolCall(
                    id=raw_id,
                    name=name,
                    arguments=arguments,
                    raw={
                        "id": raw_id,
                        "type": raw.get("type") or "function",
                        "function": {
                            "name": name,
                            "arguments": function.get("arguments") or "",
                        },
                    },
                    parse_error=parse_error,
                )
            )
        return LLMResponse(content="".join(self.content_parts), tool_calls=tool_calls)


def _parse_stream_arguments(value: object) -> tuple[dict[str, Any], str | None]:
    if isinstance(value, dict):
        return value, None
    if value in (None, ""):
        return {}, None
    if not isinstance(value, str):
        return {}, f"Tool arguments must be JSON object string, got {type(value).__name__}."
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        return {}, f"Tool arguments JSON parse failed: {exc}"
    if not isinstance(parsed, dict):
        return {}, f"Tool arguments must decode to JSON object, got {type(parsed).__name__}."
    return parsed, None


def _read_max_tool_concurrency() -> int:
    """从环境变量读取最大工具并发数。"""
    raw = os.getenv(_MAX_TOOL_CONCURRENCY_ENV)
    if raw is None:
        return _DEFAULT_MAX_TOOL_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_TOOL_CONCURRENCY
    return max(1, value)


def _partition_tool_calls(
    tool_calls: list[LLMToolCall],
    registry: ToolRegistry,
) -> list[dict[str, object]]:
    """按 Claude Code partitionToolCalls 思路分区。

    连续 concurrency-safe 工具合并为一个并发批次；
    非 safe 工具各自独立为串行批次。
    """
    batches: list[dict[str, object]] = []
    for tc in tool_calls:
        tool = registry.get(tc.name)
        is_safe = bool(getattr(tool, "is_concurrency_safe", False)) if tool else False
        if is_safe and batches and batches[-1]["safe"] is True:
            tc_list = batches[-1]["calls"]
            assert isinstance(tc_list, list)
            tc_list.append(tc)
        else:
            batches.append({"safe": is_safe, "calls": [tc]})
    return batches
