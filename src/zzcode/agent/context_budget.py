"""Agent 上下文预算估算。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_RESERVED_OUTPUT_TOKENS = 8_000
DEFAULT_AUTO_COMPACT_BUFFER_TOKENS = 12_000
DEFAULT_BLOCKING_BUFFER_TOKENS = 3_000
DEFAULT_MAX_TURNS = 20


@dataclass(frozen=True)
class ContextBudgetConfig:
    """描述一次 Agent 请求可用的上下文预算。"""

    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS
    auto_compact_buffer_tokens: int = DEFAULT_AUTO_COMPACT_BUFFER_TOKENS
    blocking_buffer_tokens: int = DEFAULT_BLOCKING_BUFFER_TOKENS

    @classmethod
    def from_env(cls) -> "ContextBudgetConfig":
        """从环境变量读取上下文预算配置。"""

        return cls(
            context_window_tokens=_env_int("ZZCODE_CONTEXT_WINDOW_TOKENS", DEFAULT_CONTEXT_WINDOW_TOKENS),
            reserved_output_tokens=_env_int("ZZCODE_RESERVED_OUTPUT_TOKENS", DEFAULT_RESERVED_OUTPUT_TOKENS),
            auto_compact_buffer_tokens=_env_int(
                "ZZCODE_AUTO_COMPACT_BUFFER_TOKENS",
                DEFAULT_AUTO_COMPACT_BUFFER_TOKENS,
            ),
            blocking_buffer_tokens=_env_int("ZZCODE_BLOCKING_BUFFER_TOKENS", DEFAULT_BLOCKING_BUFFER_TOKENS),
        )

    @property
    def effective_context_window(self) -> int:
        """返回扣除输出预留后的可用上下文窗口。"""

        return max(1, self.context_window_tokens - self.reserved_output_tokens)

    @property
    def auto_compact_threshold(self) -> int:
        """返回建议自动压缩的 token 阈值。"""

        return max(1, self.effective_context_window - self.auto_compact_buffer_tokens)

    @property
    def blocking_threshold(self) -> int:
        """返回阻止继续请求模型的 token 阈值。"""

        return max(1, self.effective_context_window - self.blocking_buffer_tokens)


@dataclass(frozen=True)
class ContextBudgetState:
    """一次上下文预算检查的结果。"""

    estimated_tokens: int
    percent_left: int
    is_above_auto_compact_threshold: bool
    is_at_blocking_limit: bool
    config: ContextBudgetConfig


def max_turns_from_env(default: int = DEFAULT_MAX_TURNS) -> int:
    """读取主 Agent 最大 turn 数。"""

    return _env_int("ZZCODE_MAX_TURNS", default)


def rough_token_count(text: str) -> int:
    """用字符数粗略估算 token 数。"""

    return max(1, len(text) // 4) if text else 0


def estimate_messages_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    """估算 OpenAI-compatible messages 和 tools schema 的 token 数。"""

    text_parts: list[str] = []
    for message in messages:
        text_parts.append(json.dumps(message, ensure_ascii=False, sort_keys=True))
    if tools:
        text_parts.append(json.dumps(tools, ensure_ascii=False, sort_keys=True))
    return rough_token_count("\n".join(text_parts))


def calculate_context_budget_state(
    estimated_tokens: int,
    config: ContextBudgetConfig | None = None,
) -> ContextBudgetState:
    """根据估算 token 数计算上下文预算状态。"""

    budget = config or ContextBudgetConfig.from_env()
    threshold = budget.auto_compact_threshold
    percent_left = max(0, round(((threshold - estimated_tokens) / threshold) * 100))
    return ContextBudgetState(
        estimated_tokens=estimated_tokens,
        percent_left=percent_left,
        is_above_auto_compact_threshold=estimated_tokens >= budget.auto_compact_threshold,
        is_at_blocking_limit=estimated_tokens >= budget.blocking_threshold,
        config=budget,
    )


def check_context_budget(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    config: ContextBudgetConfig | None = None,
) -> ContextBudgetState:
    """估算 messages/tools 并返回预算状态。"""

    return calculate_context_budget_state(
        estimate_messages_tokens(messages, tools=tools),
        config=config,
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
