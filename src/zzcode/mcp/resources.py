"""MCP resources 数据模型和格式化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .connection import model_to_dict


@dataclass(frozen=True)
class McpResource:
    """表示 MCP server 暴露的一个 resource。"""

    server: str
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""

    def to_dict(self) -> dict[str, str]:
        """转换为稳定的字典结构。"""

        return {
            "server": self.server,
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mime_type": self.mime_type,
        }


def normalize_mcp_resource(server_name: str, raw_resource: dict[str, Any]) -> McpResource:
    """把 resources/list 原始项转换为 McpResource。"""

    uri = raw_resource.get("uri")
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError(f"Invalid MCP resource from server '{server_name}': missing non-empty uri.")
    name = raw_resource.get("name", "")
    description = raw_resource.get("description", "")
    mime_type = raw_resource.get("mimeType", raw_resource.get("mime_type", ""))
    return McpResource(
        server=server_name,
        uri=uri.strip(),
        name=name if isinstance(name, str) else "",
        description=description if isinstance(description, str) else "",
        mime_type=mime_type if isinstance(mime_type, str) else "",
    )


def normalize_mcp_resources(
    resources_by_server: dict[str, list[dict[str, Any]]],
) -> list[McpResource]:
    """把按 server 分组的 resources/list 结果拍平为资源列表。"""

    resources: list[McpResource] = []
    for server_name in sorted(resources_by_server):
        for raw_resource in resources_by_server[server_name]:
            resources.append(normalize_mcp_resource(server_name, raw_resource))
    return resources


def format_mcp_resources(resources: list[McpResource]) -> str:
    """格式化资源列表，便于回灌模型。"""

    if not resources:
        return "(no MCP resources)"
    lines: list[str] = []
    for resource in resources:
        label = resource.name or resource.uri
        details = [f"- {resource.server}: {label}", f"  uri: {resource.uri}"]
        if resource.description:
            details.append(f"  description: {resource.description}")
        if resource.mime_type:
            details.append(f"  mime_type: {resource.mime_type}")
        lines.extend(details)
    return "\n".join(lines)


@dataclass(frozen=True)
class McpReadResourceResult:
    """表示 MCP resources/read 的文本化结果。"""

    content: str
    contents: tuple[dict[str, Any], ...]
    has_blob: bool = False


def format_mcp_read_resource_result(raw_result: Any) -> McpReadResourceResult:
    """把 resources/read 结果转成文本，拒绝把 blob 直接塞进上下文。"""

    raw_result = model_to_dict(raw_result)
    if not isinstance(raw_result, dict):
        return McpReadResourceResult(content=str(raw_result), contents=())

    raw_contents = raw_result.get("contents", [])
    if not isinstance(raw_contents, list):
        raise ValueError("Invalid MCP resources/read response: 'contents' must be a list.")

    lines: list[str] = []
    contents: list[dict[str, Any]] = []
    has_blob = False
    for item in raw_contents:
        item = model_to_dict(item)
        if not isinstance(item, dict):
            raise ValueError("Invalid MCP resources/read response: content items must be objects.")
        content_item = dict(item)
        contents.append(_redact_blob(content_item))
        uri = str(item.get("uri") or "(unknown uri)")
        mime_type = str(item.get("mimeType") or item.get("mime_type") or "")
        if "blob" in item:
            has_blob = True
            label = f"binary resource {uri}"
            if mime_type:
                label += f" ({mime_type})"
            lines.append(f"{label}: blob content omitted")
            continue
        text = item.get("text")
        if isinstance(text, str):
            header = f"resource {uri}"
            if mime_type:
                header += f" ({mime_type})"
            lines.append(f"{header}:\n{text}")
            continue
        lines.append(f"resource {uri}: {content_item}")

    return McpReadResourceResult(
        content="\n".join(lines) if lines else "(empty MCP resource)",
        contents=tuple(contents),
        has_blob=has_blob,
    )


def _redact_blob(item: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(item)
    if "blob" in redacted:
        redacted["blob"] = "[omitted]"
    return redacted
