"""Safety helpers for local code tools."""

from __future__ import annotations

import shlex
from pathlib import Path


DANGEROUS_COMMAND_PATTERNS = (
    "sudo",
    "rm -rf /",
    "rm -rf /*",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    "dd of=",
    "chmod 777 /",
    "chown -R",
    "curl | sh",
    "curl|sh",
    "wget | sh",
    "wget|sh",
)


def resolve_project_path(project_root: Path, user_path: str) -> Path:
    """把模型给出的相对路径解析到项目内，并拒绝越界访问。"""

    clean_path = (user_path or ".").strip().strip('"').strip("'")
    candidate = Path(clean_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate

    # resolve 会规整 .. 和符号链接；随后用 relative_to 做项目根围栏判断。
    resolved = candidate.resolve()
    root = project_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越界，拒绝访问项目外路径: {clean_path}") from exc
    return resolved


def reject_dangerous_command(command: str) -> None:
    """在执行 shell 前做一层快速拒绝，避免明显危险命令进入 subprocess。"""

    normalized = " ".join(command.strip().lower().split())
    if not normalized:
        raise ValueError("命令不能为空。")

    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern in normalized:
            raise ValueError(f"命令命中危险规则，已拒绝执行: {pattern}")

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"命令解析失败: {exc}") from exc

    if parts and parts[0] in {"sudo", "su"}:
        raise ValueError(f"拒绝执行需要提升权限的命令: {parts[0]}")
