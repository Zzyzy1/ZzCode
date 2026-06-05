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

## Step 05：React + Ink UI 壳子

为了更接近 Claude Code 的终端体验，第一阶段新增一个独立的 React + Ink 前端壳子。

这个壳子不是替换 Python Agent Core，而是把“界面”和“智能体执行”先拆开：

```text
frontend/ React + Ink
  -> 负责终端布局、输入框、消息列表、状态栏、工具展示

src/zzcode/ Python Core
  -> 负责 Agent 循环、LLM 调用、工具执行、安全边界
```

这样设计的原因是：UI 会长期存在，而 Agent 能力会持续变化。如果 UI 直接写死在 Python ReAct 循环里，后面接 MCP、Plan、Memory 时会频繁改 UI。先把 UI 做成事件驱动，就能让后续能力都只是在协议里新增事件或字段。

### 当前新增目录

```text
frontend/
├── package.json
├── tsconfig.json
└── src/
    ├── index.tsx
    ├── app/
    │   ├── App.tsx
    │   └── theme.ts
    ├── screens/
    │   ├── REPL.tsx
    │   └── reducer.ts
    ├── components/
    │   ├── layout/
    │   ├── messages/
    │   ├── prompt/
    │   ├── status/
    │   └── tools/
    └── protocol/
        ├── events.ts
        └── mockAgent.ts
```

### 当前已实现的 UI 能力

- Messages：按事件流展示用户输入、Thought、工具调用、工具结果、Final。
- ToolBlock：把 `tool_use` 和 `tool_result` 合并成 Claude 风格工具块。
- PromptInput：终端单行输入，支持输入、回车发送、退格。
- StatusBar：展示 ready、thinking、running tool、done，以及模型和工作目录。
- reducer：集中维护消息列表和运行状态。
- mockAgent：用异步事件模拟一次 Agent 回合。

### JSON Lines 协议草案

后续接 Python Core 时，前端不直接调用 Python 函数，而是通过标准输入输出传递 JSON Lines：

```json
{"type":"user_message","text":"读取 README.md"}
{"type":"assistant_thought","text":"我需要读取文件"}
{"type":"tool_use","id":"1","name":"read_file","input":"README.md","displayName":"Read"}
{"type":"tool_result","id":"1","name":"read_file","ok":true,"output":"# ZzCode..."}
{"type":"assistant_final","text":"README.md 的内容是..."}
```

当前先使用 `mockAgent.ts`，目的是只验证 UI 壳子。下一步再实现 Python 侧事件输出和 Node 侧 JSONL client。

### 本地运行

```bash
cd frontend
npm install
npm run dev
```

运行后输入任意普通任务，可以看到一轮 mock 的 Thought、工具调用、工具结果和 Final。

## Step 06：打通 Ink UI 和 Python Agent Core

当前已经把 React + Ink UI 从 mock 事件流切换到真实 Python 后端。

新的运行链路：

```text
用户在 Ink PromptInput 输入任务
  -> frontend/src/protocol/pythonAgent.ts
  -> 启动 python -m zzcode.protocol.server --once
  -> Python server 读取 user_message JSON
  -> TextReActAgent 调用 DeepSeek 和本地工具
  -> JsonLineRenderer 输出 assistant_thought/tool_use/tool_result/assistant_final
  -> Ink Messages 实时渲染事件流
```

### Python 侧新增模块

```text
src/zzcode/protocol/
├── __init__.py
├── events.py
└── server.py
```

职责：

- `server.py`：JSON Lines 后端入口，负责读取前端请求、组装 LLM/工具/Agent。
- `events.py`：把 Python 内部 `UiMessage` 转换成前端 `AgentEvent`。

为了保证 stdout 只输出 JSON Lines，`ZzCodeLLM` 的调试日志改为输出到 stderr。这样前端可以稳定解析 stdout。

### 前端侧新增模块

```text
frontend/src/protocol/pythonAgent.ts
```

职责：

- 启动 Python 子进程。
- 设置 `PYTHONPATH=项目根/src`。
- 把用户输入写成 `{"type":"user_message","text":"..."}`。
- 逐行解析 Python stdout 中的 JSON Lines。
- Python 退出异常时，把 stderr 转成 `system_notice`。

### 当前运行方式

默认真实后端：

```powershell
cd D:\zzy\JavaLearn\agent_learn\ZzCode\frontend
npm run dev
```

只看 UI mock：

```powershell
$env:ZZCODE_USE_MOCK="1"
npm run dev
```

如果 Windows 里没有 `python` 命令：

```powershell
$env:ZZCODE_PYTHON="py"
npm run dev
```

### 当前边界

- 现在每次用户输入都会启动一个 Python 子进程，简单可靠，便于学习。
- Agent 的长会话记忆还没有跨请求保存。
- 斜杠命令还没有迁移到 Ink UI。
- 工具权限确认、文件 diff、流式 token 输出还没有实现。

