"""子 Agent markdown 定义加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .builtin import get_builtin_subagents
from .definition import SubagentDefinition


USER_AGENT_DIR = ".zzcode/agents"
PROJECT_AGENT_DIR = ".zzcode/agents"


@dataclass(frozen=True)
class SubagentLoadResult:
    """子 Agent 加载结果。

    active_agents 是按名称合并后的可用定义；failed_files 保存解析失败的文件和原因。
    """

    active_agents: list[SubagentDefinition]
    all_agents: list[SubagentDefinition]
    failed_files: tuple[tuple[Path, str], ...] = ()


def load_subagent_definitions(project_root: Path, home: Path | None = None) -> SubagentLoadResult:
    """加载内置、用户和项目子 Agent 定义。

    project_root 是当前项目根目录；home 可在测试中指定用户目录；
    返回合并后的 active agents 以及所有原始定义。
    """

    home_dir = home or Path.home()
    builtins = get_builtin_subagents()
    user_agents, user_failed = load_subagents_from_dir(home_dir / USER_AGENT_DIR, source="user")
    project_agents, project_failed = load_subagents_from_dir(project_root / PROJECT_AGENT_DIR, source="project")
    all_agents = [*builtins, *user_agents, *project_agents]
    return SubagentLoadResult(
        active_agents=_merge_active_agents(all_agents),
        all_agents=all_agents,
        failed_files=(*user_failed, *project_failed),
    )


def load_subagents_from_dir(directory: Path, source: str) -> tuple[list[SubagentDefinition], tuple[tuple[Path, str], ...]]:
    """从一个目录读取 markdown 子 Agent 定义。"""

    if not directory.exists():
        return [], ()
    if not directory.is_dir():
        return [], ((directory, "Agent definition path is not a directory."),)

    agents: list[SubagentDefinition] = []
    failed: list[tuple[Path, str]] = []
    for path in sorted(directory.glob("*.md"), key=lambda item: item.name.lower()):
        try:
            agent = parse_subagent_markdown(path, source)
        except ValueError as exc:
            failed.append((path, str(exc)))
            continue
        if agent is not None:
            agents.append(agent)
    return agents, tuple(failed)


def parse_subagent_markdown(path: Path, source: str) -> SubagentDefinition | None:
    """解析一个 markdown agent 文件，缺少 agent frontmatter 时返回 None。"""

    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _split_frontmatter(content)
    if frontmatter is None:
        return None

    name = _clean_scalar(frontmatter.get("name"))
    description = _clean_scalar(frontmatter.get("description"))
    if not name:
        raise ValueError("Missing required 'name' field.")
    if not description:
        raise ValueError("Missing required 'description' field.")

    system_prompt = body.strip()
    if not system_prompt:
        raise ValueError("Agent markdown body cannot be empty.")

    return SubagentDefinition(
        name=name,
        description=description.replace("\\n", "\n"),
        system_prompt=system_prompt,
        tools=_parse_list(frontmatter.get("tools")),
        disallowed_tools=_parse_list(frontmatter.get("disallowed_tools") or frontmatter.get("disallowedTools")),
        model=_clean_scalar(frontmatter.get("model")),
        permission_mode=_clean_scalar(frontmatter.get("permission_mode") or frontmatter.get("permissionMode")),
        max_steps=_parse_positive_int(frontmatter.get("max_steps") or frontmatter.get("maxSteps")),
        background=_parse_bool(frontmatter.get("background")),
        source=source,
    )


def _merge_active_agents(agents: list[SubagentDefinition]) -> list[SubagentDefinition]:
    """按加载顺序合并 agent，同名定义以后者为准。"""

    merged: dict[str, SubagentDefinition] = {}
    for agent in agents:
        merged[agent.name] = agent
    return list(merged.values())


def _split_frontmatter(content: str) -> tuple[dict[str, str] | None, str]:
    """拆分 markdown frontmatter 和正文。"""

    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized
    end = normalized.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Unclosed frontmatter block.")
    raw_frontmatter = normalized[4:end]
    body = normalized[end + len("\n---\n") :]
    return _parse_frontmatter_lines(raw_frontmatter), body


def _parse_frontmatter_lines(text: str) -> dict[str, str]:
    """解析简单 key: value frontmatter。"""

    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Invalid frontmatter line: {raw_line}")
        key, value = line.split(":", 1)
        cleaned_key = key.strip()
        if not cleaned_key:
            raise ValueError(f"Invalid frontmatter line: {raw_line}")
        result[cleaned_key] = value.strip()
    return result


def _clean_scalar(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'").strip()
    return cleaned or None


def _parse_list(value: str | None) -> tuple[str, ...] | None:
    cleaned = _clean_scalar(value)
    if cleaned is None:
        return None
    items = tuple(item.strip() for item in cleaned.split(",") if item.strip())
    return items or None


def _parse_bool(value: str | None) -> bool:
    cleaned = _clean_scalar(value)
    if cleaned is None:
        return False
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _parse_positive_int(value: str | None) -> int | None:
    cleaned = _clean_scalar(value)
    if cleaned is None:
        return None
    try:
        parsed = int(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid positive integer: {cleaned}") from exc
    if parsed <= 0:
        raise ValueError(f"Invalid positive integer: {cleaned}")
    return parsed
