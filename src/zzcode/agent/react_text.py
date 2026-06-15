"""Text-format ReAct agent inspired by hello-agents chapter 4."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from zzcode.llm.client import ThinkClient
from zzcode.tools.executor import ToolExecutor
from zzcode.ui.messages import (
    AssistantThought,
    FinalAnswer,
    StepStarted,
    SystemNotice,
    ToolResult,
    ToolUse,
)
from zzcode.ui.renderer import PlainInlineRenderer


class _PlainRenderer(PlainInlineRenderer):
    pass


class TranscriptSink(Protocol):
    """Agent 可选的 transcript 记录接口。"""

    def record_tool_use(self, tool_name: str, tool_input: str) -> None: ...

    def record_tool_result(self, tool_name: str, output: str, ok: bool = True) -> None: ...


REACT_PROMPT_TEMPLATE = """
你是一个可以调用外部工具的编程助手。

可用工具如下：
{tools}

Memory mechanics:
- 你有一个持久的文件型 Auto Memory 系统，目录是 `.zzcode/memory/`。
- `.zzcode/memory/MEMORY.md` 是记忆索引；详细记忆应写入 `.zzcode/memory/user/`、`.zzcode/memory/project/`、`.zzcode/memory/feedback/` 或 `.zzcode/memory/reference/` 下的独立 Markdown 文件。
- 你也有当前会话专用的 session memory，具体路径会在上下文的 `Current session memory` 中给出；它只服务当前 session，新 session 不会自动读取旧 session memory。
- 当用户在语义上明确表达希望你长期保留某个偏好、事实、反馈、项目约定或后续任务规则时，应通过普通文件工具更新 `.zzcode/memory/`，不要依赖固定关键词判断。
- 当前任务进度、临时调试状态和本轮上下文应写入当前 session memory，不要写入长期 Auto Memory。
- 保存记忆时先写入或更新对应的详细 Markdown 文件，再更新 `.zzcode/memory/MEMORY.md` 索引；索引项应指向详细文件。
- 更新已有记忆时优先使用 read_file 查看原内容，然后使用 edit_file 或 append_file 做增量修改，避免覆盖已有记忆。
- 不要为记忆创建 `memory.txt`，不要用 run_shell 写记忆，不要把临时执行步骤、命令输出或本轮推理过程写入长期记忆。

请严格按照以下格式回应：

Thought: 你的思考过程，用于分析问题、拆解任务和规划下一步行动。
Action: 你决定采取的行动，必须是以下格式之一：
- `{{tool_name}}[{{tool_input}}]`：调用一个可用工具。
- `Finish[最终答案]`：当你已经可以回答用户问题时。

规则：
1. 每次回复必须包含 Thought 和 Action。
2. Action 中的工具名必须来自可用工具列表。
3. 如果已有 Observation 足够回答问题，必须使用 Finish。
4. write_file 工具的输入必须使用 `path|||content` 格式，例如 `write_file[hello.txt|||hello zzcode]`。
5. edit_file 工具的输入必须使用 `path|||old_text|||new_text` 格式，append_file 工具的输入必须使用 `path|||content` 格式。
6. 文件相关任务优先使用 list_files、read_file、write_file、edit_file、append_file；命令执行任务使用 run_shell。

Question: {question}