下一步可以把“一次一进程”改成“常驻 Python 会话”，同时实现 `/help`、`/clear`、`/exit` 等前端命令。

## 前端 UI 优化阶段待办表

当前目标是逐步把 Ink 壳子做成后续基本不用大改的完整 CLI UI。

| Step | 内容 | 状态 |
|---|---|---|
| Step 07 | Slash Command 与会话控制 | 已完成 |
| Step 08 | 常驻 Python backend session | 已完成 |
| Step 09 | PromptInput 输入体验强化 | 已完成 |
| Step 10 | 工具权限确认 UI | 已完成 |
| Step 11 | 文件 diff 与工具结果展示 | 已完成 |
| Step 12 | 状态栏、模式系统、工具 renderer 注册表 | 已完成 |

## Step 07：Slash Command 与会话控制

Ink 前端已经把斜杠命令从普通 Agent 请求中拆出来。

当前支持：

```text
/help     显示帮助
/clear    清空前端消息和 Python 会话历史
/mock     在 mock/python 后端之间切换
/mode     查看或切换 UI 模式
/exit     退出 ZzCode
/quit     退出 ZzCode
```

设计原则：

- 普通输入才发送给 Python Agent。
- `/xxx` 命令由 Ink 前端优先处理，不污染 Agent 上下文。
- 未知命令显示 `system_notice`。
- `/clear` 同时清空前端消息和后端短会话历史。
- `/mode` 只切换当前 UI 模式状态，第一阶段暂不改变 Agent 行为。

## Step 08：常驻 Python backend session

前端已经从“一次输入启动一个 Python 进程”改为“复用一个 Python 后端进程”。

当前链路：

```text
runPythonAgent(text)
  -> getPythonSession()
  -> stdin 写入 user_message JSONL
  -> stdout 读取 AgentEvent JSONL
  -> request_done 作为本次请求结束信号
```

Python server 新增控制请求：

```json
{"type":"clear_history"}
{"type":"shutdown"}
```

并新增结束事件：

```json
{"type":"request_done","ok":true}
```

常驻会话的好处：

- 不再每次输入都重新初始化 Python。
- 后端可以保存短会话历史。
- `/clear` 可以同步清理后端历史。
- 后续权限确认、取消任务、流式输出都可以基于同一条协议继续扩展。

当前跨轮历史采用短文本摘要，只保留最近几轮 `User/Assistant`。这是第一阶段的轻量实现，后续可以升级为更完整的上下文压缩机制。

## Step 09：PromptInput 输入体验强化

输入框仍然保持单行，但已经具备更接近真实 CLI 的编辑能力。

当前支持：

```text
Enter     发送
↑/↓       切换历史输入
←/→       移动光标
Ctrl+A    跳到行首
Ctrl+E    跳到行尾
Ctrl+U    清空当前输入
Ctrl+C    当前输入为空时退出，否则清空输入
```

实现要点：

- 输入框维护 `value`、`cursor`、`history`、`historyIndex`。
- 普通输入和粘贴内容都按当前光标位置插入。
- 历史输入只保留最近 30 条，并去重。
- Agent 运行中禁用输入，避免并发请求打乱协议事件流。

当前还没有做多行输入、命令补全、任务取消和复杂中文输入法适配，这些可以放到后续更完整的 PromptInput 阶段。

## Step 10：工具权限确认 UI

当前已经在工具执行前加入权限确认。

新的执行链路：

```text
模型输出 Action: ToolName[input]
  -> Agent 渲染 tool_use
  -> Agent 调用 permission_checker
  -> Python server 输出 permission_request
  -> Ink UI 展示 PermissionPrompt
  -> 用户选择 allow_once / allow_session / deny
  -> Ink 写回 permission_response
  -> Python 决定执行工具或把拒绝结果作为 Observation
```

协议新增事件：

```json
{"type":"permission_request","id":"permission-1","toolName":"write_file","displayName":"Write","input":"a.txt|||hello","risk":"medium"}
{"type":"permission_response","id":"permission-1","decision":"allow_once"}
```

当前按工具名做轻量风险分级：

| 工具 | 风险 |
|---|---|
| `run_shell` | high |
| `write_file` | medium |
| 其他工具 | low |

Ink 权限确认选单：

```text
1. Allow once，本次允许
2. Allow for session，本会话允许该工具
3. Deny，拒绝执行

↑/↓     移动选项
Enter   确认当前选项
1/2/3   直接选择对应选项
```

当前实现边界：

- `allow_session` 以工具名为粒度，不区分具体参数。
- 还没有做权限规则列表、撤销规则、危险命令详情解释。

这些能力会进入后续 Step 12 或更完整的权限系统阶段。

## Step 11：文件 diff 与工具结果展示

