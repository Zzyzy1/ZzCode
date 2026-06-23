"""OpenAI-compatible LLM client used by structured tool-call agents."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from zzcode.logging import log_debug, log_error


@dataclass(frozen=True)
class LLMToolCall:
    """模型返回的标准化工具调用。

    id 对应 provider 的 tool_call_id；arguments 是解析后的 JSON object。
    """

    id: str
    name: str
    arguments: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    """模型响应的标准化结果。"""

    content: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ChatClient(Protocol):
    """结构化 tool call Agent 依赖的模型协议。"""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0,
    ) -> LLMResponse | None:
        """请求模型生成 assistant message。"""


class ZzCodeLLM:
    """OpenAI-compatible LLM 客户端。

    从参数或环境变量读取模型配置；chat() 返回标准化 assistant message。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        stream: bool = False,
    ) -> None:
        load_env_file()

        self.model = model or os.getenv("LLM_MODEL_ID") or os.getenv("ZZCODE_MODEL")
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("ZZCODE_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("ZZCODE_BASE_URL")
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT") or os.getenv("ZZCODE_TIMEOUT") or 60)
        self.stream = stream

        if not all([self.model, self.api_key, self.base_url]):
            raise ValueError(
                "LLM_MODEL_ID/LLM_API_KEY/LLM_BASE_URL or "
                "ZZCODE_MODEL/ZZCODE_API_KEY/ZZCODE_BASE_URL must be configured."
            )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0,
    ) -> LLMResponse | None:
        """调用 Chat Completions 接口并标准化 tool_calls。

        messages 是模型上下文；tools 是 OpenAI-compatible tools schema；
        返回标准化 LLMResponse，HTTP 或网络失败时返回 None。
        """

        request_started_at = time.perf_counter()
        message_chars = sum(len(str(message.get("content") or "")) for message in messages)
        log_debug(
            "request start "
            f"model={self.model} "
            f"messages={len(messages)} "
            f"message_chars={message_chars} "
            f"tools={len(tools or [])} "
            f"timeout={self.timeout}",
            level="info",
            component="llm",
        )
        try:
            # 这里直接使用标准库 HTTP，避免第一阶段依赖 openai SDK。
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            if tools is not None:
                payload["tools"] = tools
            request = urllib.request.Request(
                url=self._chat_completions_url(),
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            http_started_at = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status_code = getattr(response, "status", "unknown")
                raw_body = response.read()
            http_elapsed_ms = (time.perf_counter() - http_started_at) * 1000
            log_debug(
                f"http response status={status_code} bytes={len(raw_body)} elapsed_ms={http_elapsed_ms:.1f}",
                level="info",
                component="llm",
            )
            normalize_started_at = time.perf_counter()
            body = json.loads(raw_body.decode("utf-8"))
            llm_response = normalize_chat_response(body)
            log_debug(
                _summarize_llm_response(llm_response)
                + f" normalize_ms={(time.perf_counter() - normalize_started_at) * 1000:.1f}"
                + f" total_ms={(time.perf_counter() - request_started_at) * 1000:.1f}",
                level="debug",
                component="llm",
            )
            return llm_response
        except urllib.error.HTTPError as exc:  # pragma: no cover - depends on remote provider
            error_body = exc.read().decode("utf-8", errors="replace")
            log_error(
                exc,
                component="llm",
                context={
                    "status_code": exc.code,
                    "response_body": error_body,
                    "elapsed_ms": f"{(time.perf_counter() - request_started_at) * 1000:.1f}",
                },
            )
            return None
        except Exception as exc:  # pragma: no cover - depends on remote provider
            log_error(
                exc,
                component="llm",
                context={
                    "phase": "chat",
                    "elapsed_ms": f"{(time.perf_counter() - request_started_at) * 1000:.1f}",
                },
            )
            return None

    def _chat_completions_url(self) -> str:
        """拼出 Chat Completions 请求地址。

        base_url 可以是服务根地址或完整 /chat/completions 地址；返回最终 URL。
        """

        base = str(self.base_url).rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def normalize_chat_response(body: dict[str, Any]) -> LLMResponse:
    """把 OpenAI-compatible 响应标准化为 LLMResponse。"""

    message = body["choices"][0].get("message") or {}
    content = message.get("content") or ""
    tool_calls = _normalize_tool_calls(message)
    return LLMResponse(content=content, tool_calls=tool_calls, raw=body)


def _normalize_tool_calls(message: dict[str, Any]) -> list[LLMToolCall]:
    calls = message.get("tool_calls") or []
    if not calls and message.get("function_call"):
        calls = [{"id": "call_0", "type": "function", "function": message["function_call"]}]

    normalized: list[LLMToolCall] = []
    for index, raw_call in enumerate(calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
        name = str(function.get("name") or raw_call.get("name") or "")
        if not name:
            continue
        arguments, parse_error = _parse_tool_arguments(function.get("arguments", {}))
        normalized.append(
            LLMToolCall(
                id=str(raw_call.get("id") or f"call_{index}"),
                name=name,
                arguments=arguments,
                raw=raw_call,
                parse_error=parse_error,
            )
        )
    return normalized


def _parse_tool_arguments(value: Any) -> tuple[dict[str, Any], str | None]:
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


def _summarize_llm_response(response: LLMResponse) -> str:
    """压缩 LLM 返回，避免日志被正文刷满。"""

    content = " ".join(response.content.split()).strip()
    if len(content) > 120:
        content = content[:117] + "..."
    if not content:
        content = "(empty)"
    return (
        f"response tool_calls={len(response.tool_calls)} "
        f"content_chars={len(response.content)} content={content}"
    )


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    """读取简单 .env 文件。

    path 是 env 文件路径；函数只写入尚未存在的环境变量，不返回值。
    """

    env_path = Path(path)
    if not env_path.exists():
        return

    # 只支持 KEY=VALUE 子集，够第一阶段使用，也避免引入 python-dotenv。
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
