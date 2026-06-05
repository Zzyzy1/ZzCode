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
    """启动交互式 CLI。

    负责创建 UI、LLM、工具注册表和 Agent；返回进程退出码。
    """

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

        # 斜杠命令由 CLI 自己处理，普通输入才交给 Agent。
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
    """创建本次会话可用的工具集合。

    project_root 表示工具操作的项目根目录；返回已注册内置工具的 ToolExecutor。
    """

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
    """计算教学用四则运算表达式。

    expression 是模型传入的算式字符串；返回计算结果或错误文本。
    """

    try:
        result = safe_eval_arithmetic(expression)
    except Exception as exc:
        return f"计算失败: {exc}"
    return str(result)


def safe_eval_arithmetic(expression: str) -> int | float:
    """安全计算简单算术表达式。

    expression 只允许数字和基础运算符；返回 int 或 float。
    """

    node = ast.parse(expression, mode="eval")
    return _eval_node(node.body)


def _eval_node(node: ast.AST) -> int | float:
    """递归求值 AST 节点。

    node 是表达式 AST；返回该节点的数值结果，不支持的语法会抛 ValueError。
    """

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
    # 只允许白名单中的 AST 节点，避免 eval 执行任意 Python 代码。
    if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
        return binary_ops[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
        return unary_ops[type(node.op)](_eval_node(node.operand))
    raise ValueError("只支持数字和简单四则运算。")


if __name__ == "__main__":
    raise SystemExit(main())
