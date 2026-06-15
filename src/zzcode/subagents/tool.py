"""用户子 Agent 工具入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from zzcode.llm.client import ThinkClient
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.builtin import WRITE_FILE_SEPARATOR
from zzcode.tools.executor import ToolExecutor

from .definition import SubagentDefinition
from .loader import load_subagent_definitions
from .user_runner import PermissionChecker, UserSubagentRunner


DEFAULT_SUBAGENT_TYPE = "general-purpose"


@dataclass(frozen=True)
class AgentToolInput:
    """agent 工具的字符串输入解析结果。"""

    subagent_type: str
    description: str
    prompt: str


def register_agent_tool(
    executor: ToolExecutor,
    *,
    project_root: Path,
    llm_client: ThinkClient,
    session_scope: SessionScope,
    permission_checker: PermissionChecker | None = None,
    session_context_provider: Callable[[], str] | None = None,
) -> None:
    """把同步用户子 Agent 注册为主 Agent 工具。"""

    def run_agent_tool(tool_input: str) -> str:
        parsed = parse_agent_tool_input(tool_input)
        if not parsed.prompt:
            return "Error: agent prompt cannot be empty."

        definitions = load_subagent_definitions(project_root)
        active = _agent_definitions_by_name(definitions.active_agents)
        definition = active.get(parsed.subagent_type)
        if definition is None:
            available = ", ".join(active) if active else "(none)"
            return f"Error: subagent '{parsed.subagent_type}' was not found. Available subagents: {available}"

        runner = UserSubagentRunner(
            llm_client=llm_client,
            parent_scope=session_scope,
            base_tools=executor,
            permission_checker=permission_checker,
        )
        context_text = session_context_provider() if session_context_provider else ""
        result = runner.run(
            definition=definition,
            prompt=parsed.prompt,
            description=parsed.description,
            session_context=context_text,
        )
        if not result.ok:
            return (
                f"Agent {result.agent_id} failed.\n"
                f"Error: {result.error}\n"
                f"Transcript: {result.transcript_path}"
            )
        return (
            f"Agent {result.agent_id} completed.\n"
            f"Subagent: {result.subagent_name}\n"
            f"Result:\n{result.result}\n"
            f"Transcript: {result.transcript_path}"
        )

    executor.register_tool(
        "agent",
        (
            "启动一个同步子 Agent 执行明确子任务。输入格式: "
            "subagent_type|||description|||prompt；也可只输入 prompt，默认使用 general-purpose。"
        ),
        run_agent_tool,
        display_name="Agent",
    )


def parse_agent_tool_input(tool_input: str) -> AgentToolInput:
    """解析 agent 工具输入，支持完整三段式和默认 general-purpose。"""

    parts = [part.strip() for part in tool_input.split(WRITE_FILE_SEPARATOR, 2)]
    if len(parts) == 3:
        subagent_type, description, prompt = parts
        return AgentToolInput(
            subagent_type=subagent_type or DEFAULT_SUBAGENT_TYPE,
            description=description,
            prompt=prompt,
        )
    return AgentToolInput(
        subagent_type=DEFAULT_SUBAGENT_TYPE,
        description="",
        prompt=tool_input.strip(),
    )


def _agent_definitions_by_name(agents: list[SubagentDefinition]) -> dict[str, SubagentDefinition]:
    return {agent.name: agent for agent in agents}
