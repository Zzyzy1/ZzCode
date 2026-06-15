"""系统子 Agent 受限工具池。"""

from __future__ import annotations

from pathlib import Path

from zzcode.tools.builtin import WRITE_FILE_SEPARATOR
from zzcode.tools.executor import RegisteredTool, ToolExecutor
from zzcode.tools.safety import resolve_project_path


READ_PATH_TOOLS = frozenset({"list_files", "read_file"})
WRITE_PATH_TOOLS = frozenset({"write_file", "edit_file", "append_file"})


class RestrictedToolExecutor(ToolExecutor):
    """按工具名和路径边界包装基础工具池。

    allow_tools 控制系统 Agent 能看到哪些工具；allow_read_paths 为 None 时
    表示读取仍只受基础工具的项目根围栏限制；allow_write_paths 为空时拒绝写入。
    """

    def __init__(
        self,
        base_tools: ToolExecutor,
        *,
        project_root: Path,
        allow_tools: set[str],
        allow_read_paths: list[Path] | None = None,
        allow_write_paths: list[Path] | None = None,
    ) -> None:
        super().__init__()
        self.project_root = project_root.resolve()
        self.allow_tools = set(allow_tools)
        self.allow_read_paths = _resolve_allowed_paths(self.project_root, allow_read_paths)
        self.allow_write_paths = _resolve_allowed_paths(self.project_root, allow_write_paths or [])
        for tool in base_tools.iter_tools():
            if tool.name not in self.allow_tools:
                continue
            self.register_tool(
                tool.name,
                tool.description,
                self._wrap_tool(tool),
                display_name=tool.display_name,
            )

    def _wrap_tool(self, tool: RegisteredTool):
        def run(tool_input: str) -> str:
            denied = self._validate_tool_input(tool.name, tool_input)
            if denied:
                return denied
            return tool.func(tool_input)

        return run

    def _validate_tool_input(self, tool_name: str, tool_input: str) -> str | None:
        """检查工具输入是否满足系统 Agent 的路径限制。"""

        if tool_name in READ_PATH_TOOLS:
            return self._validate_read_path(tool_name, tool_input)
        if tool_name in WRITE_PATH_TOOLS:
            return self._validate_write_path(tool_name, tool_input)
        return None

    def _validate_read_path(self, tool_name: str, tool_input: str) -> str | None:
        if self.allow_read_paths is None:
            return None
        try:
            path = resolve_project_path(self.project_root, _extract_read_path(tool_input))
        except ValueError as exc:
            return f"Error: restricted tool read path denied for {tool_name}: {exc}"
        if not _path_is_allowed(path, self.allow_read_paths):
            return f"Error: restricted tool read path denied for {tool_name}: {path}"
        return None

    def _validate_write_path(self, tool_name: str, tool_input: str) -> str | None:
        path_text = _extract_write_path(tool_name, tool_input)
        if path_text is None:
            return None
        try:
            path = resolve_project_path(self.project_root, path_text)
        except ValueError as exc:
            return f"Error: restricted tool write path denied for {tool_name}: {exc}"
        if not _path_is_allowed(path, self.allow_write_paths):
            return f"Error: restricted tool write path denied for {tool_name}: {path}"
        return None


def _resolve_allowed_paths(project_root: Path, paths: list[Path] | None) -> list[Path] | None:
    if paths is None:
        return None
    resolved: list[Path] = []
    for path in paths:
        candidate = path if path.is_absolute() else project_root / path
        resolved.append(candidate.resolve())
    return resolved


def _extract_read_path(tool_input: str) -> str:
    return tool_input or "."


def _extract_write_path(tool_name: str, tool_input: str) -> str | None:
    if tool_name == "edit_file":
        parts = tool_input.split(WRITE_FILE_SEPARATOR, 2)
        return parts[0] if len(parts) == 3 else None
    if WRITE_FILE_SEPARATOR not in tool_input:
        return None
    return tool_input.split(WRITE_FILE_SEPARATOR, 1)[0]


def _path_is_allowed(path: Path, allowed_paths: list[Path] | None) -> bool:
    if allowed_paths is None:
        return True
    for allowed in allowed_paths:
        if path == allowed:
            return True
        if _allowed_path_is_directory_root(allowed):
            try:
                path.relative_to(allowed)
            except ValueError:
                continue
            return True
    return False


def _allowed_path_is_directory_root(path: Path) -> bool:
    return path.exists() and path.is_dir()
