# 第三阶段：Claude Code 风格 Subagents

## 阶段目标

第三阶段为 ZzCode 增加子 Agent 能力，并把子 Agent 分成两条线实现：

1. 用户子 Agent：主 Agent 可以通过一个普通工具，把明确任务委托给独立子 Agent。
2. 系统子 Agent：ZzCode 内部使用 forked agent 执行后台维护任务，例如 session memory 更新、auto memory 提取和 compact 前摘要。

本阶段参考 Claude Code 的实现框架，但按 ZzCode 当前代码规模落地：

```text
AgentTool
-> AgentDefinition
-> SubagentContext
-> runAgent
-> sidechain transcript
-> LocalAgentTask / runForkedAgent
```

ZzCode 第一版不做完整后台任务面板、worktree、远程 agent、teammate 协作和 MCP per-agent 配置。第一版要保证主链完整：能启动、能隔离、能记录、能按权限执行、能返回结果。

Claude Code 子 Agent 参考实现已单独整理到 `docs/phase-03-claude-subagents-reference.md`。后续实现优先参考该文档，不再每一步重复读取 Claude 源码，除非遇到文档缺失或需要重新核对。

## Claude Code 子 Agent 要点

Claude Code 的子 Agent 不是单纯再调用一次模型，而是一套完整执行系统。

### AgentTool

`AgentTool` 是主 Agent 可调用的工具。它接收：

```text
description
prompt
subagent_type
model
run_in_background
```

执行时会：

1. 根据 `subagent_type` 选择 agent 定义。
2. 检查 agent 是否存在、是否被权限规则禁用。
3. 检查 MCP 等依赖是否可用。
4. 组装子 Agent 的 system prompt。
5. 根据 agent 定义重新组装工具池。
6. 创建独立 `agentId`。
7. 按同步或后台方式运行子 Agent。
8. 把子 Agent 过程写入 sidechain transcript。
9. 汇总最终结果返回给主 Agent。

### AgentDefinition

Claude 的 agent 定义可以来自内置、插件、用户 markdown、项目 markdown。一个定义通常包含：

```text
agentType
whenToUse
tools
disallowedTools
model
permissionMode
mcpServers
hooks
maxTurns
skills
memory
background
isolation
```

ZzCode 第一版需要保留这些字段中会影响主链的部分：

```text
name
description
system_prompt
tools
disallowed_tools
model
permission_mode
max_steps
background
```

其余字段先写入文档 TODO，不进入第一版代码路径。

### SubagentContext

Claude 会通过 `createSubagentContext` 创建隔离上下文。隔离内容包括：

- 独立 agentId。
- 独立 messages/history。
- 独立 transcript。
- 独立 abort controller。
- 独立 read file cache。
- 独立工具决策状态。
- 必要时共享父级 AppState 或指标回调。

ZzCode 第一版需要隔离：

- `agent_id`
- `parent_session_id`
- `subagent_name`
- `history`
- `tool_executor`
- `permission_checker`
- `transcript`
- `renderer`

### runAgent

Claude 的 `runAgent` 是子 Agent 查询循环。它负责：

1. 解析 agent 定义。
2. 构建子 Agent system prompt。
3. 构建 user context 和 system context。
4. 初始化 agent 专属 MCP、skills、hooks。
5. 创建子 Agent tool context。
6. 调用主 `query()` 循环。
7. 持续记录 sidechain transcript。
8. 完成后清理资源。

ZzCode 第一版可以复用 `TextReActAgent` 作为子 Agent 执行循环，但必须使用独立上下文和独立 transcript。

### runForkedAgent

Claude 的系统任务会使用 `runForkedAgent`。它用于：

- Session memory updater。
- Auto memory extraction。
- Compact summary。
- Prompt suggestion。

关键行为：

1. 读取父会话的必要上下文。
2. 创建隔离子上下文。
3. 使用受限工具池。
4. 运行一段专用 prompt。
5. 写入独立 transcript。
6. 返回消息和 usage。

ZzCode 的系统子 Agent 应单独实现，不和用户可调用的 `agent` 工具混在一起。

## 阶段开始前 ZzCode 状态

第三阶段开始前，ZzCode 只有一个主 Agent：

