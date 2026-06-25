"""WebFetch 页面内容提取。"""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_MAX_EXTRACTED_TEXT_LENGTH = 100_000


@dataclass(frozen=True)
class ExtractedWebContent:
    """表示 HTTP body 转换后的页面文本。"""

    text: str
    content_type: str
    original_text_chars: int
    text_truncated: bool
    max_text_length: int


def extract_fetch_text(
    raw_bytes: bytes,
    content_type: str,
    *,
    max_text_length: int = DEFAULT_MAX_EXTRACTED_TEXT_LENGTH,
) -> ExtractedWebContent:
    """把 WebFetch HTTP body 转换为可进入后续提取层的文本。"""

    raw_text = _decode_response_body(raw_bytes)
    is_html = "text/html" in content_type.lower() or (
        len(raw_text) > 20 and looks_like_html(raw_text)
    )
    text = strip_html(raw_text) if is_html else raw_text

    original_len = len(text)
    text_truncated = original_len > max_text_length
    if text_truncated:
        text = text[:max_text_length] + "\n\n[Content truncated due to length...]"

    return ExtractedWebContent(
        text=text,
        content_type=content_type,
        original_text_chars=original_len,
        text_truncated=text_truncated,
        max_text_length=max_text_length,
    )


def looks_like_html(text: str) -> bool:
    """快速判断文本是否像 HTML。"""

    head = text[:200].lower().strip()
    return bool(
        re.search(r"<!doctype\s+html", head)
        or re.search(r"<html[\s>]", head)
        or re.search(r"<head[\s>]", head)
        or re.search(r"<body[\s>]", head)
    )


def strip_html(html: str) -> str:
    """用轻量规则把 HTML 转为纯文本。"""

    for tag in ("script", "style", "noscript", "iframe", "svg", "nav", "footer"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    for tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "section", "article", "header"):
        html = re.sub(rf"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)

    html = re.sub(r"<[^>]+>", "", html)

    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'")
    html = html.replace("&nbsp;", " ").replace("&#160;", " ")

    html = re.sub(r" +", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"^\s+", "", html)

    return html.strip()


def _decode_response_body(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return raw_bytes.decode("latin-1", errors="replace")
