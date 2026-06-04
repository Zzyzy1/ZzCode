# 第一阶段：ReAct + Tool Call Demo

## 阶段目标

第一阶段要完成一个最小但完整的 Python CLI demo，用来证明 Agent 的核心循环能跑通：

1. 用户在终端输入任务。
2. CLI 把用户任务和可用工具定义发送给 LLM Client。
3. LLM 直接回答，或者返回一个或多个工具调用请求。
4. 本地 Python 程序根据工具名执行对应工具。
5. 工具执行结果作为 `tool` 消息追加回对话历史。
6. Agent 继续请求模型，直到模型给出最终答案，或者达到最大循环步数。

这一阶段的重点是理解机制，不是做一个完整的 Claude Code 复制品。

## 要学习的核心概念

### ReAct 是什么

ReAct 可以理解为 Reasoning + Acting：

- Reasoning：模型分析当前任务，判断下一步需要什么。
- Acting：程序执行模型请求调用的工具。
- Observing：程序把工具执行结果返回给模型，让模型继续判断。

关键点：模型本身不会真的读文件、写文件、执行命令。模型只是返回结构化的工具调用请求，真正的执行者是本地 CLI 程序。

### Tool Call 是什么

一个 Tool Call 至少包含三部分：

- 工具名，例如 `read_file`。
- JSON 参数，例如 `{"path": "README.md"}`。
- 工具调用 id，用来把工具结果和 assistant 的工具调用消息关联起来。

CLI 会把工具的名称、用途和参数结构发给模型。模型根据这些信息决定是否调用工具，并生成符合结构的参数。

## 第一阶段 Python 项目结构

采用 Python 常见的 `src/` 布局：

```text
src/zzcode/
├── cli/
│   └── main.py
├── agent/
│   └── react.py
├── llm/
│   ├── base.py
│   ├── mock.py
│   └── openai_compatible.py
├── tools/
│   ├── base.py
│   ├── registry.py
│   └── builtin.py
└── runtime/
    └── config.py
```

模块职责：

- `cli`：终端输入输出、斜杠命令、启动交互循环。
- `agent`：ReAct 主循环、消息历史、工具结果回灌。
- `llm`：模型客户端抽象、Mock 模型、OpenAI 兼容模型调用。
- `tools`：工具定义、工具 schema、工具注册表、工具执行。
- `runtime`：配置读取、运行时状态。

这个结构是为 Python CLI 设计的，不照搬 PaiCLI 的 Java 目录。

## 最小 CLI 行为

第一阶段 CLI 支持三个斜杠命令：

```text
/help    查看命令说明
/clear   清空当前对话历史
/exit    退出 CLI
```

除了斜杠命令外，其他输入都作为 Agent 任务处理。

示例：

```text
zzcode> 帮我列出当前项目的文件
```

预期流程：

```text
[assistant requested tool] list_files {"path": "."}
[tool result] ...
[assistant] 当前项目包含这些文件...
```

## 第一批内置工具

第一阶段先实现四个工具：

| 工具名 | 用途 |
|---|---|
| `list_files` | 列出指定目录下的文件和文件夹 |
| `read_file` | 读取文本文件 |
| `write_file` | 写入文本文件 |
| `run_shell` | 执行简单 shell 命令 |

### 最小安全约束

第一阶段需要有一些基础防护：

- 文件路径统一基于项目根目录解析。
- 拒绝访问项目根目录之外的路径。
- 限制单次读取文件大小。
- shell 命令设置超时时间。
- 拒绝明显危险的命令，例如 `sudo`、`rm -rf /`、`shutdown`、磁盘格式化相关命令。

这些规则不是沙箱，只是学习阶段的基本护栏。

## LLM 模式

第一阶段支持两种模式。

### Mock 模式

Mock 模式不需要 API Key，主要用于学习和测试。

它可以先用简单规则模拟模型行为：

- 用户要求列目录时，返回 `list_files` 工具调用。
- 用户要求读文件时，返回 `read_file` 工具调用。
- 用户要求写文件时，返回 `write_file` 工具调用。
- 用户要求执行命令时，返回 `run_shell` 工具调用。
- 收到工具结果后，返回最终答案。

这样即使没有真实模型，也能先跑通 Agent Loop。

### OpenAI 兼容模式

真实模型模式对接 OpenAI-compatible Chat Completions API。

建议环境变量：

```env
ZZCODE_PROVIDER=mock
ZZCODE_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZZCODE_API_KEY=
ZZCODE_MODEL=glm-5.1
```

默认使用 Mock 模式，保证项目随时可以启动。

## ReAct 主循环伪代码

```python
messages = [system_message, user_message]

for step in range(max_steps):
    response = llm.chat(messages=messages, tools=registry.tool_schemas())

    if response.tool_calls:
        messages.append(response.assistant_message)
        for call in response.tool_calls:
            result = registry.execute(call.name, call.arguments)
            messages.append(tool_message(call.id, result))
        continue

    messages.append(response.assistant_message)
    return response.content

return "已停止：达到最大执行步数。"
```

## 验收标准

第一阶段完成时，需要满足：

- `python -m zzcode.cli.main` 可以启动命令行。
- `/help`、`/clear`、`/exit` 可用。
- 没有 API Key 时，Mock 模式可以跑通。
- Agent 可以调用并执行 `list_files`。
- Agent 可以调用并执行 `read_file`。
- Agent 可以调用并执行 `write_file`。
- Agent 可以调用并执行 `run_shell`。
- 工具结果会被追加回模型对话历史。
- 至少有工具注册表和 Mock ReAct 循环的基础测试。

## 第一阶段暂不实现

以下内容不在第一阶段实现：

- MCP
- Plan DAG
- Multi-Agent
- 长期记忆
- RAG 代码检索
- Skill 系统
- 复杂 TUI 和状态栏
- Git 快照
- 浏览器自动化
- 图片输入

这些能力等 ReAct + Tool Call 主链路能够稳定跑通、并且可以清楚讲明白之后再逐步加入。
