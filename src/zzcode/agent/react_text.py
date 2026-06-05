"""Text-format ReAct agent inspired by hello-agents chapter 4."""

from __future__ import annotations

import re

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
    """A small teaching-oriented ReAct loop using Thought/Action text."""

    def __init__(
        self,
        llm_client: ThinkClient,
        tool_executor: ToolExecutor,
        max_steps: int = 5,
        renderer: object | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.max_steps = max_steps
        self.renderer = renderer or _PlainRenderer()
        self.history: list[str] = []

    def run(self, question: str) -> str | None:
        self.history = []

        for step in range(1, self.max_steps + 1):
            self.renderer.render(StepStarted(step, self.max_steps))
            prompt = self._build_prompt(question)
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

            tool_name, tool_input = self.parse_action(action)
            if not tool_name or tool_input is None:
                observation = "Invalid Action format. Use ToolName[input]."
                self.history.append(f"Action: {action}")
                self.history.append(f"Observation: {observation}")
                self.renderer.render(SystemNotice(observation, "warning"))
                continue

            tool = self.tool_executor.get_registered_tool(tool_name)
            display_name = tool.display_name if tool else None
            self.renderer.render(ToolUse(tool_name, tool_input, display_name))
            observation = self.tool_executor.execute(tool_name, tool_input)
            self.renderer.render(ToolResult(tool_name, observation))
            self.history.append(f"Action: {action}")
            self.history.append(f"Observation: {observation}")

        self.renderer.render(SystemNotice("Stopped: max steps reached.", "warning"))
        return None

    def _build_prompt(self, question: str) -> str:
        return REACT_PROMPT_TEMPLATE.format(
            tools=self.tool_executor.get_available_tools(),
            question=question,
            history="\n".join(self.history) if self.history else "(empty)",
        )

    @staticmethod
    def parse_output(text: str) -> tuple[str | None, str | None]:
        thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(.*?)$", text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else None
        action = action_match.group(1).strip() if action_match else None
        return thought, action

    @staticmethod
    def parse_action(action_text: str) -> tuple[str | None, str | None]:
        match = re.match(r"(\w+)\[(.*)\]$", action_text, re.DOTALL)
        return (match.group(1), match.group(2)) if match else (None, None)

    @staticmethod
    def parse_action_input(action_text: str) -> str:
        match = re.match(r"\w+\[(.*)\]$", action_text, re.DOTALL)
        return match.group(1) if match else ""
