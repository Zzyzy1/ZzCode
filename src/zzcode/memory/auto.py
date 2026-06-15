"""受控 Auto Memory 目录和索引基础能力。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


AUTO_MEMORY_DIRNAME = "memory"
AUTO_MEMORY_INDEX_NAME = "MEMORY.md"
AUTO_MEMORY_TYPES = ("user", "project", "feedback", "reference")
DEFAULT_AUTO_MEMORY_MAX_CHARS = 12000
MAX_AUTO_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30

DEFAULT_AUTO_MEMORY_INDEX = """# ZzCode Auto Memory

This file is an index of durable memories. Each entry points to a separate markdown file.

## User

## Project

## Feedback

## Reference
"""


@dataclass(frozen=True)
class AutoMemoryHeader:
    """Auto memory 文件的 manifest 摘要。"""

    filename: str
    path: Path
    mtime_ms: int
    description: str | None = None
    memory_type: str | None = None


def get_auto_memory_dir(project_root: Path) -> Path:
    """返回当前项目的受控 auto memory 目录。"""

    return project_root / ".zzcode" / AUTO_MEMORY_DIRNAME


def get_auto_memory_index_path(project_root: Path) -> Path:
    """返回 auto memory 索引文件路径。"""

    return get_auto_memory_dir(project_root) / AUTO_MEMORY_INDEX_NAME


def ensure_auto_memory(project_root: Path) -> Path:
    """确保 auto memory 目录、分类目录和索引存在。"""

    memory_dir = get_auto_memory_dir(project_root)
    memory_dir.mkdir(parents=True, exist_ok=True)
    for memory_type in AUTO_MEMORY_TYPES:
        (memory_dir / memory_type).mkdir(parents=True, exist_ok=True)

    index_path = get_auto_memory_index_path(project_root)
    if not index_path.exists():
        index_path.write_text(DEFAULT_AUTO_MEMORY_INDEX, encoding="utf-8")
    return memory_dir


def read_auto_memory_index(project_root: Path, max_chars: int = DEFAULT_AUTO_MEMORY_MAX_CHARS) -> str:
    """读取 auto memory 索引；不存在时创建默认索引。"""

    ensure_auto_memory(project_root)
    index_path = get_auto_memory_index_path(project_root)
    content = index_path.read_text(encoding="utf-8", errors="replace").strip()
    if max_chars >= 0 and len(content) > max_chars:
        return content[:max_chars] + "\n\n[auto memory index truncated]"
    return content


def read_auto_memory_file(project_root: Path, path_text: str) -> str:
    """读取受控 auto memory 目录内的单个 markdown 文件。"""

    memory_path = _resolve_auto_memory_path(project_root, Path(path_text))
    if not memory_path.exists():
        return f"记忆文件不存在: {_relative_to_memory_dir(project_root, memory_path)}"
    if not memory_path.is_file():
        return f"目标不是记忆文件: {_relative_to_memory_dir(project_root, memory_path)}"
    return memory_path.read_text(encoding="utf-8", errors="replace")


def scan_auto_memory_files(project_root: Path) -> list[AutoMemoryHeader]:
    """扫描 auto memory markdown 文件，返回按修改时间倒序排列的 manifest 条目。"""

    memory_dir = ensure_auto_memory(project_root).resolve()
    headers: list[AutoMemoryHeader] = []
    for path in memory_dir.rglob("*.md"):
        if path.name == AUTO_MEMORY_INDEX_NAME:
            continue
        if not path.is_file():
            continue
        try:
            relative_path = path.relative_to(memory_dir)
            content = _read_frontmatter_head(path)
            frontmatter = _parse_frontmatter(content)
            memory_type = _parse_memory_type(frontmatter.get("type"))
            description = _clean_frontmatter_value(frontmatter.get("description"))
            headers.append(
                AutoMemoryHeader(
                    filename=relative_path.as_posix(),
                    path=path,
                    mtime_ms=int(path.stat().st_mtime * 1000),
                    description=description,
                    memory_type=memory_type,
                )
            )
        except OSError:
            continue
    return sorted(headers, key=lambda item: item.mtime_ms, reverse=True)[:MAX_AUTO_MEMORY_FILES]


def format_auto_memory_manifest(headers: list[AutoMemoryHeader]) -> str:
    """把 auto memory manifest 格式化为一行一个文件的文本清单。"""

    lines = []
    for header in headers:
        tag = f"[{header.memory_type}] " if header.memory_type else ""
        timestamp = _format_mtime_iso(header.mtime_ms)
        if header.description:
            lines.append(f"- {tag}{header.filename} ({timestamp}): {header.description}")
        else:
            lines.append(f"- {tag}{header.filename} ({timestamp})")
    return "\n".join(lines)


def _resolve_auto_memory_path(project_root: Path, relative_path: Path) -> Path:
    """把相对路径限制在 .zzcode/memory 内。"""

    if relative_path.is_absolute():
        raise ValueError("memory 路径必须是 .zzcode/memory 内的相对路径。")
    if relative_path.suffix.lower() != ".md":
        raise ValueError("memory 文件必须是 markdown 文件。")

    memory_dir = get_auto_memory_dir(project_root).resolve()
    resolved = (memory_dir / relative_path).resolve()
    try:
        resolved.relative_to(memory_dir)
    except ValueError as exc:
        raise ValueError(f"memory 路径越界，拒绝访问: {relative_path}") from exc
    return resolved


def _relative_to_memory_dir(project_root: Path, path: Path) -> str:
    return str(path.relative_to(get_auto_memory_dir(project_root).resolve()))


def _read_frontmatter_head(path: Path) -> str:
    lines = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index >= FRONTMATTER_MAX_LINES:
                break
            lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def _parse_frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    frontmatter: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            frontmatter[key] = value.strip()
    return frontmatter


def _parse_memory_type(value: str | None) -> str | None:
    cleaned = _clean_frontmatter_value(value)
    if cleaned in AUTO_MEMORY_TYPES:
        return cleaned
    return None


def _clean_frontmatter_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


def _format_mtime_iso(mtime_ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(mtime_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
