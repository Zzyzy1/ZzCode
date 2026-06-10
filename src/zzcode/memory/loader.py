"""加载 Claude Code 风格的指令记忆文件。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .instruction import InstructionMemoryFile, get_instruction_memory_files


DEFAULT_MAX_MEMORY_FILE_CHARS = 40_000
MAX_INCLUDE_DEPTH = 5
INCLUDE_TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class LoadedInstructionMemory:
    """已读取的指令记忆内容。

    content 是 UTF-8 文本内容；truncated 表示内容是否因长度限制被截断。
    """

    memory_type: str
    path: Path
    priority: int
    scope: str
    description: str
    checked_in: bool
    content: str
    char_count: int
    truncated: bool = False
    parent: Path | None = None


def load_instruction_memories(
    project_root: Path,
    home: Path | None = None,
    max_file_chars: int = DEFAULT_MAX_MEMORY_FILE_CHARS,
) -> list[LoadedInstructionMemory]:
    """读取当前项目可用的指令记忆文件。

    project_root 是项目根目录；home 可用于测试覆盖用户目录；
    max_file_chars 限制单个文件读取长度，返回按优先级和路径排序的记忆列表。
    """

    loaded: list[LoadedInstructionMemory] = []
    candidates = get_instruction_memory_files(project_root, home=home)
    processed_paths: set[Path] = set()
    for candidate in candidates:
        allowed_root = _allowed_include_root(candidate, project_root, home)
        if candidate.is_pattern:
            loaded.extend(
                _load_rule_files(candidate, max_file_chars, allowed_root, processed_paths)
            )
            continue
        loaded.extend(
            _load_memory_file(candidate, max_file_chars, allowed_root, processed_paths)
        )
    return loaded


def _load_rule_files(
    candidate: InstructionMemoryFile,
    max_file_chars: int,
    allowed_root: Path,
    processed_paths: set[Path],
) -> list[LoadedInstructionMemory]:
    """展开并读取 .zzcode/rules/*.md 规则文件。"""

    rules_dir = candidate.path.parent
    if not rules_dir.is_dir():
        return []

    loaded: list[LoadedInstructionMemory] = []
    for path in sorted(rules_dir.glob("*.md")):
        if not path.is_file():
            continue
        memories = _read_loaded_memory_tree(
            path=path,
            memory_type=candidate.memory_type,
            priority=candidate.priority,
            scope=candidate.scope,
            description="Project rule memory file.",
            checked_in=candidate.checked_in,
            max_file_chars=max_file_chars,
            allowed_root=allowed_root,
            processed_paths=processed_paths,
        )
        loaded.extend(memories)
    return loaded


def _load_memory_file(
    candidate: InstructionMemoryFile,
    max_file_chars: int,
    allowed_root: Path,
    processed_paths: set[Path],
) -> list[LoadedInstructionMemory]:
    """读取一个普通指令记忆文件，不存在时返回 None。"""

    if not candidate.path.is_file():
        return []
    return _read_loaded_memory_tree(
        path=candidate.path,
        memory_type=candidate.memory_type,
        priority=candidate.priority,
        scope=candidate.scope,
        description=candidate.description,
        checked_in=candidate.checked_in,
        max_file_chars=max_file_chars,
        allowed_root=allowed_root,
        processed_paths=processed_paths,
    )


def _read_loaded_memory_tree(
    path: Path,
    memory_type: str,
    priority: int,
    scope: str,
    description: str,
    checked_in: bool,
    max_file_chars: int,
    allowed_root: Path,
    processed_paths: set[Path],
    depth: int = 0,
    parent: Path | None = None,
) -> list[LoadedInstructionMemory]:
    """递归读取记忆文件和它声明的 @./include 文件。"""

    resolved_path = path.expanduser().resolve()
    if depth >= MAX_INCLUDE_DEPTH or resolved_path in processed_paths:
        return []
    if not _is_path_inside(resolved_path, allowed_root):
        return []
    if resolved_path.suffix.lower() not in INCLUDE_TEXT_EXTENSIONS:
        return []
    if not resolved_path.is_file():
        return []

    processed_paths.add(resolved_path)
    memory = _read_loaded_memory(
        path=resolved_path,
        memory_type=memory_type,
        priority=priority,
        scope=scope,
        description=description,
        checked_in=checked_in,
        max_file_chars=max_file_chars,
        parent=parent,
    )
    loaded = [memory]
    for include_path in _extract_include_paths(memory.content, resolved_path):
        loaded.extend(
            _read_loaded_memory_tree(
                path=include_path,
                memory_type=memory_type,
                priority=priority,
                scope=scope,
                description=f"Included memory from {resolved_path.name}.",
                checked_in=checked_in,
                max_file_chars=max_file_chars,
                allowed_root=allowed_root,
                processed_paths=processed_paths,
                depth=depth + 1,
                parent=resolved_path,
            )
        )
    return loaded


def _read_loaded_memory(
    path: Path,
    memory_type: str,
    priority: int,
    scope: str,
    description: str,
    checked_in: bool,
    max_file_chars: int,
    parent: Path | None = None,
) -> LoadedInstructionMemory:
    """读取文件内容并应用单文件长度限制。"""

    content = path.read_text(encoding="utf-8", errors="replace")
    truncated = max_file_chars >= 0 and len(content) > max_file_chars
    if truncated:
        content = content[:max_file_chars]
    return LoadedInstructionMemory(
        memory_type=memory_type,
        path=path,
        priority=priority,
        scope=scope,
        description=description,
        checked_in=checked_in,
        content=content,
        char_count=len(content),
        truncated=truncated,
        parent=parent,
    )


def _extract_include_paths(content: str, base_path: Path) -> list[Path]:
    """从 markdown 文本节点提取 @./relative 引用，跳过代码块和行内代码。"""

    paths: list[Path] = []
    in_fence = False
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for token in _include_tokens_without_inline_code(line):
            if not token.startswith("@./"):
                continue
            raw_path = token[1:].split("#", 1)[0]
            if raw_path:
                paths.append((base_path.parent / raw_path).resolve())
    return paths


def _include_tokens_without_inline_code(line: str) -> list[str]:
    """返回一行中不位于行内代码片段的 @include token。"""

    tokens: list[str] = []
    current = []
    in_code = False
    for char in line:
        if char == "`":
            if current:
                tokens.extend(_include_tokens_from_text("".join(current)))
                current = []
            in_code = not in_code
            continue
        if not in_code:
            current.append(char)
    if current:
        tokens.extend(_include_tokens_from_text("".join(current)))
    return tokens


def _include_tokens_from_text(text: str) -> list[str]:
    """提取空白分隔的 @./path token。"""

    return [part for part in text.split() if part.startswith("@./")]


def _allowed_include_root(
    candidate: InstructionMemoryFile,
    project_root: Path,
    home: Path | None,
) -> Path:
    """返回 include 允许访问的根目录。"""

    if candidate.memory_type == "user":
        return ((home or Path.home()).expanduser().resolve() / ".zzcode").resolve()
    return project_root.expanduser().resolve()


def _is_path_inside(path: Path, root: Path) -> bool:
    """判断 path 是否位于 root 内。"""

    try:
        path.relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False
