# Phase 08: Structured Subagents

## 阶段目标

第八阶段把 ZzCode 的用户子 Agent 和系统子 Agent 从旧文本 ReAct 循环迁移到结构化 `tool_calls` 主循环。

当前主 Agent 已经使用 `ToolCallAgent + ToolRegistry + ToolRunner`，但 subagents 仍通过 `TextReActAgent` 和旧 `ToolExecutor` 执行。日志里出现的 `Invalid Action format` 就来自这条旧链路：模型没有稳定遵守 `Thought/Action/ToolName[input]` 文本协议，导致后台 memory worker 多次重试并消耗额外 LLM 请求。

本阶段目标不是继续修补旧 ReAct prompt，而是删除运行时代码中的旧文本 ReAct，实现一套统一的结构化 Agent loop。

## Claude Code 参考原则

Claude Code 的主循环不是为 subagent 单独维护另一套 ReAct parser。它的核心执行方式是：

```text
messages
  -> query()/callModel(tools schema)
  -> assistant tool_use blocks
  -> tool orchestration 执行工具
  -> tool_result blocks 回灌
  -> 继续 query loop
```

用户 Agent、forked/system Agent 也走同一个底层 query loop，只是传入不同的：

- system prompt
- tool set
- permission context
- agent id / sidechain transcript
- maxTurns
- parent context 或隔离上下文

ZzCode 对应原则：

1. 主 Agent、用户 subagent、系统 subagent 都使用 `ToolCallAgent`。
2. 工具都来自结构化 `ToolRegistry`，不再使用字符串 `ToolExecutor`。
3. subagent 只是不同的运行上下文和工具集合，不是另一套 Agent 协议。
4. 系统 memory worker 也使用结构化工具调用，不再输出 `Thought/Action`。
5. 旧文本 ReAct 只能留在历史文档或学习归档中，不能继续存在于 `src/` 的运行路径。

## 当前问题

当前仍在运行路径中使用旧 ReAct：

```text
src/zzcode/agent/react_text.py
src/zzcode/tools/executor.py
src/zzcode/subagents/user_runner.py
src/zzcode/subagents/forked_runner.py
src/zzcode/subagents/restricted_tool_executor.py
src/zzcode/subagents/system.py
src/zzcode/subagents/tool.py
```

主要风险：

- 模型容易输出不合法的 `Action` 文本，导致 `Invalid Action format`。
- 主 Agent 和 subagent 的工具协议不一致。
- 权限、路径限制、上下文预算、max turns、日志和 transcript 逻辑需要维护两套。
- 后台系统 Agent 可能在用户任务完成后继续多次请求 LLM。
- 后续 MCP、Plan Mode、Memory compact 会被旧工具层拖住。

## 目标架构

第八阶段后的结构：

```text
src/zzcode/
├── agent/
│   ├── context_budget.py
│   └── tool_call_agent.py
├── subagents/
│   ├── definition.py
│   ├── structured_runner.py
│   ├── restricted_tool_registry.py
│   ├── system.py
│   └── transcript.py
├── tools/
│   ├── base.py
│   ├── registry.py
│   ├── runner.py
│   ├── results.py
│   ├── builtin.py
│   └── local/
│       └── agent.py
└── llm/
    └── client.py
```

删除或移出运行路径：

```text
src/zzcode/agent/react_text.py
src/zzcode/tools/executor.py
src/zzcode/subagents/forked_runner.py
src/zzcode/subagents/user_runner.py
src/zzcode/subagents/restricted_tool_executor.py
src/zzcode/subagents/tool.py
src/zzcode/legacy/react_tools.py
```

如果需要保留学习材料，移动到：

```text
learning/legacy-react/
```

或只保留在 docs 中。

## 核心模块

### StructuredSubagentRunner

新增：

```text
src/zzcode/subagents/structured_runner.py
```

职责：

```text
StructuredSubagentRunner
  -> 创建 subagent context
  -> 创建 sidechain transcript
  -> 构建专属 system prompt
  -> 构建受限 ToolRegistry
  -> 创建 ToolCallAgent
  -> 执行 prompt
  -> 返回 StructuredSubagentResult
```

建议结果类型：

