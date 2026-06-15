"""用户子 Agent runner。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zzcode.agent.react_text import TextReActAgent
from zzcode.llm.client import ThinkClient
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.executor import ToolExecutor
from zzcode.ui.messages import UiMessage

from .context import SubagentContext, create_subagent_context
from .definition import SubagentDefinition
from .transcript import SidechainTranscriptRecorder


PermissionChecker = Callable[[str, str, str | None], bool]


@dataclass(frozen=True)
class UserSubagentResult:
    """用户子 Agent 执行结果。"""

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


class UserSubagentRunner:
    """运行用户可调用的同步子 Agent。"""

    def __init__(
        self,
        *,
        llm_client: ThinkClient,
        parent_scope: SessionScope,
        base_tools: ToolExecutor,
        permission_checker: PermissionChecker | None = None,
        renderer: object | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.parent_scope = parent_scope
        self.base_tools = base_tools
        self.permission_checker = permission_checker
        self.renderer = renderer or SilentRenderer()

    def run(
        self,
        *,
        definition: SubagentDefinition,
        prompt: str,
        description: str | None = None,
        session_context: str = "",
        agent_id: str | None = None,
    ) -> UserSubagentResult:
        """启动一个同步用户子 Agent，并返回最终结果。"""

        context = create_subagent_context(
            self.parent_scope,
            definition.name,
            agent_id=agent_id,
            description=description,
            source=definition.source,
        )
        transcript = SidechainTranscriptRecorder(context)
        transcript.record_user(prompt)
        try:
            tool_executor = build_subagent_tool_executor(self.base_tools, definition)
            child_agent = TextReActAgent(
                llm_client=self.llm_client,
                tool_executor=tool_executor,
                max_steps=definition.max_steps or 5,
                renderer=self.renderer,
                permission_checker=self.permission_checker,
                transcript_sink=transcript,
            )
            result = child_agent.run(
                self._build_subagent_question(definition, prompt, description),
                session_context=session_context,
            )
            if result is None:
                error = "Subagent stopped without final answer."
                transcript.record_error(error)
                return _failed_result(context, error)
            transcript.record_assistant(result)
            return UserSubagentResult(
                ok=True,
                agent_id=context.agent_id,
                subagent_name=context.subagent_name,
                result=result,
                transcript_path=str(context.transcript_path),
            )
        except Exception as exc:
            error = f"Subagent failed: {exc}"
            transcript.record_error(error)
            return _failed_result(context, error)

    def _build_subagent_question(
        self,
        definition: SubagentDefinition,
        prompt: str,
        description: str | None,
    ) -> str:
        """构建传给子 Agent 的任务文本。"""

        parts = [
            definition.system_prompt.strip(),
            "",
            "Subagent task:",
        ]
        if description:
            parts.append(f"Description: {description}")
        parts.append(prompt.strip())
        return "\n".join(parts)


def build_subagent_tool_executor(base_tools: ToolExecutor, definition: SubagentDefinition) -> ToolExecutor:
    """按子 Agent 定义创建专属工具池。"""

    allowed = set(definition.tools) if definition.tools is not None else None
    disallowed = set(definition.disallowed_tools or ())
    executor = ToolExecutor()
    for tool in base_tools.iter_tools():
        if allowed is not None and tool.name not in allowed:
            continue
        if tool.name in disallowed:
            continue
        executor.register_tool(
            tool.name,
            tool.description,
            tool.func,
            display_name=tool.display_name,
        )
    return executor


def _failed_result(context: SubagentContext, error: str) -> UserSubagentResult:
    return UserSubagentResult(
        ok=False,
        agent_id=context.agent_id,
        subagent_name=context.subagent_name,
        result=None,
        transcript_path=str(context.transcript_path),
        error=error,
    )
