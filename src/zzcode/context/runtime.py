"""构造 Agent 运行时 user context。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime


DATE_OVERRIDE_ENV = "ZZCODE_OVERRIDE_DATE"


@dataclass(frozen=True)
class RuntimeUserContext:
    """一次请求注入给模型的运行时上下文。"""

    current_date: str

    def as_sections(self) -> dict[str, str]:
        """返回 Claude 风格的 user context section。"""

        return {"currentDate": f"Today's date is {self.current_date}."}


def get_runtime_user_context() -> RuntimeUserContext:
    """读取当前本地日期并构造 user context。"""

    return RuntimeUserContext(current_date=get_local_iso_date())


def get_local_iso_date() -> str:
    """返回本地日期 YYYY-MM-DD，可用环境变量固定测试日期。"""

    override = os.getenv(DATE_OVERRIDE_ENV)
    if override:
        return override
    return datetime.now().astimezone().date().isoformat()


def get_local_month_year() -> str:
    """返回本地月份和年份，用于 WebSearch 工具提示。"""

    override = os.getenv(DATE_OVERRIDE_ENV)
    if override:
        try:
            date_value = datetime.strptime(override, "%Y-%m-%d")
        except ValueError:
            date_value = datetime.now().astimezone()
    else:
        date_value = datetime.now().astimezone()
    return date_value.strftime("%B %Y")