```text
src/zzcode/protocol/server.py
-> TextReActAgent
-> ToolExecutor
-> builtin tools
-> TranscriptRecorder
```

阶段开始前已经具备的基础：

- `TextReActAgent` 可以执行文本 ReAct 循环。
- `ToolExecutor` 可以注册和执行工具。
- `PermissionBridge` 可以做工具权限确认。
- `TranscriptRecorder` 可以写结构化 `transcript.jsonl`。
- `.zzcode/sessions/<session-id>/` 已经存在。
- memory 目录和当前 session memory 已经有自动允许写入规则。

阶段开始前缺失：

- 没有 agent 定义加载。
- 没有用户子 Agent 工具。
- 没有子 Agent 独立 transcript。
- 没有子 Agent 独立工具池。
- 没有系统 forked agent runner。
- 没有 session memory updater。
- 没有 auto memory extraction worker。

## 第一版总体设计

第一版实现两个执行入口：

```text
用户子 Agent:
main TextReActAgent
-> agent tool
-> UserSubagentRunner
-> child TextReActAgent
-> sidechain transcript
-> final result

系统子 Agent:
server turn finished
-> SystemAgentScheduler
-> ForkedAgentRunner
-> restricted tools
-> memory/session/compact worker
-> sidechain transcript
```

两条线共用基础模块：

```text
src/zzcode/subagents/
├── __init__.py
├── definition.py
├── loader.py
├── context.py
├── transcript.py
├── user_runner.py
├── forked_runner.py
├── restricted_tool_executor.py
└── system.py
```

## 用户子 Agent 实现步骤

### Step 1：AgentDefinition

新增 `SubagentDefinition`：

```text
name: str
description: str
system_prompt: str
tools: list[str] | None
disallowed_tools: list[str] | None
model: str | None
permission_mode: str | None
max_steps: int | None
background: bool
source: str
```

第一版内置一个 `general-purpose`：

```text
name: general-purpose
description: 通用子 Agent，适合搜索、阅读、分析和总结
tools: list_files, read_file, run_shell
max_steps: 5
background: false
```

### Step 2：AgentDefinition Loader

加载顺序参考 Claude 的覆盖规则：

```text
built-in
-> user agents
-> project agents
```

建议路径：

```text
~/.zzcode/agents/*.md
.zzcode/agents/*.md
```

markdown frontmatter：

```text
---
name: general-purpose
description: 通用子 Agent
tools: list_files, read_file, run_shell
max_steps: 5
---

你是一个专门执行子任务的 ZzCode 子 Agent。
```

第一版可以先完成 loader 和 parser，但实际默认只依赖内置 `general-purpose`。

### Step 3：SubagentContext

新增 `SubagentContext`，保存一次子 Agent 执行需要的状态：

```text
agent_id
parent_session_id
session_dir
subagent_name
transcript_path
metadata_path
project_root
```

路径建议：

```text
.zzcode/sessions/<session-id>/subagents/<agent-id>/metadata.json
.zzcode/sessions/<session-id>/subagents/<agent-id>/transcript.jsonl
```

### Step 4：Sidechain Transcript

新增子 Agent transcript 记录器，事件格式尽量和主 transcript 对齐：

```text
eventId
parentEventId
sequence
sessionId
agentId
parentSessionId
type
createdAt
```

需要记录：

- user：子 Agent 收到的任务。
- assistant：子 Agent 最终回答。
- tool_use：子 Agent 工具调用。
- tool_result：子 Agent 工具结果。
- error：执行失败。

### Step 5：工具池重建

根据 `SubagentDefinition.tools` 创建子 Agent 专属 `ToolExecutor`。

规则：

- 未声明 `tools` 时，默认继承主工具池。
- 声明 `tools` 时，只注册这些工具。
- `disallowed_tools` 从最终工具池移除。
- 子 Agent 写文件、跑命令仍走 `PermissionBridge`。
- `.zzcode/memory/**/*.md` 和当前 session memory 的自动允许规则继续生效。

### Step 6：UserSubagentRunner

`UserSubagentRunner` 负责：