```text
StructuredSubagentResult
  ok: bool
  agent_id: str
  subagent_name: str
  result: str | None
  transcript_path: str
  error: str | None
```

运行参数：

```text
definition: SubagentDefinition | None
name: str
prompt: str
description: str | None
session_context: str
tool_registry: ToolRegistry
max_turns: int
system_prompt: str
agent_id: str | None
source: user | system
```

用户 subagent 和系统 subagent 可以共用同一个 runner。

### RestrictedToolRegistry

新增：

```text
src/zzcode/subagents/restricted_tool_registry.py
```

职责：

```text
build_restricted_tool_registry(
    base_registry: ToolRegistry,
    allow_tools: set[str] | None,
    disallowed_tools: set[str],
    project_root: Path,
    allow_read_paths: list[Path] | None,
    allow_write_paths: list[Path] | None,
) -> ToolRegistry
```

实现方式：

- 不复制工具逻辑。
- 用 `RestrictedToolWrapper` 包装原结构化 `Tool`。
- `name`、`description`、`input_schema`、展示字段透传。
- `validate_input()` 先调用原工具校验。
- `check_permission()` 先检查路径限制，再调用原工具权限判断。
- `call()` 先检查路径限制，再调用原工具。

路径检查基于 JSON 参数，不再解析字符串：

```text
read_file      args["path"]
list_files     args["path"]
glob/grep      args["path"] 或 "."
write_file     args["path"]
edit_file      args["path"]
append_file    args["path"]
run_shell      系统 memory worker 默认不允许
```

系统 worker 的写入边界：

```text
.zzcode/sessions/<session-id>/**
.zzcode/memory/**
```

### 结构化 AgentTool

新增或迁移：

```text
src/zzcode/tools/local/agent.py
```

结构化 schema：

```json
{
  "type": "object",
  "properties": {
    "subagent_type": {"type": "string"},
    "description": {"type": "string"},
    "prompt": {"type": "string"}
  },
  "required": ["prompt"],
  "additionalProperties": false
}
```

执行逻辑：

```text
AgentTool.call()
  -> load_subagent_definitions()
  -> 找到 active subagent definition
  -> StructuredSubagentRunner.run()
  -> 返回 result 和 transcript path
```

主 Agent 看到的是普通结构化工具，不再有特殊字符串协议：

```json
{
  "subagent_type": "general-purpose",
  "description": "检查工具层职责",
  "prompt": "阅读 src/zzcode/tools 并总结结构"
}
```

### 系统 memory workers

`SessionMemoryUpdateWorker` 和 `AutoMemoryExtractionWorker` 改为结构化 runner。

建议工具集：

```text
session-memory-updater:
  read_file
  write_file
  edit_file
  append_file

auto-memory-extraction:
  read_file
  write_file
  edit_file
  append_file
  glob
  grep
```

系统 worker 的 system prompt 要明确要求：

- 必须通过结构化工具更新文件。
- 不输出 `Thought/Action`。
- 如果无需更新，直接最终回答说明 skipped。
- 不写入长期 memory，除非确实发现用户偏好、项目事实、反馈或可复用参考。

## 迁移步骤

### Step 01：新增 RestrictedToolRegistry

实现结构化工具过滤和路径限制。

验收：

- allow list 生效。
- disallow list 生效。
- 越权读取被拒绝。
- 越权写入被拒绝。
- 被允许工具仍保留原 schema 和权限判断。

### Step 02：新增 StructuredSubagentRunner

用 `ToolCallAgent` 执行一个隔离子 Agent。

验收：

- 子 Agent 能通过 fake `ChatClient` 调用结构化工具并返回 final answer。
- sidechain transcript 记录 user、tool use、tool result、assistant final。
- `max_turns` 和 context budget 仍生效。

### Step 03：迁移用户 subagent

用 `StructuredSubagentRunner` 替代 `UserSubagentRunner`。

验收：

- `general-purpose` 子 Agent 可被调用。
- `SubagentDefinition.tools` 控制工具集合。
- `disallowed_tools` 生效。
- 用户权限仍能通过主会话 permission bridge 确认。

### Step 04：迁移 AgentTool

把旧字符串 `agent` 工具迁为结构化 `Tool`，注册到 `ToolRegistry`。

验收：

