"""MCP result 归一化。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .connection import model_to_dict


@dataclass(frozen=True)
class McpNormalizedResult:
    """表示可回灌模型的 MCP tool result。"""

    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_mcp_tool_result(raw_result: Any, *, server_name: str, tool_name: str) -> McpNormalizedResult:
    """把 MCP tools/call 结果转为文本和元数据。"""

    result = model_to_dict(raw_result)
    if not result:
        return McpNormalizedResult(ok=True, content=_json_text(raw_result), data={"mcp_result": raw_result})

    ok = result.get("isError", result.get("is_error")) is not True
    content = _format_result_content(result, server_name=server_name)
    metadata: dict[str, Any] = {
        "source": "mcp",
        "server_name": server_name,
        "tool_name": tool_name,
    }
    meta = result.get("_meta")
    structured = result.get("structuredContent", result.get("structured_content"))
    if meta is not None or structured is not None:
        metadata["mcp_meta"] = {
            **({"_meta": meta} if meta is not None else {}),
            **({"structuredContent": structured} if structured is not None else {}),
        }
    return McpNormalizedResult(
        ok=ok,
        content=content or ("MCP tool returned an error." if not ok else "(empty MCP result)"),
        data={"mcp_result": _redact_blob_values(result)},
        metadata=metadata,
    )


def _format_result_content(result: dict[str, Any], *, server_name: str) -> str:
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            parts.append(_format_content_item(item, server_name=server_name))
    structured = result.get("structuredContent", result.get("structured_content"))
    if structured is not None:
        parts.append(_json_text({"structuredContent": structured}))
    if not parts and "result" in result:
        parts.append(_json_text(result["result"]))
    return "\n".join(part for part in parts if part)


def _format_content_item(item: Any, *, server_name: str) -> str:
    item_dict = model_to_dict(item)
    if not item_dict:
        return _json_text(item)
    content_type = item_dict.get("type")
    if content_type == "text":
        text = item_dict.get("text", "")
        return text if isinstance(text, str) else str(text)
    if content_type == "image":
        return "image content omitted from MCP result"
    if content_type == "audio":
        return "audio content omitted from MCP result"
    if content_type == "resource":
        resource = model_to_dict(item_dict.get("resource"))
        uri = resource.get("uri", "(unknown uri)")
        text = resource.get("text")
        if isinstance(text, str):
            return f"resource {server_name}:{uri}:\n{text}"
        if "blob" in resource:
            return f"resource {server_name}:{uri}: binary content omitted"
        return f"resource {server_name}:{uri}: {_json_text(_redact_blob_values(resource))}"
    if content_type == "resource_link":
        uri = item_dict.get("uri", "(unknown uri)")
        name = item_dict.get("name") or uri
        return f"resource link {name}: {uri}"
    return _json_text(_redact_blob_values(item_dict))


def _redact_blob_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[omitted]" if key in {"blob", "data"} else _redact_blob_values(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_blob_values(item) for item in value]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(_redact_blob_values(value), ensure_ascii=False, sort_keys=True)