1. 根据 `subagent_type` 找到定义。
2. 创建 `SubagentContext`。
3. 创建子 Agent 专属 tool executor。
4. 创建子 Agent transcript。
5. 构建子 Agent prompt。
6. 调用 `TextReActAgent.run()`。
7. 返回最终结果文本。
8. 写入 metadata 和 transcript。

子 Agent prompt 应包含：

```text
你是 ZzCode 子 Agent。
你的任务来自主 Agent。
只完成委托任务，不要询问用户。
如果需要工具，按可用工具执行。
最终输出应是可以交给主 Agent 使用的结果。
```

### Step 7：注册 agent 工具

在主工具池注册 `agent` 工具。

输入格式第一版建议：

```text
subagent_type|||description|||prompt
```

示例：

```text
agent[general-purpose|||检查记忆模块|||阅读 src/zzcode/memory，说明当前有哪些文件和职责]
```

返回：

```text
Agent <agent-id> completed.
Result:
...
Transcript:
.zzcode/sessions/<session-id>/subagents/<agent-id>/transcript.jsonl
```

后续可以改成 JSON 输入，但第一版继续贴合当前 `ToolExecutor` 的字符串工具协议。

### Step 8：用户子 Agent 测试

需要补测试：

- 能加载内置 `general-purpose`。
- 能解析 `.zzcode/agents/*.md`。
- agent 工具能创建子 Agent transcript。
- 子 Agent 只看到定义允许的工具。
- disallowed tools 能生效。
- 子 Agent 工具调用仍触发权限检查。
- 子 Agent 失败时返回错误，不破坏主会话。

## 系统子 Agent 实现步骤

系统子 Agent 第一版服务第二阶段遗留的 memory 差异。

### Step 1：ForkedAgentRunner

新增 `ForkedAgentRunner`，对齐 Claude `runForkedAgent` 的职责：

```text
输入专用 prompt
读取父会话上下文
创建隔离 context
使用受限工具池
执行 TextReActAgent
写 sidechain transcript
返回执行结果
```

它不注册为主 Agent 工具，只给内部 worker 调用。

### Step 2：RestrictedToolExecutor

系统子 Agent 必须有受限工具池。

建议支持：

```text
allow_tools: set[str]
allow_write_paths: list[Path]
allow_read_paths: list[Path] | None
```

Auto memory worker：

```text
允许读取项目文件
允许写 .zzcode/memory/**/*.md
允许写 .zzcode/memory/MEMORY.md
```

Session memory worker：

```text
允许读取当前 transcript
只允许 edit/write 当前 session summary.md
```

Compact worker：

```text
允许读取当前 transcript
允许读取当前 summary.md
必要时只允许写当前 summary.md
```

### Step 3：SystemAgentScheduler

在每轮主 Agent 完成后触发：

```text
system_agents.on_turn_finished(...)
```

第一版同步执行，顺序固定：

```text
SessionMemoryUpdateWorker
-> AutoMemoryExtractionWorker
```

compact 前额外触发：

```text
SessionMemoryUpdateWorker(force=True)
```

### Step 4：SessionMemoryUpdateWorker

目标：让 `.zzcode/sessions/<session-id>/session-memory/summary.md` 随当前会话更新。

流程：

```text
读取当前 summary.md
读取 transcript 中 last_summarized_event_id 之后的新事件
构建 session memory update prompt
ForkedAgentRunner 执行
只允许更新当前 summary.md
写入状态文件
```

状态文件：

```text
.zzcode/sessions/<session-id>/system/session-memory-state.json
```

包含：

```text
last_summarized_event_id
last_updated_at
turn_count
```

触发条件第一版：

- 每轮成功回答后尝试更新。
- 如果没有新事件则跳过。
- compact 前强制更新。

### Step 5：AutoMemoryExtractionWorker

目标：主 Agent 没主动写 memory 时，系统子 Agent 也能根据语义提取长期记忆。

流程：

```text
读取 auto-memory-state.json
读取 transcript 增量
扫描 .zzcode/memory/ manifest
构建 auto memory extraction prompt
ForkedAgentRunner 执行
写详细 memory markdown
更新 MEMORY.md
写入状态文件
```

状态文件：

```text
.zzcode/sessions/<session-id>/system/auto-memory-state.json
```

包含：

```text
last_processed_event_id
last_updated_at
last_memory_write_event_id
```

