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

## Claude Code 流式与进度参考

本节只参考 Claude Code 的关键主链路，不照搬完整实现。

关键文件：

```text
claude-code-sourcemap/restored-src/src/query.ts
claude-code-sourcemap/restored-src/src/QueryEngine.ts
claude-code-sourcemap/restored-src/src/services/tools/StreamingToolExecutor.ts
claude-code-sourcemap/restored-src/src/remote/sdkMessageAdapter.ts
```

Claude 的模式：

1. `query()` / `queryLoop()` 是 `AsyncGenerator`，主循环不等完整回合结束，而是持续 `yield`：
   - `stream_request_start`
   - `stream_event`
   - assistant message
   - tool result message
   - tombstone / error / max turns 等控制消息
2. 模型调用通过 streaming 接口返回增量事件；`QueryEngine` 再把 `stream_event` 转为 SDK / remote 前端可消费事件。
3. tool use 是否继续循环不依赖 `stop_reason`，而是在 streaming 过程中观察是否出现 `tool_use` block；只要有 tool_use，就执行工具并继续下一轮。
4. Claude 有 `StreamingToolExecutor`：tool_use block 一到就可以进入工具队列，支持并发安全判断、顺序结果、progress message、abort、fallback 后 tombstone 清理。
5. subagent / sidechain 不是另一套协议，而是同一个 query loop 的不同 `agentId`、tool set、permission context 和 transcript 位置。

ZzCode 暂不直接实现 Claude 的完整 `StreamingToolExecutor`，因为它会引入较重的并发、回滚、顺序和中断处理。第八阶段先借鉴更直接有效的部分：

- 主循环和协议支持增量事件。
- 子 Agent 内部进度透出到前端。
- final answer 支持文本 delta 流式输出。
- 工具仍在完整 tool_call 到达后执行，暂不做边流边执行工具。

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

### 子 Agent 可见进度和结果压缩

当前前端测试暴露的问题：

```text
主回合耗时约 104s
子 Agent 工具调用耗时约 73s
工具本身多为 1-3ms，主要慢在 LLM 请求
子 Agent 最后一轮输入约 74k chars，最终输出约 8k chars
主 Agent 还要再花约 14s 总结子 Agent 结果
```

需要补两类能力：

1. 子 Agent 进度透出
   `StructuredSubagentRunner` 不能只用 `SilentRenderer`。应支持把子 Agent 的 `ToolUse`、`ToolResult`、`SystemNotice` 转成前端可识别的子事件，例如：

   ```json
   {"type": "subagent_start", "agentId": "...", "name": "general-purpose", "description": "..."}
   {"type": "subagent_tool_use", "agentId": "...", "name": "read_file", "input": {...}}
   {"type": "subagent_tool_result", "agentId": "...", "name": "read_file", "ok": true, "outputPreview": "..."}
   {"type": "subagent_done", "agentId": "...", "ok": true, "transcriptPath": "..."}
   ```

   这样即使子 Agent 运行几十秒，前端也能看到它正在读目录、读文件、总结，而不是只看到父级 `agent` 工具长时间 pending。

2. 子 Agent 返回给主 Agent 的结果压缩
   `AgentTool` 不应无条件把完整 8k+ 字结果塞回主 Agent。建议增加：

   ```text
   max_result_chars 默认 3000-5000
   返回 result_excerpt + transcript_path
   超长结果提示主 Agent 需要细节时读取 sidechain transcript
   ```

   同时强化 `general-purpose` prompt：优先 `glob/grep` 定位，不要为了总结目录结构一次性读取过多文件。

### 文本流式输出

当前 `ZzCodeLLM.chat()` 固定使用：

```text
stream=false
response.read()
```

因此前端必须等完整模型响应返回后，才能收到 `assistant_final`。第八阶段追加一个轻量流式目标：

```text
LLM stream
  -> Agent 接收 assistant_delta
  -> JSON Lines 输出 assistant_delta
  -> 最终仍输出 assistant_final
```

建议新增协议事件：

```json
{"type": "assistant_delta", "text": "..."}
{"type": "assistant_final", "text": "..."}
```

子 Agent 可选事件：

```json
{"type": "subagent_assistant_delta", "agentId": "...", "text": "..."}
```

第一版只要求 final answer 文本流式。工具调用阶段可以继续等待完整 response，因为 OpenAI-compatible tool call streaming 会把 `tool_calls.arguments` 分片返回，必须缓冲成完整 JSON 后才能安全执行。

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

### Step 08：子 Agent 进度透出

把 `StructuredSubagentRunner` 的内部 UI 事件转发到父级 renderer。

实现要点：

