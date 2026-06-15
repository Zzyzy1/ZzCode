"""子 Agent 定义模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentDefinition:
    """描述一个可被主 Agent 选择的子 Agent。

    name 是调用时使用的类型名；system_prompt 是子 Agent 的专属行为说明；
    tools/disallowed_tools 用于后续构建子 Agent 独立工具池。
    """

    name: str
    description: str
    system_prompt: str
    tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] | None = None
    model: str | None = None
    permission_mode: str | None = None
    max_steps: int | None = None
    background: bool = False
    source: str = "built-in"

    def __post_init__(self) -> None:
        """校验定义中的关键字段，避免后续 runner 处理非法 agent。"""

        if not self.name.strip():
            raise ValueError("Subagent name cannot be empty.")
        if not self.description.strip():
            raise ValueError("Subagent description cannot be empty.")
        if not self.system_prompt.strip():
            raise ValueError("Subagent system_prompt cannot be empty.")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("Subagent max_steps must be positive.")
