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

## 当前实现策略

第一阶段先采用 `hello-agents/code/chapter4` 的教学版 ReAct 写法，而不是一开始就使用 OpenAI 的结构化 `tool_calls`。

当前策略：

```text
PaiCLI：提供项目演进路线和功能目标
hello-agents chapter4：提供第一版代码实现模板
```

也就是说，第一阶段先跑通文本协议：

```text
Thought: ...
Action: ToolName[input]
Observation: ...
Action: Finish[最终答案]
```

等这个流程清楚之后，再升级为真实 OpenAI-compatible `tool_calls`。

## 第一阶段 Python 项目结构

采用 Python 常见的 `src/` 布局：

```text
src/zzcode/
├── cli/
│   ├── main.py
│   └── ui.py
├── agent/
│   └── react_text.py
├── llm/
│   └── client.py
├── tools/
│   └── executor.py
├── ui/
│   ├── messages.py
│   └── renderer.py
└── runtime/
    └── config.py
```

模块职责：

- `cli`：终端输入输出、斜杠命令、启动交互循环。
- `agent`：ReAct 主循环、消息历史、工具结果回灌。
- `llm`：模型客户端抽象、Mock 模型、OpenAI 兼容模型调用。
- `tools`：工具定义、工具 schema、工具注册表、工具执行。
- `ui`：UI 消息模型和 inline renderer。
- `runtime`：配置读取、运行时状态。

这个结构是为 Python CLI 设计的，不照搬 PaiCLI 的 Java 目录。

## Step 01：文本版 ReAct 内核

当前已经先实现最小教学内核和交互式 CLI：

```text
src/zzcode/
├── __init__.py
├── agent/
│   ├── __init__.py
│   └── react_text.py
├── llm/
│   ├── __init__.py
│   └── client.py
├── cli/
│   ├── __init__.py
│   ├── main.py
│   └── ui.py
├── tools/
    ├── __init__.py
    └── executor.py
└── ui/
    ├── __init__.py
    ├── messages.py
    └── renderer.py
```

### 已实现内容

- `ZzCodeLLM`：参考 hello-agents 的 `HelloAgentsLLM`，封装 OpenAI-compatible 模型调用。
- `ThinkClient`：定义 TextReActAgent 需要的最小 LLM 协议。
- `ToolExecutor`：参考 hello-agents 的 `ToolExecutor`，支持注册工具、查看工具、执行工具。
- `TextReActAgent`：使用 `Thought/Action` 文本格式完成 ReAct 循环。
- `REACT_PROMPT_TEMPLATE`：要求模型输出 `Thought:` 和 `Action:`。
- Action 解析规则：支持 `ToolName[input]` 和 `Finish[最终答案]`。
- `zzcode.cli.main`：交互式 CLI 入口，支持 `/help`、`/clear`、`/exit`。
- `zzcode.cli.ui`：轻量终端 UI 层，优先使用 Rich；未安装 Rich 时退回纯文本输出。
- 当前 demo 工具：`Echo` 和 `Calculator`，用于先验证 ReAct 工具调用链路。

### 当前 Step 01 的边界

这一步还没有实现：

- 文件工具。
- shell 工具。
- OpenAI 结构化 `tool_calls`。
- 测试文件。

这一步的目的只是把 hello-agents chapter4 的 ReAct 核心方式迁移到 ZzCode 的 Python 包结构中。

## Step 02：轻量 CLI 美化

当前 CLI 已加入一版轻量美化，并在 Step 03 中进一步改成 Claude Code 风格的 inline 消息：

- 启动时用面板展示版本、模式、模型和工具列表。
- `/help` 用表格展示命令和工具。
- 错误和警告使用统一样式。

依赖文件：

```text
requirements.txt
```

当前只新增：

```text
rich>=13.7.0
```

本地如果没有 Rich，可以执行：

```bash
pip install -r requirements.txt
```

如果没有安装 Rich，CLI 仍然可以用纯文本模式运行。

## Step 03：学习 Claude Code 的消息驱动渲染

Claude Code 的 CLI 主界面不是散落的 `console.log`，而是：

```text
REPL
  -> Messages
    -> MessageRow
      -> Message
        -> AssistantTextMessage / AssistantToolUseMessage / UserTextMessage / SystemTextMessage
```

ZzCode 当前学习这个模式，做了一个最小 Python 版：

```text
Agent
  -> UiMessage
  -> InlineRenderer
  -> Terminal
```

### 新增 UI 消息模型

`src/zzcode/ui/messages.py` 定义当前几类消息：

- `StepStarted`：Agent 开始新一轮。
- `AssistantThought`：模型思考内容。
- `ToolUse`：模型请求调用工具。
- `ToolResult`：工具执行结果。
- `FinalAnswer`：最终答案。
- `SystemNotice`：系统提示、警告、错误。

### 新增 inline renderer

`src/zzcode/ui/renderer.py` 提供两个 renderer：

- `PlainInlineRenderer`：无 Rich 时的纯文本展示。
- `RichInlineRenderer`：Rich 版本的 Claude 风格 inline 展示。

当前显示风格：

```text
Step 1/5
● Thought
  需要调用 Calculator 工具。
● Calculator(1+2*3)
  ⎿ 7

Step 2/5
● Final
  结果是 7。
```

这个风格比大块 Panel 更接近 Claude Code：轻量、行内、适合连续对话。

### 工具展示元数据

`RegisteredTool` 新增 `display_name` 字段。后续可以继续演进为：

```text
user_facing_name(input)
render_tool_use_message(input)
render_tool_result(output)
```

这对应 Claude Code 中工具自己提供展示逻辑的模式。

## Step 04：第一批真实 Code CLI 工具

当前已经从教学工具过渡到基础 Code CLI 工具。

新增文件：

```text
src/zzcode/tools/
├── builtin.py
└── safety.py
```

### 已实现工具

| 工具名 | 用途 | 输入格式 |
|---|---|---|
| `list_files` | 列出项目内目录内容 | `path` |
| `read_file` | 读取项目内 UTF-8 文本文件，最大 100KB | `path` |
| `write_file` | 写入项目内文本文件 | `path|||content` |
| `run_shell` | 在项目根目录执行简单 shell 命令 | `command` |

`Calculator` 暂时保留为教学/调试工具，方便验证 ReAct 链路。

### 文本版 write_file 协议

由于当前还是 hello-agents 风格的文本 Action：

```text
Action: ToolName[input]
```

所以 `write_file` 暂时不能传 JSON 参数，先使用分隔符协议：

```text
Action: write_file[hello.txt|||hello zzcode]
```

后续升级到 OpenAI-compatible `tool_calls` 后，再把参数改成结构化 JSON：

```json
{"path": "hello.txt", "content": "hello zzcode"}
```

### 最小安全规则

`safety.py` 当前包含两类基础防护：

- 路径围栏：所有文件路径都会解析到项目根目录内，拒绝 `..` 或绝对路径逃逸。
- 命令快速拒绝：拒绝明显危险命令，例如 `sudo`、`rm -rf /`、`shutdown`、`mkfs`、`dd of=` 等。

这些规则不是沙箱，只是第一阶段的学习护栏。

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
