"""内置子 Agent 定义。"""

from __future__ import annotations

from .definition import SubagentDefinition


GENERAL_PURPOSE_SUBAGENT = SubagentDefinition(
    name="general-purpose",
    description="通用子 Agent，适合搜索、阅读、分析和总结。",
    system_prompt=(
        "你是 ZzCode 的通用子 Agent。\n"
        "你的任务来自主 Agent，请专注完成委托任务。\n"
        "需要信息时优先使用可用工具读取和检查项目内容。\n"
        "最终输出应简洁、可直接交给主 Agent 使用。"
    ),
    tools=("list_files", "read_file", "write_file", "edit_file", "append_file", "run_shell"),
    max_steps=5,
    background=False,
    source="built-in",
)


def get_builtin_subagents() -> list[SubagentDefinition]:
    """返回 ZzCode 内置子 Agent 定义列表。"""

    return [GENERAL_PURPOSE_SUBAGENT]
