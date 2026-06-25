"""把运行时上下文包装为模型消息。"""

from __future__ import annotations

from collections.abc import Mapping


def build_user_context_message(context: Mapping[str, str]) -> dict[str, str] | None:
    """生成 Claude 风格的 meta user context 消息。"""

    if not context:
        return None
    sections = "\n".join(f"# {key}\n{value}" for key, value in context.items())
    content = (
        "<system-reminder>\n"
        "As you answer the user's questions, you can use the following context:\n"
        f"{sections}\n\n"
        "IMPORTANT: this context may or may not be relevant to your tasks. "
        "You should not respond to this context unless it is highly relevant to your task.\n"
        "</system-reminder>"
    )
    return {"role": "user", "content": content}


def build_date_change_context_message(previous_date: str, current_date: str) -> dict[str, str] | None:
    """生成长会话跨日期时的 meta user context 消息。"""

    if not previous_date or not current_date or previous_date == current_date:
        return None
    return build_user_context_message(
        {
            "currentDate": f"Today's date is {current_date}.",
            "dateChange": (
                "The local date changed during this session "
                f"from {previous_date} to {current_date}. "
                "For relative-date requests, use the updated currentDate."
            ),
        }
    )
