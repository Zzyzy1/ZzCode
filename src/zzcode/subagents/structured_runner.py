"""结构化子 Agent runner。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zzcode.agent.tool_call_agent import ToolCallAgent
from zzcode.llm.client import ChatClient
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.base import PermissionChecker, ToolPermissionRequest, ToolPermissionResult
from zzcode.tools.registry import ToolRegistry
from zzcode.ui.messages import (
    AssistantDelta,
    FinalAnswer,
    SubagentDone,
    SubagentStarted,
    SubagentToolResult,
    SubagentToolUse,
    ToolResult,
    ToolUse,
    UiMessage,
)

from .context import create_subagent_context
from .definition import SubagentDefinition
from .transcript import SidechainTranscriptRecorder


@dataclass(frozen=True)
class StructuredSubagentResult:
    """结构化子 Agent 执行结果。"""

    ok: bool
    agent_id: str
    subagent_name: str
    result: str | None
    transcript_path: str
    error: str | None = None


class SilentRenderer:
    """丢弃子 Agent 内部 UI 事件，避免污染主会话显示。"""

    def render(self, message: UiMessage) -> None:
        """接收 UI 消息但不输出。"""

        return None


class SubagentEventRenderer:
    """把子 Agent 内部 UI 事件转成父会话子事件。"""

    def __init__(self, parent_renderer: object, *, agent_id: str) -> None:
        self.parent_renderer = parent_renderer
        self.agent_id = agent_id

    def render(self, message: UiMessage) -> None:
        """转发子 Agent 工具进度，最终回答留给 agent 工具结果。"""

        render = getattr(self.parent_renderer, "render", None)
        if not callable(render):
            return
        if isinstance(message, ToolUse):
            render(
                SubagentToolUse(
                    agent_id=self.agent_id,
                    name=message.name,
                    tool_input=message.tool_input,
                    display_name=message.display_name,
                    id=message.id,
                    source=message.source,
                    mcp_info=message.mcp_info,
                )
            )
        elif isinstance(message, ToolResult):
            render(
                SubagentToolResult(
                    agent_id=self.agent_id,
                    tool_name=message.tool_name,
                    output=message.output,
                    id=message.id,
                    ok=message.ok,
                    source=message.source,
                    mcp_info=message.mcp_info,
                )
            )
        elif isinstance(message, AssistantDelta):
            # 第一版只流式主 Agent 最终回答，避免子 Agent 大量中间文字刷屏。
            return
        elif isinstance(message, FinalAnswer):
            return


class StructuredSubagentRunner:
    """用 ToolCallAgent 运行用户或系统子 Agent。"""

    def __init__(
        self,
        *,
        llm_client: ChatClient,
        parent_scope: SessionScope,
        project_root: Path,
        renderer: object | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.parent_scope = parent_scope
        self.project_root = project_root.resolve()
        self.renderer = renderer or SilentRenderer()

    def run(
        self,
        *,
        name: str,
        prompt: str,
        tool_registry: ToolRegistry,
        system_prompt: str,
        description: str | None = None,
        session_context: str = "",
        max_turns: int = 5,
        agent_id: str | None = None,
        source: str = "system",
        permission_checker: PermissionChecker | None = None,
    ) -> StructuredSubagentResult:
        """启动一次结构化子 Agent，并返回最终结果。"""

        context = create_subagent_context(
            self.parent_scope,
            name,
            agent_id=agent_id,
            description=description,
            source=source,
        )
        transcript = SidechainTranscriptRecorder(context)
        transcript.record_user(prompt)
        self._render(
            SubagentStarted(
                agent_id=context.agent_id,
                name=name,
                description=description,
                transcript_path=str(context.transcript_path),
            )
        )
        try:
            agent = ToolCallAgent(
                llm_client=self.llm_client,
                tool_registry=tool_registry,
                project_root=self.project_root,
                max_turns=max_turns,
                renderer=SubagentEventRenderer(self.renderer, agent_id=context.agent_id),
                permission_checker=permission_checker,
                transcript_sink=transcript,
                system_prompt=system_prompt,
                session_id=context.agent_id,
            )
            result = agent.run(prompt, session_context=session_context)
            if result is None:
                error = "Subagent stopped without final answer."
                transcript.record_error(error)
                self._render(SubagentDone(context.agent_id, name, False, str(context.transcript_path), error))
                return _failed_result(context.agent_id, name, str(context.transcript_path), error)
            transcript.record_assistant(result)
            self._render(SubagentDone(context.agent_id, name, True, str(context.transcript_path)))
            return StructuredSubagentResult(
                ok=True,
                agent_id=context.agent_id,
                subagent_name=name,
                result=result,
                transcript_path=str(context.transcript_path),
            )
        except Exception as exc:
            error = f"Subagent failed: {exc}"
            transcript.record_error(error)
            self._render(SubagentDone(context.agent_id, name, False, str(context.transcript_path), error))
            return _failed_result(context.agent_id, name, str(context.transcript_path), error)

    def run_definition(
        self,
        *,
        definition: SubagentDefinition,
        prompt: str,
        tool_registry: ToolRegistry,
        description: str | None = None,
        session_context: str = "",
        agent_id: str | None = None,
        permission_checker: PermissionChecker | None = None,
    ) -> StructuredSubagentResult:
        """按用户 subagent 定义启动结构化子 Agent。"""

        return self.run(
            name=definition.name,
            prompt=_build_definition_prompt(definition, prompt, description),
            tool_registry=tool_registry,
            system_prompt=definition.system_prompt,
            description=description,
            session_context=session_context,
            max_turns=definition.max_steps or 5,
            agent_id=agent_id,
            source=definition.source,
            permission_checker=permission_checker,
        )

    def _render(self, message: UiMessage) -> None:
        render = getattr(self.renderer, "render", None)
        if callable(render):
            render(message)


def allow_system_tool(request: ToolPermissionRequest) -> ToolPermissionResult:
    """系统子 Agent 通过受限工具池后的工具调用默认允许。"""

    return ToolPermissionResult.allow(reason="system_agent_allowed")


def _build_definition_prompt(
    definition: SubagentDefinition,
    prompt: str,
    description: str | None,
) -> str:
    parts = ["Subagent task:"]
    if description:
        parts.append(f"Description: {description}")
    parts.append(prompt.strip())
    return "\n".join(parts)


def _failed_result(agent_id: str, name: str, transcript_path: str, error: str) -> StructuredSubagentResult:
    return StructuredSubagentResult(
        ok=False,
        agent_id=agent_id,
        subagent_name=name,
        result=None,
        transcript_path=transcript_path,
        error=error,
    )
