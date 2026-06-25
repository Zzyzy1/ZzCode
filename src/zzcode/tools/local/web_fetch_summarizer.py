"""WebFetch prompt 提取/压缩层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


DEFAULT_WEB_FETCH_RESULT_MAX_CHARS = 12_000


@dataclass(frozen=True)
class WebFetchSummary:
    """表示 WebFetch 按 prompt 提取后的结果。"""

    text: str
    source: str
    original_chars: int
    result_chars: int
    truncated: bool


class WebFetchSummarizer(Protocol):
    """WebFetch secondary model / lightweight summarizer 协议。"""

    def summarize(
        self,
        *,
        prompt: str,
        content: str,
        content_type: str,
        is_preapproved_domain: bool = False,
    ) -> WebFetchSummary:
        """按 prompt 从页面内容中提取短结果。"""


class ExtractiveWebFetchSummarizer:
    """无 secondary model 时的本地降级提取器。"""

    def __init__(self, max_chars: int = DEFAULT_WEB_FETCH_RESULT_MAX_CHARS) -> None:
        self.max_chars = max_chars

    def summarize(
        self,
        *,
        prompt: str,
        content: str,
        content_type: str,
        is_preapproved_domain: bool = False,
    ) -> WebFetchSummary:
        """返回长度受控的页面文本。"""

        result = content
        truncated = len(result) > self.max_chars
        if truncated:
            result = result[: self.max_chars] + "\n\n[WebFetch result truncated by local summarizer...]"
        return WebFetchSummary(
            text=result,
            source="extractive",
            original_chars=len(content),
            result_chars=len(result),
            truncated=truncated,
        )


class LLMWebFetchSummarizer:
    """使用现有 ChatClient 模拟 Claude WebFetch secondary model。"""

    def __init__(self, llm_client: Any, fallback: WebFetchSummarizer | None = None) -> None:
        self.llm_client = llm_client
        self.fallback = fallback or ExtractiveWebFetchSummarizer()

    def summarize(
        self,
        *,
        prompt: str,
        content: str,
        content_type: str,
        is_preapproved_domain: bool = False,
    ) -> WebFetchSummary:
        """调用模型按 prompt 提取页面内容；失败时降级本地提取。"""

        messages = [
            {
                "role": "user",
                "content": build_web_fetch_summary_prompt(
                    prompt=prompt,
                    content=content,
                    content_type=content_type,
                    is_preapproved_domain=is_preapproved_domain,
                ),
            }
        ]
        try:
            response = self.llm_client.chat(messages, tools=[], temperature=0)
        except Exception:
            response = None

        text = (getattr(response, "content", "") or "").strip() if response is not None else ""
        if not text:
            fallback = self.fallback.summarize(
                prompt=prompt,
                content=content,
                content_type=content_type,
                is_preapproved_domain=is_preapproved_domain,
            )
            return WebFetchSummary(
                text=fallback.text,
                source="extractive_fallback",
                original_chars=fallback.original_chars,
                result_chars=fallback.result_chars,
                truncated=fallback.truncated,
            )

        return WebFetchSummary(
            text=text,
            source="llm",
            original_chars=len(content),
            result_chars=len(text),
            truncated=False,
        )


def build_web_fetch_summary_prompt(
    *,
    prompt: str,
    content: str,
    content_type: str,
    is_preapproved_domain: bool = False,
) -> str:
    """构造 WebFetch secondary model prompt。"""

    if is_preapproved_domain:
        guidelines = (
            "Provide a concise response based on the content above. "
            "Include relevant details, code examples, and documentation excerpts as needed."
        )
    else:
        guidelines = "\n".join(
            [
                "Provide a concise response based only on the content above. In your response:",
                " - Enforce a strict 125-character maximum for quotes from any source document. Open Source Software is ok as long as we respect the license.",
                " - Use quotation marks for exact language from articles; any language outside of the quotation should never be word-for-word the same.",
                " - You are not a lawyer and never comment on the legality of your own prompts and responses.",
                " - Never produce or reproduce exact song lyrics.",
            ]
        )

    return "\n".join(
        [
            "Web page content:",
            "---",
            content,
            "---",
            "",
            prompt,
            "",
            guidelines,
            f"Content-Type: {content_type or 'unknown'}",
        ]
    )
