# 第三阶段 Claude Code 子 Agent 实现参考

本文档用于记录 Claude Code 子 Agent 的关键实现，后续实现 ZzCode 第三阶段时优先参考本文档，避免每一步重复读取 Claude 源码。

## 关键源码位置

Claude Code 子 Agent 主要对应这些文件：

```text
src/tools/AgentTool/AgentTool.tsx
src/tools/AgentTool/runAgent.ts
src/tools/AgentTool/loadAgentsDir.ts
src/tools/AgentTool/agentMemory.ts
src/utils/forkedAgent.ts
src/utils/agentContext.ts
src/tasks/LocalAgentTask/LocalAgentTask.tsx
```

## 总体框架

Claude 子 Agent 分两类：

1. 用户可调用子 Agent：通过 `AgentTool` 启动，用于主 Agent 委托任务。
2. 系统 forked Agent：通过 `runForkedAgent` 启动，用于 memory、compact、summary 等后台维护任务。

核心链路：

```text
AgentTool
-> 选择 AgentDefinition
-> 构建子 Agent system prompt
-> 重建子 Agent 工具池
-> 创建 SubagentContext
-> runAgent/query loop
-> sidechain transcript
-> 返回 AgentToolResult
```

系统子 Agent 链路：

```text
runForkedAgent
-> cache-safe parent context
-> createSubagentContext
-> restricted tools
-> query loop
-> sidechain transcript
-> 返回 messages/usage
```

## AgentTool

`AgentTool` 是主 Agent 可调用的工具。

输入核心字段：

```text
description
prompt
subagent_type
model
run_in_background
```

执行过程：

1. 读取输入参数。
2. 根据 `subagent_type` 选择 agent 定义。
3. 未指定类型时走默认 general-purpose 或 fork path。
4. 检查 agent 是否存在。
5. 检查权限规则是否禁用该 agent。
6. 检查 MCP 依赖是否满足。
7. 构建子 Agent system prompt。
8. 根据 agent 定义创建工具池。
9. 创建 agentId。
10. 根据同步/异步分支运行。
11. 记录 sidechain transcript。
12. 汇总结果返回主 Agent。

## AgentDefinition

Claude 的 agent 定义来源：

```text
built-in
plugin
user settings
project settings
policy settings
flag settings
```

关键字段：

```text
agentType
whenToUse
tools
disallowedTools
skills
mcpServers
hooks
color
model
effort
permissionMode
maxTurns
background
memory
isolation
```

合并规则：

```text
built-in
-> plugin
-> user
-> project
-> flag
-> managed/policy
```

同名 agent 后加载的覆盖先加载的。

ZzCode 第三阶段第一版对应字段：

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
source
```

## runAgent

`runAgent` 是普通用户子 Agent 的执行循环。

关键职责：

1. 创建独立 agentId。
2. 构建初始 messages。
3. 获取 user context/system context。
4. 根据 agent 定义处理权限模式。
5. 解析 agent 工具列表。
6. 构建 agent system prompt。
7. 创建子 Agent 上下文。
8. 记录初始 sidechain transcript。
9. 调用 `query()` 循环。
10. 每条 recordable message 写入 sidechain transcript。
11. 完成后清理 MCP、hooks、file cache、todos、后台 shell。

ZzCode 第三阶段第一版对应：

```text
UserSubagentRunner
-> SubagentContext
-> SidechainTranscriptRecorder
-> TextReActAgent
```

## createSubagentContext

Claude 会复制或隔离父上下文中的状态。

隔离内容：

```text
readFileState
nestedMemoryAttachmentTriggers
loadedNestedMemoryPaths
toolDecisions
contentReplacementState
abortController
messages
agentId
agentType
queryTracking
```

默认子 Agent 不能直接控制父 UI 和父状态。

ZzCode 第三阶段第一版对应：

```text
SubagentContext
agent_id
parent_session_id
subagent_name
agent_dir
transcript_path
metadata_path
```

runner 层继续保持：

```text
独立 history
独立 ToolExecutor
独立 transcript
独立 renderer
```

## sidechain transcript

Claude 子 Agent transcript 与主会话分开。

用途：

1. 查看子 Agent 做了什么。
2. 后台 agent 恢复。
3. compact 和 summary 使用。
4. 异步任务输出文件关联。

ZzCode 路径：

```text
.zzcode/sessions/<session-id>/subagents/<agent-id>/metadata.json
.zzcode/sessions/<session-id>/subagents/<agent-id>/transcript.jsonl
```

ZzCode 事件字段：

```text
type
eventId
parentEventId
sequence
sessionId
agentId
parentSessionId
subagentName
createdAt
```

## 工具权限

Claude 子 Agent 会重新组装工具池：

1. agent 定义可以指定 `tools`。
2. agent 定义可以指定 `disallowedTools`。
3. agent 可以指定 `permissionMode`。
4. 异步 agent 默认不能弹权限 UI。
5. 系统 forked agent 使用专门的 `canUseTool` 限制。

ZzCode 第三阶段第一版规则：

1. `SubagentDefinition.tools` 控制允许工具。
2. `disallowed_tools` 从工具池移除。
3. 写文件、shell 仍走主权限系统。
4. memory/session memory 自动允许规则继续生效。
5. 系统子 Agent 使用 `RestrictedToolExecutor` 做工具名和路径限制。

## runForkedAgent

Claude 的 `runForkedAgent` 用于内部系统任务。

典型用途：

```text
Session memory updater
Auto memory extraction
Compact summary
Prompt suggestion
```

关键行为：

1. 接收 parent cache-safe params。
2. 创建隔离上下文。
3. 使用专用 prompt。
4. 使用受限工具权限。
5. 可选写 sidechain transcript。
6. 返回 messages 和 usage。

ZzCode 第三阶段第一版对应：

```text
ForkedAgentRunner
RestrictedToolExecutor
SessionMemoryUpdateWorker
AutoMemoryExtractionWorker
SystemAgentScheduler
```

`CompactSummaryWorker` 第一版暂未单独实现；当前 compact 前先通过 `SessionMemoryUpdateWorker(force=True)` 强制刷新当前 session memory。

## 暂缓实现

Claude 有但 ZzCode 第三阶段第一版先不做：

```text
后台异步任务 UI
foreground 转 background
worktree isolation
remote agent
teammate / multi-agent team
SendMessage
MCP per-agent 配置
skills 预加载
SubagentStart/SubagentStop hooks
agent memory snapshot
prompt cache 优化
token usage 统计
```

这些能力等用户子 Agent 和系统子 Agent 主链跑通后再补。

## 后续实现时的简化沟通规则

后续每一步回答只保留：

1. 本步目标。
2. 参考 Claude 的关键点。
3. Plan。
4. 实际改动。
5. 验证结果。
6. 下一步。

不再重复展开 Claude 源码细节，除非发现当前文档缺失或用户明确要求重新核对源码。