当前已经给 `write_file` 权限确认加入写入前 diff 预览，并按工具类型优化结果展示。

权限请求新增可选 `preview` 字段：

```json
{
  "type": "permission_request",
  "id": "permission-1",
  "toolName": "write_file",
  "displayName": "Write",
  "input": "a.txt|||hello",
  "risk": "medium",
  "preview": {
    "type": "write_file_diff",
    "path": "a.txt",
    "fileExists": false,
    "oldLineCount": 0,
    "newLineCount": 1,
    "lines": [{"kind": "add", "text": "+hello"}],
    "truncated": false
  }
}
```

实现要点：

- 后端在 `PermissionBridge` 发出 `permission_request` 前解析 `write_file` 的 `path|||content`。
- 后端读取项目内旧文件内容，使用 `difflib.unified_diff` 生成有限行数的 unified diff。
- 前端 `PermissionPrompt` 在选项上方渲染 `DiffPreview`，用户确认前就能看到将创建或修改的内容。
- 前端 `ToolResultView` 按工具名展示结果：`list_files` 展示列表，`read_file` 展示行号预览，`run_shell` 展示 stdout/stderr/exit code，`write_file` 展示写入摘要。

当前实现边界：

- diff 预览只支持 `write_file`，且依赖当前文本版 `path|||content` 协议。
- diff 最多展示 80 行，超出后标记 truncated。
- 非 UTF-8 旧文件无法生成 diff，会在权限面板显示错误说明。
- 还没有做真正的结构化工具参数、语法高亮、折叠展开和 IDE diff。

## Step 12：状态栏、模式系统、工具 renderer 注册表

当前已经加入轻量模式系统、增强状态栏，并把工具结果展示改成 renderer 注册表。

当前模式：

```text
default   默认模式
readonly 只读观察
plan     计划模式
```

当前 `/mode` 命令：

```text
/mode                 查看当前模式和可用模式
/mode default         切回默认模式
/mode readonly        切换为只读观察
/mode plan            切换为计划模式
```

状态栏现在展示：

```text
运行状态
最近工具
当前 mode
当前 backend
当前 model
当前 cwd
权限等待状态
```

工具结果展示已经从 `if toolName === ...` 改为注册表：

```text
toolResultRenderers = {
  list_files,
  read_file,
  run_shell,
  write_file
}
```

当前实现边界：

- `readonly` 和 `plan` 目前只是 UI 模式状态，还没有影响 Python Agent prompt、工具权限或可用工具列表。
- renderer 注册表只覆盖工具结果展示，权限 diff 预览仍是独立组件。
- 还没有做模式持久化、模式快捷键和状态栏配置项。

## 前端 UI 体验增强阶段

这一阶段继续完善 Ink 前端的输入体验和启动界面。

| Step | 内容 | 状态 |
|---|---|---|
| Step 13 | 多行输入 | 已完成 |
| Step 14 | 输入框优化 | 已完成 |
| Step 15 | 配色优化 | 已完成 |
| Step 16 | 开始界面优化 | 已完成 |

## Step 13：多行输入

当前 `PromptInput` 已经从单行输入升级为多行输入。

当前支持：

```text
Enter       发送
Shift+Enter 插入换行
\ + Enter   续行输入
↑/↓         多行内移动；到边界后切换历史输入
←/→         左右移动光标
Ctrl+A/E    跳到当前行首/行尾
Ctrl+U      清空当前行光标前内容
Ctrl+C      当前输入为空时退出，否则清空输入
```

实现要点：

- 参考 Claude 的输入思路，用全局 cursor offset 管理完整文本。
- `↑/↓` 优先在多行内移动，移动不了时才触发历史输入切换。
- 支持粘贴多行内容，按当前光标位置插入。

## Step 14：输入框优化

输入区域已经从裸文本行改为稳定的 prompt 面板。

当前展示：

```text
zzcode › Enter send · Shift+Enter newline · \ + Enter continue · N lines
> 当前输入内容
· 后续输入行
```

实现边界：

- 还没有做自动换行测量，只按显式换行渲染。
- 还没有做命令补全、选择建议和 Vim 输入模式。

## Step 15：配色优化

当前主题已从高饱和终端色调整为柔和低饱和配色。

主要变化：

- 主色使用柔和浅蓝。
- 用户色使用低饱和淡紫。
- 成功、警告、危险色降低视觉刺激。
- 边框使用灰蓝色，减少界面噪声。

## Step 16：开始界面优化

空消息状态已经改成欢迎页。

欢迎页包含：

```text
Zz Code 标题
卡通终端形象
欢迎提示
Tips & updates
Quick commands
```

设计原则：

- 参考 `docs/front.png` 的信息结构，但保持 Ink 终端可读。
- 不引入图片依赖，使用终端字符绘制轻量卡通形象。
- 首页只在消息为空时显示，用户发起任务后切换为事件消息流。

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
