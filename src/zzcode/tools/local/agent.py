"""Structured Agent tool."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from zzcode.llm.client import ChatClient
from zzcode.memory.session_scope import SessionScope
from zzcode.subagents.loader import load_subagent_definitions
from zzcode.subagents.restricted_tool_registry import build_restricted_tool_registry
from zzcode.subagents.structured_runner import StructuredSubagentRunner
from zzcode.tools.base import BaseTool, JsonObject, PermissionChecker, ToolContext, ToolValidationResult
from zzcode.tools.registry import ToolRegistry
from zzcode.tools.results import ToolResult


DEFAULT_SUBAGENT_TYPE = "general-purpose"


class AgentTool(BaseTool):
    """启动结构化子 Agent 执行明确子任务。"""

    name = "agent"
    description = (
        "Start a focused subagent for an isolated code reading or analysis task. "
        "Use this when a task can be delegated without polluting the main context."
    )
    display_name = "Agent"
    is_read_only = False
    input_schema = {
        "type": "object",
        "properties": {
            "subagent_type": {
                "type": "string",
                "description": "Subagent type name. Defaults to general-purpose.",
            },
            "description": {
                "type": "string",
                "description": "Short human-readable task description.",
            },
            "prompt": {
                "type": "string",
                "description": "Full task prompt for the subagent.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        project_root: Path,
        llm_client: ChatClient,
        session_scope: SessionScope,
        base_registry: ToolRegistry,
        permission_checker: PermissionChecker | None = None,
        session_context_provider: Callable[[], str] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.llm_client = llm_client
        self.session_scope = session_scope
        self.base_registry = base_registry
        self.permission_checker = permission_checker
        self.session_context_provider = session_context_provider

    def validate_input(self, args: JsonObject) -> ToolValidationResult:
        """校验 agent 工具参数。"""

        result = super().validate_input(args)
        errors = list(result.errors)
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append("$.prompt: prompt cannot be empty")
        if errors:
            return ToolValidationResult.failure(*errors)
        return ToolValidationResult.success()

    def call(self, args: JsonObject, context: ToolContext, tool_call_id: str) -> ToolResult:
        """运行结构化子 Agent 并返回结果。"""

        definitions = load_subagent_definitions(self.project_root)
        active = {definition.name: definition for definition in definitions.active_agents}
        subagent_type = str(args.get("subagent_type") or DEFAULT_SUBAGENT_TYPE).strip() or DEFAULT_SUBAGENT_TYPE
        definition = active.get(subagent_type)
        if definition is None:
            available = ", ".join(active) if active else "(none)"
            return ToolResult.failure(
                tool_call_id,
                self.name,
                f"Subagent '{subagent_type}' was not found. Available subagents: {available}",
                metadata={"reason": "subagent_not_found", "subagent_type": subagent_type},
            )

        allow_tools = set(definition.tools) if definition.tools is not None else None
        disallowed_tools = set(definition.disallowed_tools or ())
        if allow_tools is None:
            disallowed_tools.add(self.name)
        child_registry = build_restricted_tool_registry(
            self.base_registry,
            project_root=self.project_root,
            allow_tools=allow_tools,
            disallowed_tools=disallowed_tools,
            allow_read_paths=None,
            allow_write_paths=None,
        )
        runner = StructuredSubagentRunner(
            llm_client=self.llm_client,
            parent_scope=self.session_scope,
            project_root=self.project_root,
        )
        result = runner.run_definition(
            definition=definition,
            prompt=str(args["prompt"]),
            description=str(args.get("description") or ""),
            session_context=self.session_context_provider() if self.session_context_provider else "",
            tool_registry=child_registry,
            permission_checker=self.permission_checker,
        )
        if not result.ok:
            return ToolResult.failure(
                tool_call_id,
                self.name,
                (
                    f"Agent {result.agent_id} failed.\n"
                    f"Error: {result.error}\n"
                    f"Transcript: {result.transcript_path}"
                ),
                metadata={"reason": "subagent_failed", "agent_id": result.agent_id},
            )
        return ToolResult.success(
            tool_call_id,
            self.name,
            (
                f"Agent {result.agent_id} completed.\n"
                f"Subagent: {result.subagent_name}\n"
                f"Result:\n{result.result}\n"
                f"Transcript: {result.transcript_path}"
            ),
            metadata={"agent_id": result.agent_id, "subagent_name": result.subagent_name},
        )