第一版要避免重复写：

- 如果本轮主 Agent 已经写过 `.zzcode/memory/**/*.md`，可以跳过 AutoMemoryExtractionWorker。
- 执行前扫描 `MEMORY.md` 和 memory manifest，优先更新已有文件。

### Step 6：Compact 联动

当前 compact 只处理进程内短期历史。

第三阶段接入：

```text
compact_history request
-> SessionMemoryUpdateWorker(force=True)
-> ShortTermSessionMemory.compact()
-> TranscriptRecorder.record_compact()
```

后续再进一步改成基于 transcript 和 session memory 的 compact。

### Step 7：系统子 Agent 测试

需要补测试：

- ForkedAgentRunner 能创建系统子 Agent transcript。
- RestrictedToolExecutor 拒绝越权写入。
- SessionMemoryUpdateWorker 能更新当前 summary.md。
- AutoMemoryExtractionWorker 能写 memory topic 文件和 MEMORY.md。
- 有游标时只处理新增 transcript。
- 主 Agent 已写 memory 时，AutoMemoryExtractionWorker 不重复提取。

## 暂不实现

以下能力来自 Claude Code，但第三阶段第一版先不做：

1. 后台异步任务 UI。
2. agent 任务面板和实时进度。
3. foreground agent 中途转 background。
4. worktree isolation。
5. remote agent。
6. teammate / multi-agent team。
7. SendMessage。
8. MCP per-agent 配置。
9. skills 预加载。
10. SubagentStart / SubagentStop hooks。
11. agent memory snapshot。
12. prompt cache 兼容优化。
13. token 级 usage 统计。

这些内容在文档中保留位置，等基础用户子 Agent 和系统子 Agent 跑通后再补。

## 验收标准

### 用户子 Agent

- 主 Agent 的工具列表中出现 `agent`。
- 主 Agent 可以调用 `agent[...]` 委托任务。
- 子 Agent 有独立 `agent_id`。
- 子 Agent transcript 写入 `.zzcode/sessions/<session-id>/subagents/<agent-id>/transcript.jsonl`。
- 子 Agent 只能使用定义允许的工具。
- 子 Agent 写文件、跑命令仍走原权限策略。
- 子 Agent 失败时主会话继续运行，并返回明确错误。

### 系统子 Agent

- 每轮完成后可以触发系统 Agent 调度器。
- 当前 session `summary.md` 可以被 SessionMemoryUpdateWorker 更新。
- `.zzcode/memory/MEMORY.md` 和 topic memory 文件可以被 AutoMemoryExtractionWorker 更新。
- 系统子 Agent 写权限被限制在目标 memory/session 路径。
- 系统子 Agent 有独立 transcript。
- 状态文件能记录已处理游标，避免重复处理 transcript。

## 第一版完成结果

第三阶段第一版已完成用户子 Agent 和系统子 Agent 主链。

### 用户子 Agent

- 主工具池注册 `agent` 工具，支持 `subagent_type|||description|||prompt` 字符串协议。
- 内置 `general-purpose` 子 Agent，对齐 Claude general-purpose 的通用能力，允许当前内置文件读写工具和 `run_shell`。
- 支持从 `~/.zzcode/agents/*.md` 和 `.zzcode/agents/*.md` 加载 markdown agent 定义。
- 每次子 Agent 执行创建独立 `agent_id`、metadata 和 sidechain transcript。
- 子 Agent 使用独立 `TextReActAgent`、独立工具池和静默 renderer，不污染主 UI。
- 子 Agent 写文件、执行命令仍走主权限确认链路。

### 系统子 Agent

- 实现 `ForkedAgentRunner`，供内部 worker 运行系统子 Agent。
- 实现 `RestrictedToolExecutor`，按工具名和读写路径限制系统子 Agent 权限。
- 实现 `SessionMemoryUpdateWorker`，基于主 transcript 增量更新当前 session 的 `summary.md`。
- 实现 `AutoMemoryExtractionWorker`，基于主 transcript 增量提取长期记忆，并在主 Agent 已写 `.zzcode/memory/` 时跳过以避免重复提取。
- 实现 `SystemAgentScheduler`，在每轮成功回答后触发 session memory 和 auto memory worker。
- `compact_history` 前会强制刷新当前 session memory。