- 主 Agent 能以结构化 `tool_calls` 调用子 Agent。
- 返回内容包含 `agent_id`、`subagent_name`、`result`、`transcript_path`。
- 不再出现 `agent[prompt]` 或 `subagent_type|||description|||prompt`。

### Step 05：迁移系统 memory workers

把 `SessionMemoryUpdateWorker` 和 `AutoMemoryExtractionWorker` 改为结构化 runner。

验收：

- turn finished 后后台任务仍能更新 session memory。
- auto memory 提取仍能更新 `.zzcode/memory/`。
- compact 前强制刷新 session memory 仍可运行。
- 日志里不再出现 `Invalid Action format`。

### Step 06：删除旧运行路径

删除旧文件和引用：

```text
TextReActAgent
ToolExecutor
RestrictedToolExecutor
ForkedAgentRunner
UserSubagentRunner
legacy/react_tools.py
ThinkClient
ZzCodeLLM.think()
```

验收：

```text
rg "TextReActAgent|react_text|ToolExecutor|RestrictedToolExecutor|ThinkClient" src tests
```

应该无结果，或只剩命名迁移说明中允许的历史文档。

### Step 07：更新文档和手动验收

删除旧 parser 测试改动。本阶段当前按用户约定不新增测试文件，先通过前端流程和 debug 日志验收结构化 subagent 链路。

手动必测场景：

- 用户 subagent 成功调用结构化工具。
- 系统 subagent 成功更新 session memory。
- auto memory worker skipped 时直接 final answer。
- 路径越权被拒绝。
- 权限拒绝后停止。
- 连续工具失败保护生效。
- context budget 阻断生效。
- sidechain transcript 可回放。

## 删除标准

本阶段完成后，运行时代码中不应存在：

```text
Thought:
Action:
ToolName[input]
TextReActAgent
ToolExecutor
ThinkClient
```

允许在历史 docs 中出现，但必须标注为旧阶段学习记录。

## 前端和日志验收

手测提示词：

```text
请调用 general-purpose 子 Agent 检查 src/zzcode/tools 目录，要求它只总结工具注册和执行链路。
```

```text
请完成一个普通代码阅读任务，然后观察后台 system agents 是否更新 session memory。
```

期望日志：

```text
agent run start ... max_turns=...
context budget step=...
tool call start ... name=agent
tool call end ... name=agent ok=True
system-agents background finished ...
```

不应再出现：

```text
Invalid Action format
No valid Action found
Thought:
Action:
```

## 风险和处理

- 子 Agent 工具池迁移会影响安全边界：必须先完成 `RestrictedToolRegistry` 测试。
- 系统 worker prompt 需要重写：旧 prompt 可能还在要求 `Thought/Action`，迁移时必须清理。
- 旧测试数量较多：不要为了保留测试而保留旧运行路径，应重写为结构化行为测试。
- 删除 `ThinkClient` 会影响少量 helper：统一改为 `ChatClient.chat(messages, tools=None)`。

## 执行进度

- [x] 新增 `RestrictedToolRegistry`，用结构化工具 wrapper 实现工具名和路径限制。
- [x] 新增 `StructuredSubagentRunner`，用户子 Agent 和系统子 Agent 共用 `ToolCallAgent`。
- [x] 迁移 `SessionMemoryUpdateWorker` 和 `AutoMemoryExtractionWorker` 到结构化 tool call。
- [x] 新增结构化 `AgentTool` 并注册到 CLI 与 JSON Lines server。
- [x] 删除运行路径中的旧 `react_text.py`、`ToolExecutor`、forked/user runner 和旧 subagent 字符串工具。
- [x] 删除本轮新增测试改动，改用前端和 debug 日志验收。
- [ ] 前端实际运行验证 sidechain transcript、system agents 和权限流程。

## 完成定义

第八阶段完成时：

1. 主 Agent、用户 subagent、系统 subagent 全部使用 `ToolCallAgent`。
2. 所有运行时工具调用都经过 `ToolRegistry` 和 `ToolRunner`。
3. 后台系统 Agent 不再产生 `Invalid Action format`。
4. 旧文本 ReAct 和旧字符串工具层从 `src/` 删除或移出运行路径。
5. README 和相关 phase 文档说明当前架构已统一为结构化 tool-call loop。