- 新增 `SubagentEventRenderer` 或在现有 `JsonLineRenderer` 增加子事件方法。
- `AgentTool.call()` 创建 runner 时传入能转发事件的 renderer。
- 系统 memory worker 默认继续静默，避免后台任务干扰用户界面。
- sidechain transcript 继续完整记录，不依赖前端展示事件。

验收：

- 前端调用 `agent` 后，能看到 `subagent_start`。
- 子 Agent 内部 `list_files/read_file/glob/grep` 能显示为子事件。
- 子 Agent 完成后显示 `subagent_done` 和 transcript path。
- 后台 system agents 不刷前端子事件。

### Step 09：子 Agent 结果压缩和搜索优先

降低主 Agent 二次总结成本。

实现要点：

- `AgentTool` 对子 Agent result 做长度限制，默认返回摘要片段和 transcript path。
- 超长结果不丢失，完整内容保留在 sidechain transcript。
- 更新内置 `general-purpose` prompt，要求先用 `glob/grep` 定位，再按需 `read_file`。
- 在 debug log 中打印 `subagent result_chars`、`returned_chars`、`truncated=true/false`。

验收：

- 子 Agent 返回主 Agent 的 tool_result 不再轻易超过 3k-5k chars。
- 同样的“检查 tools 目录”提示词，主回合总耗时明显下降。
- 主 Agent 仍能根据摘要给出准确回答。

### Step 10：final answer 文本流式输出

参考 Claude 的 `stream_event` 思路，但先做轻量版，不做 streaming tool execution。

实现要点：

- `ZzCodeLLM` 增加 `stream_chat()`，解析 OpenAI-compatible SSE。
- 增加 `LLMStreamEvent`，至少支持：
  - `content_delta`
  - `tool_call_delta`
  - `message_done`
  - `error`
- `ToolCallAgent` 增加流式运行路径：
  - 文本 delta 立即渲染 `AssistantDelta`
  - tool_call delta 先缓冲参数
  - tool_call 完整后再执行工具
  - 最终仍追加完整 assistant message，保证下一轮上下文正确
- JSON Lines 协议新增 `assistant_delta`，前端增量拼接。
- 非 stream provider 或解析失败时，自动 fallback 到现有 `chat()`。
- 可通过 `ZZCODE_STREAM=0` 临时关闭流式输出。

验收：

- 无工具调用的回答可以边生成边显示。
- 有工具调用的任务，工具执行前后仍保持现有行为。
- 最终仍输出 `assistant_final`，用于 transcript 和历史记录。
- 解析失败不会破坏当前非流式链路。

暂不实现：

- Claude 风格完整 `StreamingToolExecutor`。
- 工具调用边流边执行。
- 并行工具调度、tombstone 回滚和 streaming fallback 结果清理。

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
subagent_start ...
subagent_tool_use ... name=read_file
subagent_done ...
assistant_delta ...
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
- 流式 tool call 参数是分片 JSON，第一版必须缓冲完整后再执行工具，避免半截参数触发错误工具调用。
- 子 Agent 进度透出要和后台 system agents 区分开，后台任务默认静默。

## 执行进度

- [x] 新增 `RestrictedToolRegistry`，用结构化工具 wrapper 实现工具名和路径限制。
- [x] 新增 `StructuredSubagentRunner`，用户子 Agent 和系统子 Agent 共用 `ToolCallAgent`。
- [x] 迁移 `SessionMemoryUpdateWorker` 和 `AutoMemoryExtractionWorker` 到结构化 tool call。
- [x] 新增结构化 `AgentTool` 并注册到 CLI 与 JSON Lines server。
- [x] 删除运行路径中的旧 `react_text.py`、`ToolExecutor`、forked/user runner 和旧 subagent 字符串工具。
- [x] 删除本轮新增测试改动，改用前端和 debug 日志验收。
- [ ] 前端实际运行验证 sidechain transcript、system agents 和权限流程。
- [x] 子 Agent 内部进度透出到前端。
- [x] 子 Agent result 压缩，降低主 Agent 二次总结成本。
- [x] final answer 文本流式输出。

## 完成定义

第八阶段完成时：

1. 主 Agent、用户 subagent、系统 subagent 全部使用 `ToolCallAgent`。
2. 所有运行时工具调用都经过 `ToolRegistry` 和 `ToolRunner`。
3. 后台系统 Agent 不再产生 `Invalid Action format`。
4. 旧文本 ReAct 和旧字符串工具层从 `src/` 删除或移出运行路径。
5. 前端能看到子 Agent 进度，不再长时间只显示父级 `agent` pending。
6. final answer 支持流式文本输出，最终仍有完整 `assistant_final`。
7. README 和相关 phase 文档说明当前架构已统一为结构化 tool-call loop。
