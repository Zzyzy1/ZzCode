"""内置子 Agent 定义。"""

from __future__ import annotations

from .definition import SubagentDefinition


GENERAL_PURPOSE_SUBAGENT = SubagentDefinition(
    name="general-purpose",
    description="通用子 Agent，适合搜索、阅读、分析和总结。",
    system_prompt=(
        "你是 ZzCode 的通用子 Agent。\n"
        "你的任务来自主 Agent，请专注完成委托任务。\n"
        "需要信息时优先使用 glob/grep/list_files 缩小范围，再按需 read_file。\n"
        "不要一次性读取大量文件；只读取能支持结论的关键文件。\n"
        "最终输出应简洁、可直接交给主 Agent 使用。"
    ),
    tools=("list_files", "glob", "grep", "read_file", "write_file", "edit_file", "append_file", "run_shell"),
    max_steps=5,
    background=False,
    source="built-in",
)


def get_builtin_subagents() -> list[SubagentDefinition]:
    """返回 ZzCode 内置子 Agent 定义列表。"""

    return [GENERAL_PURPOSE_SUBAGENT]
