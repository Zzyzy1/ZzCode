"""子 Agent 会话上下文路径。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from zzcode.memory.session_scope import SessionScope


@dataclass(frozen=True)
class SubagentContext:
    """一次子 Agent 执行对应的磁盘上下文。"""

    agent_id: str
    parent_session_id: str
    subagent_name: str
    agent_dir: Path
    transcript_path: Path
    metadata_path: Path


def create_subagent_context(
    parent_scope: SessionScope,
    subagent_name: str,
    *,
    agent_id: str | None = None,
    description: str | None = None,
    source: str = "user",
) -> SubagentContext:
    """创建子 Agent 目录、transcript 和 metadata。

    parent_scope 是当前主会话；subagent_name 是 agent 类型名；
    返回可传给 runner 和 transcript recorder 的上下文。
    """

    resolved_agent_id = agent_id or f"agent-{uuid4()}"
    agent_dir = parent_scope.session_dir / "subagents" / resolved_agent_id
    context = SubagentContext(
        agent_id=resolved_agent_id,
        parent_session_id=parent_scope.session_id,
        subagent_name=subagent_name,
        agent_dir=agent_dir,
        transcript_path=agent_dir / "transcript.jsonl",
        metadata_path=agent_dir / "metadata.json",
    )
    ensure_subagent_context(context, description=description, source=source)
    return context


def ensure_subagent_context(
    context: SubagentContext,
    *,
    description: str | None = None,
    source: str = "user",
) -> None:
    """确保子 Agent 上下文文件存在，并写入 metadata。"""

    context.agent_dir.mkdir(parents=True, exist_ok=True)
    context.transcript_path.touch(exist_ok=True)
    if not context.metadata_path.exists():
        metadata = {
            "agentId": context.agent_id,
            "parentSessionId": context.parent_session_id,
            "subagentName": context.subagent_name,
            "source": source,
            "description": description,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "transcriptPath": str(context.transcript_path),
        }
        context.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