### 解析与安全修正

- 文本 ReAct action 解析改为严格解析单个平衡括号 action。
- 如果 action 后面出现 `</think>`、第二个 `Action:` 或其他尾随文本，会判为非法 action，避免污染 `write_file` 等工具参数。
- 长期方向仍是升级到结构化 tool call 协议，减少自由文本解析风险。

## 验收记录

已完成的自动验证：

```text
env PYTHONPATH=src python3 -m unittest discover -s tests
env PYTHONPYCACHEPREFIX=/tmp/zzcode-pycache python3 -m compileall src tests
```

已完成的前端真实验证：

- 主 Agent 可以通过 `agent` 工具启动 `general-purpose` 子 Agent。
- 子 Agent 可以写入文件，并生成独立 sidechain transcript。
- 每轮成功回答后生成或更新：

```text
.zzcode/sessions/<session-id>/system/session-memory-state.json
.zzcode/sessions/<session-id>/system/auto-memory-state.json
.zzcode/sessions/<session-id>/subagents/<agent-id>/transcript.jsonl
```

- `SessionMemoryUpdateWorker` 可以更新当前 session `summary.md`。
- `AutoMemoryExtractionWorker` 对普通总结任务会返回 `no durable memory`，对长期偏好类输入可更新 `.zzcode/memory/MEMORY.md` 和 topic memory。
- 修复后复测主 Agent 写 `tests/1.txt`、子 Agent 写 `tests/2.txt`，两个文件内容均可精确写入目标文本，子 Agent 通过 `write_file` 而不是 `run_shell` 完成写入。

## 建议执行顺序

1. 建立 `src/zzcode/subagents/` 基础包。
2. 实现 `SubagentDefinition` 和内置 `general-purpose`。
3. 实现 markdown loader。
4. 实现 `SubagentContext` 和 sidechain transcript。
5. 实现用户子 Agent runner。
6. 注册 `agent` 工具。
7. 补用户子 Agent 单元测试。
8. 实现 `ForkedAgentRunner`。
9. 实现 `RestrictedToolExecutor`。
10. 实现 `SessionMemoryUpdateWorker`。
11. 实现 `AutoMemoryExtractionWorker`。
12. 接入 `server.py` turn finished 和 compact 前触发。
13. 补系统子 Agent 测试。
14. 回填第二阶段文档中关于 memory 差异的完成状态。

## 当前进度

截至当前状态，第三阶段第一版主链已完成：

- [x] 建立 `src/zzcode/subagents/` 基础包。
- [x] 实现 `SubagentDefinition` 和内置 `general-purpose`。
- [x] 实现 markdown loader，支持 `~/.zzcode/agents/*.md` 和 `.zzcode/agents/*.md`。
- [x] 实现 `SubagentContext` 和 sidechain transcript。
- [x] 实现同步 `UserSubagentRunner`。
- [x] 注册主 Agent 可调用的 `agent` 工具。
- [x] 补用户子 Agent 单元测试。
- [x] 手动验证真实对话中的 `agent[...]` 调用。
- [x] 实现系统子 Agent 的 `ForkedAgentRunner`。
- [x] 实现 `RestrictedToolExecutor`。
- [x] 实现 `SessionMemoryUpdateWorker`。
- [x] 实现 `AutoMemoryExtractionWorker`。
- [x] 接入 `server.py` turn finished 系统子 Agent 调度。
- [x] 接入 compact 前 session memory 强制更新。
- [x] 对齐 Claude general-purpose，允许通用子 Agent 使用当前内置文件写工具。
- [x] 加强文本 ReAct action 解析，拒绝 `</think>` 或第二个 Action 等尾随文本污染工具参数。

已通过验证：

```text
env PYTHONPYCACHEPREFIX=/tmp/zzcode-pycache python3 -m compileall src tests
env PYTHONPATH=src python3 -m unittest discover -s tests
```

后续建议：

1. 回填第二阶段文档中关于后台 memory worker 差异的完成状态。
2. 进入 Plan 模式设计，降低多步骤任务对单轮自由文本 ReAct 的依赖。
3. 后续把文本 `Action: tool[input]` 升级为结构化 tool call 协议。
