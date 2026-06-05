"""Interactive CLI for the first text ReAct demo."""

from __future__ import annotations

import ast
import operator
from pathlib import Path

from zzcode.agent.react_text import TextReActAgent
from zzcode.cli.ui import create_ui
from zzcode.llm.client import ZzCodeLLM
from zzcode.tools.builtin import register_builtin_tools
from zzcode.tools.executor import ToolExecutor


def main() -> int:
    ui = create_ui()
    try:
        llm = ZzCodeLLM(stream=False)
    except Exception as exc:
        ui.error(f"Failed to initialize LLM: {exc}")
        return 1

    project_root = Path.cwd()
    tools = build_tools(project_root)
    ui.banner(model=llm.model or "(unknown)", tools=tools)
    agent = TextReActAgent(llm_client=llm, tool_executor=tools, max_steps=5, renderer=ui)

    ui.info("输入 /help 查看命令，输入 /exit 退出。")
    while True:
        try:
            user_input = ui.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            ui.goodbye()
            return 0

        if not user_input:
            continue

        command = user_input.lower()
        if command in {"/exit", "/quit", "exit", "quit"}:
            ui.goodbye()
            return 0
        if command == "/help":
            ui.help(tools)
            continue
        if command == "/clear":
            agent.history = []
            ui.info("history cleared")
            continue

        agent.run(user_input)


def build_tools(project_root: Path) -> ToolExecutor:
    tools = ToolExecutor()
    register_builtin_tools(tools, project_root)

    # Calculator 暂时保留为教学/调试工具，方便验证 ReAct 链路不依赖文件系统。
    tools.register_tool(
        "Calculator",
        "计算简单四则运算表达式，例如 Calculator[1+2*3]。",
        calculate,
        display_name="Calculator",
    )
    return tools


def calculate(expression: str) -> str:
    try:
        result = safe_eval_arithmetic(expression)
    except Exception as exc:
        return f"计算失败: {exc}"
    return str(result)


def safe_eval_arithmetic(expression: str) -> int | float:
    node = ast.parse(expression, mode="eval")
    return _eval_node(node.body)


def _eval_node(node: ast.AST) -> int | float:
    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
        return binary_ops[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
        return unary_ops[type(node.op)](_eval_node(node.operand))
    raise ValueError("只支持数字和简单四则运算。")


if __name__ == "__main__":
    raise SystemExit(main())
