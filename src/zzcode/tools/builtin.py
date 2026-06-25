"""Builtin tools for the first code-agent demo."""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .registry import ToolRegistry
from .safety import reject_dangerous_command, resolve_project_path

if TYPE_CHECKING:
    from zzcode.mcp import McpManager


MAX_READ_BYTES = 100 * 1024
COMMAND_TIMEOUT_SECONDS = 30
WRITE_FILE_SEPARATOR = "|||"


class LegacyToolRegistrar(Protocol):
    """legacy 文本工具注册接口。"""

    def register_tool(self, name: str, description: str, func: object, display_name: str | None = None) -> None: ...


def register_builtin_structured_tools(registry: ToolRegistry) -> None:
    """注册第四阶段结构化内置工具。

    registry 是结构化工具注册表；当前包含本地文件工具、shell 工具、web 搜索和抓取工具。
    """

    from .local.filesystem import (
        AppendFileTool,
        EditFileTool,
        ListFilesTool,
        ReadFileTool,
        WriteFileTool,
    )
    from .local.search import GlobTool, GrepTool
    from .local.powershell import RunPowerShellTool
    from .local.shell import RunShellTool
    from .local.web_fetch import WebFetchTool
    from .local.web_search import WebSearchTool

    registry.register(ListFilesTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(AppendFileTool())
    registry.register(RunShellTool())
    registry.register(RunPowerShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())


def build_tool_registry(
    project_root: Path | None = None,
    mcp_manager: "McpManager | None" = None,
) -> ToolRegistry:
    """构建结构化工具注册表。

    project_root 当前仅保留给 MCP/resource 组装使用；mcp_manager 提供外部 MCP 工具来源。
    """

    registry = ToolRegistry()
    register_builtin_structured_tools(registry)
    if mcp_manager is not None:
        register_mcp_structured_tools(registry, mcp_manager)
        register_mcp_resource_tools(registry, mcp_manager)
    return registry


def build_builtin_tool_registry() -> ToolRegistry:
    """构建第四阶段结构化内置工具注册表。"""

    return build_tool_registry()


def register_mcp_structured_tools(registry: ToolRegistry, mcp_manager: "McpManager") -> None:
    """注册 MCP 来源的结构化工具，冲突时保留已有本地工具。"""

    from zzcode.mcp import build_mcp_tools

    for tool in build_mcp_tools(mcp_manager, mcp_manager.list_tools()):
        if tool.name in registry:
            warnings.warn(
                f"Skipping MCP tool '{tool.name}' because a local tool with the same name exists.",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        registry.register(tool)


def register_mcp_resource_tools(registry: ToolRegistry, mcp_manager: "McpManager") -> None:
    """在存在 MCP resource server 时注册显式 resource 工具。"""

    if not mcp_manager.has_resource_servers():
        return

    from zzcode.tools.mcp import ListMcpResourcesTool, ReadMcpResourceTool

    for tool in (ListMcpResourcesTool(mcp_manager), ReadMcpResourceTool(mcp_manager)):
        if tool.name not in registry:
            registry.register(tool)


def register_builtin_tools(executor: LegacyToolRegistrar, project_root: Path) -> None:
    """注册 legacy 文本 ReAct 工具。

    executor 是工具注册表；project_root 是工具允许操作的项目根目录；无返回值。
    """

    root = project_root.resolve()
    executor.register_tool(
        "list_files",
        "列出目录内容。输入格式: path，例如 list_files[.]。",
        lambda tool_input: list_files(root, tool_input),
        display_name="List",
    )
    executor.register_tool(
        "read_file",
        "读取项目内文本文件，最大 100KB。输入格式: path，例如 read_file[README.md]。",
        lambda tool_input: read_file(root, tool_input),
        display_name="Read",
    )
    executor.register_tool(
        "write_file",
        "写入项目内文本文件。输入格式: path|||content，例如 write_file[hello.txt|||hello]。",
        lambda tool_input: write_file(root, tool_input),
        display_name="Write",
    )
    executor.register_tool(
        "edit_file",
        "替换项目内文本文件中的一段内容。输入格式: path|||old_text|||new_text，例如 edit_file[README.md|||old|||new]。",
        lambda tool_input: edit_file(root, tool_input),
        display_name="Edit",
    )
    executor.register_tool(
        "append_file",
        "追加内容到项目内文本文件末尾。输入格式: path|||content，例如 append_file[notes.md|||new line]。",
        lambda tool_input: append_file(root, tool_input),
        display_name="Append",
    )
    executor.register_tool(
        "run_shell",
        "在项目根目录执行简单 shell 命令，带 30 秒超时和危险命令拦截。输入格式: command。",
        lambda tool_input: run_shell(root, tool_input),
        display_name="Shell",
    )


def list_files(project_root: Path, tool_input: str) -> str:
    """列出项目内目录内容。

    project_root 是项目根目录；tool_input 是模型传入的目录路径；返回目录项文本。
    """

    path = resolve_project_path(project_root, tool_input or ".")
    if not path.exists():
        return f"路径不存在: {path.relative_to(project_root)}"
    if not path.is_dir():
        return f"不是目录: {path.relative_to(project_root)}"

    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return "(empty)"

    lines: list[str] = []
    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines)


def read_file(project_root: Path, tool_input: str) -> str:
    """读取项目内 UTF-8 文本文件。

    project_root 是项目根目录；tool_input 是文件路径；返回文件内容或错误说明。
    """

    path = resolve_project_path(project_root, tool_input)
    if not path.exists():
        return f"文件不存在: {path.relative_to(project_root)}"
    if not path.is_file():
        return f"不是文件: {path.relative_to(project_root)}"

    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        return f"文件过大，拒绝读取: {size} bytes > {MAX_READ_BYTES} bytes"

    # 第一阶段只做文本工具；二进制文件后续再用更明确的文件类型工具处理。
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "文件不是 UTF-8 文本，当前 read_file 暂不支持。"


def write_file(project_root: Path, tool_input: str) -> str:
    """写入项目内文本文件。

    tool_input 使用 path|||content 文本协议；返回写入结果或错误说明。
    """

    if WRITE_FILE_SEPARATOR not in tool_input:
        return f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}content"

    # 文本版 ReAct 还没有 JSON 参数，因此先用固定分隔符承载 path 和 content。
    path_text, content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
    path = resolve_project_path(project_root, path_text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"写入失败: {exc}"
    return f"Wrote {path.relative_to(project_root)} ({len(content)} chars)"


def edit_file(project_root: Path, tool_input: str) -> str:
    """替换项目内文本文件的一段内容。"""

    parts = tool_input.split(WRITE_FILE_SEPARATOR, 2)
    if len(parts) != 3:
        return f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}old_text{WRITE_FILE_SEPARATOR}new_text"

    path_text, old_text, new_text = parts
    if not old_text:
        return "替换失败: old_text 不能为空。"

    path = resolve_project_path(project_root, path_text)
    if not path.exists():
        return f"文件不存在: {path.relative_to(project_root)}"
    if not path.is_file():
        return f"不是文件: {path.relative_to(project_root)}"

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "文件不是 UTF-8 文本，当前 edit_file 暂不支持。"

    count = content.count(old_text)
    if count == 0:
        return "替换失败: old_text 未在文件中找到。"
    if count > 1:
        return f"替换失败: old_text 出现 {count} 次，请提供更精确的上下文。"

    updated = content.replace(old_text, new_text, 1)
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"写入失败: {exc}"
    return f"Edited {path.relative_to(project_root)} ({len(old_text)} -> {len(new_text)} chars)"


