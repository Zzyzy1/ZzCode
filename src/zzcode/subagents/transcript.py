"""子 Agent sidechain transcript 记录。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .context import SubagentContext


class SidechainTranscriptRecorder:
    """向子 Agent 独立 transcript 追加事件。"""

    def __init__(self, context: SubagentContext) -> None:
        self.context = context
        self._sequence = 0
        self._parent_event_id: str | None = None
        self._restore_state_from_existing_transcript()

    def record_user(self, text: str) -> dict[str, object]:
        """记录子 Agent 收到的任务。"""

        return self.record("user", text=text)

    def record_assistant(self, text: str) -> dict[str, object]:
        """记录子 Agent 最终回答或中间输出。"""

        return self.record("assistant", text=text)

    def record_tool_use(self, tool_name: str, tool_input: object) -> dict[str, object]:
        """记录子 Agent 的一次工具调用。"""

        return self.record("tool_use", toolName=tool_name, input=tool_input)

    def record_tool_result(self, tool_name: str, output: str, ok: bool = True) -> dict[str, object]:
        """记录子 Agent 的一次工具结果。"""

        return self.record("tool_result", toolName=tool_name, output=output, ok=ok)

    def record_error(self, message: str) -> dict[str, object]:
        """记录子 Agent 执行错误。"""

        return self.record("error", message=message)

    def record(self, event_type: str, **fields: object) -> dict[str, object]:
        """追加一条 sidechain transcript 事件。"""

        event_id = str(uuid4())
        event = {
            "type": event_type,
            "eventId": event_id,
            "parentEventId": self._parent_event_id,
            "sequence": self._sequence,
            "sessionId": self.context.parent_session_id,
            "agentId": self.context.agent_id,
            "parentSessionId": self.context.parent_session_id,
            "subagentName": self.context.subagent_name,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        with self.context.transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._sequence += 1
        self._parent_event_id = event_id
        return event

    def _restore_state_from_existing_transcript(self) -> None:
        """从已有 sidechain transcript 恢复序号和父事件游标。"""

        try:
            lines = self.context.transcript_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        self._sequence = len(lines)
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = event.get("eventId")
            if isinstance(event_id, str) and event_id:
                self._parent_event_id = event_id
                break
