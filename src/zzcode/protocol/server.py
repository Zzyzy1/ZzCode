"""JSON Lines backend used by the React + Ink frontend."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, TextIO

from zzcode.agent.react_text import TextReActAgent
from zzcode.cli.main import build_tools
from zzcode.llm.client import ZzCodeLLM
from zzcode.protocol.events import JsonLineEventWriter, JsonLineRenderer
from zzcode.tools.builtin import WRITE_FILE_SEPARATOR
from zzcode.tools.safety import resolve_project_path


MAX_DIFF_PREVIEW_LINES = 80


def main(argv: list[str] | None = None) -> int:
    """启动 JSONL 协议服务。

    argv 是命令行参数；返回进程退出码。
    """

    _configure_stdio()

    parser = argparse.ArgumentParser(description="Run ZzCode Agent over JSON Lines.")
    parser.add_argument("--once", action="store_true", help="process stdin until EOF and exit")
    args = parser.parse_args(argv)

    writer = JsonLineEventWriter()
    try:
        llm = ZzCodeLLM(stream=False)
    except Exception as exc:
        writer.write({"type": "system_notice", "level": "error", "text": f"LLM 初始化失败: {exc}"})
        return 1

    project_root = Path(os.getenv("ZZCODE_PROJECT_ROOT") or Path.cwd()).resolve()
    tools = build_tools(project_root)
    permission_bridge = PermissionBridge(sys.stdin, writer)
    renderer = JsonLineRenderer(writer)
    agent = TextReActAgent(
        llm_client=llm,
        tool_executor=tools,
        max_steps=5,
        renderer=renderer,
        permission_checker=permission_bridge.request_permission,
    )
    session_history: list[str] = []

    for request in _read_requests(sys.stdin):
        request_type = request.get("type")
        if request_type == "clear_history":
            session_history.clear()
            agent.history = []
            writer.write({"type": "system_notice", "level": "info", "text": "会话历史已清空。"})
            writer.write({"type": "request_done", "ok": True})
            continue
        if request_type == "shutdown":
            writer.write({"type": "system_notice", "level": "info", "text": "Python 后端已关闭。"})
            writer.write({"type": "request_done", "ok": True})
            break

        text = _extract_user_text(request)
        if not text:
            writer.write({"type": "system_notice", "level": "warning", "text": "收到空任务，已忽略。"})
            writer.write({"type": "request_done", "ok": False})
            continue

        # 前端通过 user_message 发起请求；后端回显同一事件，让消息流完全来自协议。
        writer.write({"type": "user_message", "text": text})
        answer = agent.run(text, session_context=_format_session_history(session_history))
        if answer:
            session_history.append(f"User: {text}")
            session_history.append(f"Assistant: {answer}")
            del session_history[:-12]
        writer.write({"type": "request_done", "ok": answer is not None})

        if args.once:
            break

    return 0


def _read_requests(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    """读取 stdin 中的 JSON Lines 请求。

    lines 是输入行迭代器；返回解析后的请求字典，非法 JSON 会转为错误事件。
    """

    writer = JsonLineEventWriter()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            writer.write({"type": "system_notice", "level": "error", "text": f"请求 JSON 解析失败: {exc}"})
            continue
        if isinstance(value, dict):
            yield value
        else:
            writer.write({"type": "system_notice", "level": "warning", "text": "请求必须是 JSON object。"})


def _extract_user_text(request: dict[str, Any]) -> str:
    """从请求事件中提取用户文本。

    request 是前端发来的 JSON 对象；返回用户输入文本，不匹配时返回空字符串。
    """

    if request.get("type") != "user_message":
        return ""
    text = request.get("text")
    return text.strip() if isinstance(text, str) else ""


def _format_session_history(session_history: list[str]) -> str:
    """格式化跨轮会话历史。

    session_history 是短会话摘要列表；返回适合放进 prompt 的文本。
    """

    return "\n".join(session_history[-12:])


class PermissionBridge:
    """在工具执行前向前端请求权限。

    input_stream 是 JSONL 请求输入；writer 用于输出 permission_request；返回用户是否允许。
    """

    def __init__(self, input_stream: TextIO, writer: JsonLineEventWriter) -> None:
        self.input_stream = input_stream
        self.writer = writer
        self._index = 0
        self._session_allowed_tools: set[str] = set()

    def request_permission(self, tool_name: str, tool_input: str, display_name: str | None = None) -> bool:
        """请求一次工具执行权限。

        tool_name/tool_input 描述即将执行的工具；display_name 是 UI 展示名；返回是否允许执行。
        """

        if tool_name in self._session_allowed_tools:
            return True

        self._index += 1
        request_id = f"permission-{self._index}"
        self.writer.write(
            {
                "type": "permission_request",
                "id": request_id,
                "toolName": tool_name,
                "displayName": display_name,
                "input": tool_input,
                "risk": _classify_tool_risk(tool_name),
                "preview": _build_permission_preview(tool_name, tool_input),
            }
        )

        # Agent 正在等待用户选择，此时 stdin 的下一条有效消息应该是 permission_response。
        for response in _read_requests(self.input_stream):
            if response.get("type") != "permission_response":
                self.writer.write({"type": "system_notice", "level": "warning", "text": "等待权限确认时忽略了非权限响应。"})
                continue
            if response.get("id") != request_id:
                self.writer.write({"type": "system_notice", "level": "warning", "text": "权限响应 id 不匹配，已忽略。"})
                continue

            decision = response.get("decision")
            if decision == "allow_session":
                self._session_allowed_tools.add(tool_name)
                return True
            return decision == "allow_once"

        return False


def _classify_tool_risk(tool_name: str) -> str:
    """按工具名粗略分类风险。

    tool_name 是待执行工具；返回 low/medium/high，用于前端选择展示颜色。
    """

    if tool_name == "run_shell":
        return "high"
    if tool_name == "write_file":
        return "medium"
    return "low"


def _build_permission_preview(tool_name: str, tool_input: str) -> dict[str, Any] | None:
    """为权限确认生成轻量预览。

    tool_name/tool_input 描述待执行工具；返回前端可渲染的预览对象，普通工具返回 None。
    """

    if tool_name != "write_file":
        return None
    return _build_write_file_diff_preview(tool_input)


def _build_write_file_diff_preview(tool_input: str) -> dict[str, Any]:
    """生成 write_file 的写入前 diff。

    tool_input 使用 path|||content 文本协议；返回有限行数的 unified diff 预览。
    """

    if WRITE_FILE_SEPARATOR not in tool_input:
        return {
            "type": "write_file_diff",
            "path": "",
            "fileExists": False,
            "error": f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}content",
        }

    path_text, new_content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
    project_root = Path(os.getenv("ZZCODE_PROJECT_ROOT") or Path.cwd()).resolve()

    try:
        path = resolve_project_path(project_root, path_text)
        relative_path = str(path.relative_to(project_root))
    except Exception as exc:
        return {
            "type": "write_file_diff",
            "path": path_text.strip(),
            "fileExists": False,
            "error": str(exc),
        }

    old_content = ""
    file_exists = path.exists()
    if file_exists:
        if not path.is_file():
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": "目标路径不是文件。",
            }
        try:
            old_content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": "目标文件不是 UTF-8 文本，无法生成 diff。",
            }
        except OSError as exc:
            return {
                "type": "write_file_diff",
                "path": relative_path,
                "fileExists": True,
                "error": f"读取旧文件失败: {exc}",
            }

    diff_lines = _unified_diff_lines(relative_path, old_content, new_content, file_exists)
    truncated = len(diff_lines) > MAX_DIFF_PREVIEW_LINES
    return {
        "type": "write_file_diff",
        "path": relative_path,
        "fileExists": file_exists,
        "oldLineCount": len(old_content.splitlines()),
        "newLineCount": len(new_content.splitlines()),
        "lines": diff_lines[:MAX_DIFF_PREVIEW_LINES],
        "truncated": truncated,
    }


def _unified_diff_lines(path: str, old_content: str, new_content: str, file_exists: bool) -> list[dict[str, str]]:
    """把新旧文本转换成前端展示用 diff 行。

    path 是相对路径；old_content/new_content 是写入前后文本；返回带类型的行列表。
    """

    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    if old_content == new_content:
        return [{"kind": "context", "text": "(no changes)"}]

    fromfile = f"a/{path}" if file_exists else "/dev/null"
    tofile = f"b/{path}"
    raw_lines = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, lineterm="")

    diff_lines: list[dict[str, str]] = []
    for line in raw_lines:
        if line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
            kind = "header"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        else:
            kind = "context"
        diff_lines.append({"kind": kind, "text": line})
    return diff_lines


def _configure_stdio() -> None:
    """固定标准输入输出编码。

    无入参；不返回值。Windows 默认编码可能不是 UTF-8，JSONL 协议必须显式统一编码。
    """

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