def append_file(project_root: Path, tool_input: str) -> str:
    """追加内容到项目内文本文件末尾。"""

    if WRITE_FILE_SEPARATOR not in tool_input:
        return f"参数格式错误。请使用: path{WRITE_FILE_SEPARATOR}content"

    path_text, content = tool_input.split(WRITE_FILE_SEPARATOR, 1)
    path = resolve_project_path(project_root, path_text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if path.exists():
            if not path.is_file():
                return f"不是文件: {path.relative_to(project_root)}"
            existing = path.read_text(encoding="utf-8")
        separator = "\n" if existing and not existing.endswith("\n") and content else ""
        path.write_text(existing + separator + content, encoding="utf-8")
    except UnicodeDecodeError:
        return "文件不是 UTF-8 文本，当前 append_file 暂不支持。"
    except OSError as exc:
        return f"追加失败: {exc}"
    return f"Appended {path.relative_to(project_root)} ({len(content)} chars)"


def run_shell(project_root: Path, tool_input: str) -> str:
    """在项目根目录执行 shell 命令。

    project_root 是命令工作目录；tool_input 是命令文本；返回 stdout/stderr/exit_code。
    """

    command = tool_input.strip()
    reject_dangerous_command(command)

    # shell=True 是为了贴近用户在终端输入的命令；前面必须先做危险命令快速拒绝。
    completed = subprocess.run(
        command,
        cwd=project_root,
        shell=True,
        text=True,
        capture_output=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    parts = []
    if output:
        parts.append(output)
    if error:
        parts.append(f"stderr:\n{error}")
    parts.append(f"exit_code: {completed.returncode}")
    return "\n".join(parts)