History:
{history}
""".strip()


class TextReActAgent:
    """文本版 ReAct Agent。

    llm_client 负责生成 Thought/Action 文本；tool_executor 负责执行工具；
    run() 返回最终答案，模型未完成时返回 None。
    """

    def __init__(
        self,
        llm_client: ThinkClient,
        tool_executor: ToolExecutor,
        max_steps: int = 5,
        renderer: object | None = None,
        permission_checker: Callable[[str, str, str | None], bool] | None = None,
        transcript_sink: TranscriptSink | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.renderer = renderer or _PlainRenderer()
        self.permission_checker = permission_checker
        self.transcript_sink = transcript_sink
        self.history: list[str] = []

    def run(self, question: str, session_context: str = "") -> str | None:
        """执行一次 ReAct 循环。

        question 是用户原始问题；session_context 是跨轮会话摘要；
        函数会多轮调用模型和工具，成功时返回最终答案，否则返回 None。
        """

        self.history = []

        for step in range(1, self.max_steps + 1):
            self.renderer.render(StepStarted(step, self.max_steps))
            prompt = self._build_prompt(question, session_context)
            response_text = self.llm_client.think([{"role": "user", "content": prompt}])
            if not response_text:
                self.renderer.render(SystemNotice("LLM returned no response.", "error"))
                return None

            thought, action = self.parse_output(response_text)
            if thought:
                self.renderer.render(AssistantThought(thought))
            if not action:
                self.renderer.render(SystemNotice("No valid Action found; stopping.", "warning"))
                return None

            if action.startswith("Finish"):
                final_answer = self.parse_action_input(action)
                self.renderer.render(FinalAnswer(final_answer))
                return final_answer

            # 文本版 ReAct 依赖模型遵守 ToolName[input] 协议；
            # 这里解析失败时不抛异常，而是把错误作为 Observation 交还给模型。
            tool_name, tool_input = self.parse_action(action)
            if not tool_name or tool_input is None:
                observation = "Invalid Action format. Use ToolName[input]."
                self.history.append(f"Action: {action}")
                self.history.append(f"Observation: {observation}")
                self.renderer.render(SystemNotice(observation, "warning"))
                continue

            # 工具展示名来自工具注册表，Agent 只发 UiMessage，不关心终端如何渲染。
            tool = self.tool_executor.get_registered_tool(tool_name)
            display_name = tool.display_name if tool else None
            self.renderer.render(ToolUse(tool_name, tool_input, display_name))
            if self.transcript_sink:
                self.transcript_sink.record_tool_use(tool_name, tool_input)

            # 工具执行前留出权限确认钩子，UI 可以在这里阻塞并等待用户选择。
            if self.permission_checker and not self.permission_checker(tool_name, tool_input, display_name):
                observation = f"Tool execution denied by user: {tool_name}[{tool_input}]"
                if self.transcript_sink:
                    self.transcript_sink.record_tool_result(tool_name, observation, ok=False)
                self.renderer.render(ToolResult(tool_name, observation))
                self.history.append(f"Action: {action}")
                self.history.append(f"Observation: {observation}")
                continue

            observation = self.tool_executor.execute(tool_name, tool_input)
            if self.transcript_sink:
                self.transcript_sink.record_tool_result(tool_name, observation, ok=not observation.startswith("Error:"))
            self.renderer.render(ToolResult(tool_name, observation))
            self.history.append(f"Action: {action}")
            self.history.append(f"Observation: {observation}")

        self.renderer.render(SystemNotice("Stopped: max steps reached.", "warning"))
        return None

    def _build_prompt(self, question: str, session_context: str = "") -> str:
        """组装发给模型的 ReAct 提示词。

        question 是当前用户任务；session_context 是跨轮摘要；
        history 是本轮工具调用历史；返回完整 prompt 字符串。
        """

        history_parts = []
        if session_context:
            history_parts.append("Session context:")
            history_parts.append(session_context)
            history_parts.append("")
        history_parts.append("Current turn history:")
        history_parts.append("\n".join(self.history) if self.history else "(empty)")

        return REACT_PROMPT_TEMPLATE.format(
            tools=self.tool_executor.get_available_tools(),
            question=question,
            history="\n".join(history_parts),
        )

    @staticmethod
    def parse_output(text: str) -> tuple[str | None, str | None]:
        """从模型文本中拆出 Thought 和 Action。

        text 是模型原始输出；返回 (thought, action)，解析不到时对应值为 None。
        """

        # 用非贪婪匹配截取 Thought，避免把后面的 Action 一起吞掉。
        thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(.*?)$", text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else None
        action = action_match.group(1).strip() if action_match else None
        return thought, action

    @staticmethod
    def parse_action(action_text: str) -> tuple[str | None, str | None]:
        """解析 ToolName[input] 格式的 Action。

        action_text 是 Action 行内容；返回工具名和工具输入，格式错误时返回 (None, None)。
        """

        parsed = _parse_balanced_action(action_text)
        if parsed is None:
            return (None, None)
        return parsed

    @staticmethod
    def parse_action_input(action_text: str) -> str:
        """提取 Action 方括号中的内容。

        action_text 可是 Finish[...] 或 ToolName[...]；返回括号内文本。
        """

        parsed = _parse_balanced_action(action_text)
        return parsed[1] if parsed else ""


def _parse_balanced_action(action_text: str) -> tuple[str, str] | None:
    """严格解析单个 ToolName[input]，拒绝尾随文本污染工具参数。"""

    text = action_text.strip()
    match = re.match(r"^(\w+)\[", text)
    if not match:
        return None

    tool_name = match.group(1)
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                tool_input = text[start:index]
                trailing = text[index + 1 :].strip()
                if trailing:
                    return None
                return (tool_name, tool_input)
    return None
