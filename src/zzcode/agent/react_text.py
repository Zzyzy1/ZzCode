"""Text-format ReAct agent inspired by hello-agents chapter 4."""

from __future__ import annotations

import re
from collections.abc import Callable

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


REACT_PROMPT_TEMPLATE = """
你是一个可以调用外部工具的编程助手。

可用工具如下：
{tools}

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
5. 文件相关任务优先使用 list_files、read_file、write_file；命令执行任务使用 run_shell。

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
    ) -> None:
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.renderer = renderer or _PlainRenderer()
        self.permission_checker = permission_checker
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

            # 工具执行前留出权限确认钩子，UI 可以在这里阻塞并等待用户选择。
            if self.permission_checker and not self.permission_checker(tool_name, tool_input, display_name):
                observation = f"Tool execution denied by user: {tool_name}[{tool_input}]"
                self.renderer.render(ToolResult(tool_name, observation))
                self.history.append(f"Action: {action}")
                self.history.append(f"Observation: {observation}")
                continue

            observation = self.tool_executor.execute(tool_name, tool_input)
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

        match = re.match(r"(\w+)\[(.*)\]$", action_text, re.DOTALL)
        return (match.group(1), match.group(2)) if match else (None, None)

    @staticmethod
    def parse_action_input(action_text: str) -> str:
        """提取 Action 方括号中的内容。

        action_text 可是 Finish[...] 或 ToolName[...]；返回括号内文本。
        """

        match = re.match(r"\w+\[(.*)\]$", action_text, re.DOTALL)
        return match.group(1) if match else ""
