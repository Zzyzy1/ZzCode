"""系统 forked Agent runner。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zzcode.agent.react_text import TextReActAgent
from zzcode.llm.client import ThinkClient
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.executor import ToolExecutor

from .context import SubagentContext, create_subagent_context
from .transcript import SidechainTranscriptRecorder
from .user_runner import SilentRenderer


PermissionChecker = Callable[[str, str, str | None], bool]


@dataclass(frozen=True)
class ForkedAgentResult:
    """系统子 Agent 执行结果。"""

    ok: bool
    agent_id: str
    subagent_name: str
    result: str | None
    transcript_path: str
    error: str | None = None


class ForkedAgentRunner:
    """运行内部系统子 Agent。

    第一版对齐 Claude runForkedAgent 的主链：隔离上下文、专用工具池、
    独立 sidechain transcript，以及可复用的 ReAct 执行循环。
    """

    def __init__(
        self,
        *,
        llm_client: ThinkClient,
        parent_scope: SessionScope,
        tool_executor: ToolExecutor,
        permission_checker: PermissionChecker | None = None,
        renderer: object | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.parent_scope = parent_scope
        self.tool_executor = tool_executor
        self.permission_checker = permission_checker
        self.renderer = renderer or SilentRenderer()

    def run(
        self,
        *,
        name: str,
        prompt: str,
        description: str | None = None,
        session_context: str = "",
        max_steps: int = 5,
        agent_id: str | None = None,
    ) -> ForkedAgentResult:
        """启动一个系统子 Agent，并返回最终结果。"""

        context = create_subagent_context(
            self.parent_scope,
            name,
            agent_id=agent_id,
            description=description,
            source="system",
        )
        transcript = SidechainTranscriptRecorder(context)
        transcript.record_user(prompt)
        try:
            child_agent = TextReActAgent(
                llm_client=self.llm_client,
                tool_executor=self.tool_executor,
                max_steps=max_steps,
                renderer=self.renderer,
                permission_checker=self.permission_checker,
                transcript_sink=transcript,
            )
            result = child_agent.run(prompt, session_context=session_context)
            if result is None:
                error = "Forked agent stopped without final answer."
                transcript.record_error(error)
                return _failed_result(context, error)
            transcript.record_assistant(result)
            return ForkedAgentResult(
                ok=True,
                agent_id=context.agent_id,
                subagent_name=context.subagent_name,
                result=result,
                transcript_path=str(context.transcript_path),
            )
        except Exception as exc:
            error = f"Forked agent failed: {exc}"
            transcript.record_error(error)
            return _failed_result(context, error)


def _failed_result(context: SubagentContext, error: str) -> ForkedAgentResult:
    return ForkedAgentResult(
        ok=False,
        agent_id=context.agent_id,
        subagent_name=context.subagent_name,
        result=None,
        transcript_path=str(context.transcript_path),
        error=error,
    )
