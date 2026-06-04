# ZzCode

ZzCode 是一个用于学习的 Python 版 Code Agent CLI 项目。

项目目标是模仿现代终端编程智能体的核心能力，先从最小 ReAct + Tool Call demo 做起，再逐步加入 MCP、Memory、RAG、Plan 模式、多 Agent 等功能。

## 当前阶段

当前处于第一阶段：ReAct + Tool Call Demo。

这一阶段只关注一件事：让一个 Python CLI 能跑通 Agent 的核心循环。

核心流程：

```text
用户输入任务
  -> 模型判断是否需要调用工具
  -> Python 程序执行工具
  -> 工具结果回灌给模型
  -> 模型继续判断或输出最终答案
```

## 当前目录

```text
ZzCode/
├── README.md
├── AGENTS.md
├── docs/
│   └── phase-01-react-toolcall-demo.md
├── src/
│   └── zzcode/
│       ├── cli/
│       ├── agent/
│       ├── llm/
│       ├── tools/
│       └── runtime/
└── tests/
```

## 文档

- `AGENTS.md`：项目协作说明、架构约定和阶段规划。
- `docs/phase-01-react-toolcall-demo.md`：第一阶段实现方案和学习笔记。

## 第一阶段计划实现

- CLI 交互入口。
- ReAct Agent 主循环。
- Mock LLM Client。
- OpenAI-compatible LLM Client。
- 工具注册表。
- 四个基础工具：`list_files`、`read_file`、`write_file`、`run_shell`。
- 基础测试。

## 暂不实现

第一阶段暂不实现 MCP、Memory、RAG、Plan DAG、多 Agent、复杂 TUI、Git 快照等功能。

先把最核心的 Agent Loop 理解清楚，再继续扩展。
