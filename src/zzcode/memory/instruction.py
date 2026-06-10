"""Claude Code 风格的指令记忆候选文件定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstructionMemoryFile:
    """一条指令记忆候选文件。

    memory_type 表示记忆类型；path 是候选路径；priority 表示加载顺序；
    exists 只标记文件或目录当前是否存在，不读取文件内容。
    """

    memory_type: str
    path: Path
    priority: int
    scope: str
    description: str
    checked_in: bool
    exists: bool
    is_pattern: bool = False


def get_instruction_memory_files(
    project_root: Path,
    home: Path | None = None,
) -> list[InstructionMemoryFile]:
    """返回 ZzCode 支持的指令记忆候选文件。

    project_root 是当前项目根目录；home 可用于测试覆盖用户目录；
    返回按低优先级到高优先级排序的候选文件列表。
    """

    root = project_root.expanduser().resolve()
    user_home = (home or Path.home()).expanduser().resolve()
    return [
        InstructionMemoryFile(
            memory_type="user",
            path=user_home / ".zzcode" / "ZZCODE.md",
            priority=10,
            scope="global",
            description="User memory shared across projects.",
            checked_in=False,
            exists=(user_home / ".zzcode" / "ZZCODE.md").is_file(),
        ),
        InstructionMemoryFile(
            memory_type="project",
            path=root / "ZZCODE.md",
            priority=20,
            scope="project",
            description="Project memory checked into the codebase.",
            checked_in=True,
            exists=(root / "ZZCODE.md").is_file(),
        ),
        InstructionMemoryFile(
            memory_type="project",
            path=root / ".zzcode" / "ZZCODE.md",
            priority=30,
            scope="project",
            description="Project memory stored under .zzcode.",
            checked_in=True,
            exists=(root / ".zzcode" / "ZZCODE.md").is_file(),
        ),
        InstructionMemoryFile(
            memory_type="rule",
            path=root / ".zzcode" / "rules" / "*.md",
            priority=40,
            scope="project",
            description="Project rule memory files under .zzcode/rules.",
            checked_in=True,
            exists=(root / ".zzcode" / "rules").is_dir(),
            is_pattern=True,
        ),
        InstructionMemoryFile(
            memory_type="local",
            path=root / "ZZCODE.local.md",
            priority=50,
            scope="local",
            description="Private local project memory.",
            checked_in=False,
            exists=(root / "ZZCODE.local.md").is_file(),
        ),
    ]
