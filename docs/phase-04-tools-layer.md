# 第四阶段：结构化工具层方案

## 阶段目标

第四阶段把 ZzCode 的工具层从文本 ReAct demo 升级为 Claude Code 风格的结构化工具运行时。

本阶段不保留旧的工具实现方式。也就是说，原来的：

```text
ToolName[input] -> Callable[[str], str] -> Observation 字符串
```

要被替换为：

```text
tool_call JSON 参数
  -> Tool 对象
  -> schema 校验
  -> 权限判断
  -> Tool.call()
  -> ToolResult
  -> tool_result 回灌
```

这一阶段的重点不是增加更多工具，而是把工具抽象、工具注册、工具执行、权限接口和模型回灌链路打稳。

## 验收标准

完成第四阶段时，应满足：

1. 本地工具不再接收单个字符串参数，而是接收结构化 JSON 参数。
2. 工具定义包含名称、描述、参数 schema、输出处理、权限 metadata 和执行函数。
3. Agent 主链路支持 OpenAI-compatible `tool_calls`。
4. 工具结果通过 `tool_call_id` 与模型请求对应。
5. 文件工具和 shell 工具迁移到新工具层。
6. 权限确认基于结构化工具调用，而不是字符串 Action。
7. React + Ink 前端仍能显示工具调用和工具结果。
8. 旧文本 ReAct 工具协议从主链路移除。
9. 测试覆盖工具 schema、执行、权限拒绝、未知工具、工具异常和 tool result 回灌。

## 暂不实现

本阶段暂不做：

- MCP server 接入。
- MCP tools 动态发现。
- Plan Mode。
- ToolSearch / deferred tools。
- hooks 系统。
- auto mode classifier。
- 复杂 sandbox。
- 大结果持久化。
- 多工具并发执行。
- 非文本文件、图片、PDF、notebook 的完整读取。

这些能力都可以在结构化工具层稳定后继续叠加。

## Claude Code 参考原则

参考文档：

- `docs/phase-04-claude-tools-reference.md`

本阶段只吸收 Claude Code 工具层的核心思路：

1. 工具是标准对象，不是普通函数。
2. 工具有 schema、权限、执行、展示和结果映射能力。
3. Agent 不关心工具来自哪里，只通过统一工具注册表查找工具。
4. 工具执行前先做 schema 校验，再做权限判断，再执行。
5. 工具结果要保留结构，并映射回模型 API 需要的 `tool_result`。
6. MCP 未来应作为一种工具来源接入，而不是 Agent 主循环里的特殊分支。

不照搬 Claude 的复杂部分：

- React 组件级工具渲染。
- hooks。
- classifier。
- 大量 feature flag。
- 多 transport MCP。
- 复杂遥测和缓存。

## 目标架构

第四阶段后的核心结构：

```text
src/zzcode/
├── agent/
│   └── tool_call_agent.py
├── llm/
│   └── client.py
├── tools/
│   ├── base.py
│   ├── registry.py
│   ├── runner.py
│   ├── results.py
│   ├── local/
│   │   ├── filesystem.py
│   │   ├── search.py
│   │   └── shell.py
│   └── builtin.py
├── legacy/
│   └── react_tools.py
└── protocol/
    └── events.py
```

模块职责：

```text
base.py          定义 Tool、ToolContext、ToolCall、权限结果和权限请求等核心类型
registry.py      保存工具集合，生成模型 API tools schema
runner.py        工具执行管线：查找、校验、权限、执行、异常转换
results.py       工具结果到模型消息和 UI 事件的转换
local/           本地文件、搜索和 shell 工具实现
builtin.py       组装本阶段默认工具集合
tool_call_agent.py  新的结构化 tool call Agent 主循环
legacy/          临时保留文本 ReAct 工具构建，供 subagents 旧链路使用
```

## 核心数据模型

### Tool

ZzCode 的 `Tool` 应是一个协议或基类，表达工具完整能力。

建议字段：

```text
name              模型调用名
description       给模型看的工具说明
input_schema      JSON Schema object
display_name      UI 展示名
is_read_only      是否只读
is_destructive    是否可能修改文件或执行危险动作
requires_approval 是否默认需要用户确认
```

建议方法：

```text
validate_input(args) -> ToolValidationResult
check_permission(args, context) -> ToolPermissionResult
call(args, context) -> ToolResult
to_openai_tool() -> dict
```

`validate_input()` 做参数形状和基础值校验。

`check_permission()` 做工具自己的权限判断，例如写文件、执行 shell 默认需要确认。

`call()` 执行真实逻辑。

`to_openai_tool()` 生成 OpenAI-compatible tools schema。

### ToolContext

工具执行时不要只传项目路径，而是传运行环境对象。

建议字段：

```text
project_root
session_id
permission_checker
session_context
abort_signal
metadata
```

本阶段保持轻量，不需要把所有 Agent 状态都塞进去。

后续 MCP、Plan、Memory、Subagents 都可以继续扩展这个 context。

### ToolCall

内部工具调用对象：

```text
id        模型返回的 tool_call_id
name      工具名
args      JSON object 参数
raw       原始 tool call
```

### ToolResult

内部工具结果对象：

```text
tool_call_id
tool_name
ok
content
data
error
metadata
```

说明：

- `content` 是给模型看的文本内容。
- `data` 是内部结构化数据，方便 UI 或测试使用。
- `error` 是错误说明。
- `metadata` 放路径、exit_code、是否截断等信息。

### ToolPermissionResult

权限结果：

```text
allow
deny
ask
```

建议结构：

```text
behavior    allow | deny | ask
message     给用户或模型看的说明
reason      机器可读原因
updated_args 可选，权限层修正后的参数
```

第四阶段先支持这三个行为，不做持久 allow/deny 规则。

## 工具注册表

`ToolRegistry` 只负责管理工具集合。

职责：

```text
register(tool)
get(name)
list()
to_openai_tools()
```

要求：

- 工具名必须唯一。
- 未知工具返回结构化错误。
- OpenAI tools schema 由注册表统一生成。
- 未来 MCP 工具也注册到同一个 registry。

本阶段不再提供 `get_available_tools()` 这种 ReAct 文本列表作为主接口。

## 工具执行管线

工具执行统一经过 `ToolRunner`。

流程：

```text
1. 接收 ToolCall
2. 按 name 查找 Tool
3. 找不到则返回 ok=false 的 ToolResult
4. 校验 args 是否是 object
5. 用 input_schema 做基础校验
6. 调用 tool.validate_input()
7. 调用 tool.check_permission()
8. ask 时调用 permission_checker
9. deny 时返回拒绝结果
10. allow 时执行 tool.call()
11. 捕获异常并转成 ToolResult
12. 返回 ToolResult
```

这个管线对应 Claude 的：

```text
findToolByName
inputSchema.parse
validateInput
checkPermissions / canUseTool
tool.call
mapToolResultToToolResultBlockParam
```

ZzCode 当前阶段可以比 Claude 简化，但顺序要保持。

## Agent 主循环

新增结构化 Agent：

```text
src/zzcode/agent/tool_call_agent.py
```

主循环：

```text
messages = system + memory + user

while step < max_steps:
    response = llm.chat(messages, tools=registry.to_openai_tools())

    if response has final text and no tool_calls:
        return final answer

    append assistant message with tool_calls

    for tool_call in response.tool_calls:
        result = runner.run(tool_call)
        append tool result message with tool_call_id

    continue
```

第四阶段后，`TextReActAgent` 不再作为主链路使用。可以临时保留文件以便回看学习历史，但 CLI / JSONL 后端应切到新的 `ToolCallAgent`。

如果删除旧 Agent 影响太大，也可以先保留文件但不再引用。

## LLM Provider 调整

当前 `ZzCodeLLM.think()` 面向纯文本 ReAct。

第四阶段需要增加结构化接口：

```text
chat(messages, tools=None) -> LLMResponse
```

`LLMResponse` 至少包含：

```text
content
tool_calls
raw
```

`tool_calls` 标准化为内部结构：

```text
id
name
arguments
```

OpenAI-compatible 返回中的 function call 参数通常是 JSON 字符串，Provider 层应负责解析成 dict；解析失败则生成可回灌的工具参数错误。

## 本地工具迁移

本阶段迁移现有工具，并补齐 Claude Code 风格本地文件定位所需的只读搜索工具。

### list_files

参数：

```json
{
  "path": "."
}
```

属性：

```text
read_only = true
requires_approval = false
```

### read_file

参数：

```json
{
  "path": "README.md",
  "offset": 1,
  "limit": 200
}
```

本阶段可以先支持 `path`，`offset/limit` 可作为可选增强。

属性：

```text
read_only = true
requires_approval = false
```

说明：

- `read_file` 适合路径已知时读取文件。
- 如果路径不存在，结果会提示可使用 `glob` 搜索匹配文件。
- 当用户只提供文件名或部分路径时，正常链路应先用 `glob` 定位，再读取精确路径。

### glob

参数：

```json
{
  "pattern": "**/1.txt",
  "path": ".",
  "limit": 100
}
```

属性：

```text
read_only = true
requires_approval = false
```

说明：

- 用于按路径模式查找项目内文件。
- 搜索边界严格限制在 `ToolContext.project_root` 内。
- `path` 会通过 `resolve_project_path()` 校验，`..` 或项目外绝对路径会被拒绝。
- 默认跳过 `.git`、`node_modules`、`.venv`、`__pycache__`、`dist`、`build`、`target` 等目录。
- 结果受 `limit` 和最大扫描项数限制，避免大项目里输出过大。

### grep

参数：

```json
{
  "pattern": "keyword",
  "path": ".",
  "include": "**/*.py",
  "limit": 100
}
```

属性：

```text
read_only = true
requires_approval = false
```

说明：

- 用于在项目内文本文件中搜索内容。
- 搜索边界和跳过目录策略与 `glob` 一致。
- 大文件、二进制文件或非 UTF-8 文件会跳过。
- 返回 `path:line:snippet` 形式的结果，并保留结构化 matches 数据。

### write_file

参数：

```json
{
  "path": "notes.md",
  "content": "..."
}
```

属性：

```text
read_only = false
is_destructive = true
requires_approval = true
```

### edit_file

参数：

```json
{
  "path": "README.md",
  "old_text": "...",
  "new_text": "..."
}
```

属性：

```text
read_only = false
is_destructive = true
requires_approval = true
```

### append_file

参数：

```json
{
  "path": "notes.md",
  "content": "..."
}
```

属性：

```text
read_only = false
is_destructive = true
requires_approval = true
```

### run_shell

参数：

```json
{
  "command": "pytest",
  "timeout_seconds": 30
}
```

属性：

```text
read_only = false
is_destructive = true
requires_approval = true
```

本阶段继续保留危险命令快速拒绝，但权限确认改成基于结构化参数。

### Calculator

建议移除主链路。

如果还需要测试工具调用，可以改成测试专用工具，不进入默认工具集合。

### 当前默认结构化工具集合

第四阶段完成后，主链路默认注册：

```text
list_files
glob
grep
read_file
write_file
edit_file
append_file
run_shell
```

其中 `Calculator` 和 `agent` 不进入默认结构化工具集合。旧文本 ReAct 工具集合通过 `zzcode.legacy.build_legacy_tools()` 临时保留，供 subagents 旧链路和阶段回顾使用。

## 权限设计

第四阶段权限先做基础版。

默认规则：

```text
只读工具      默认 allow
写文件工具    默认 ask
shell 工具    默认 ask
未知工具      deny
路径越界      deny
危险命令      deny
```

用户拒绝策略：

- 用户拒绝 destructive 工具后，当前 turn 立即停止。
- Agent 不再继续把拒绝结果交给模型寻找替代工具，避免从 `write_file` 改用 `edit_file` 或 `run_shell` 绕过拒绝。
- 拒绝语义仍只作用于当前 turn；持久 allow/deny 规则留到后续权限系统阶段。

权限确认请求应包含：

```text
tool_call_id
tool_name
display_name
args
summary
is_destructive
```

前端确认后返回 allow / deny。

本阶段不做：

- always allow。
- always deny。
- session allow。
- 项目配置权限规则。
- classifier。

但数据结构要允许后续扩展。

## UI 和协议事件

现有 JSONL 事件可以继续使用，但输入应从字符串改成结构化对象。

工具调用事件：

```json
{
  "type": "tool_use",
  "id": "call_xxx",
  "name": "read_file",
  "displayName": "Read",
  "input": {
    "path": "README.md"
  }
}
```

工具结果事件：

```json
{
  "type": "tool_result",
  "id": "call_xxx",
  "name": "read_file",
  "ok": true,
  "output": "..."
}
```

前端如果当前只支持字符串展示，可以先把 JSON input 格式化成文本显示，但后端协议应保留 object。

## 与 Memory / Subagents 的关系

Memory 和 Subagents 不作为本阶段重构重点，但要保证不破坏。

要求：

- `build_memory_context()` 仍能注入 Agent messages。
- session notes 和 compact 不依赖旧 Observation 文本格式。
- Subagent 工具如果还依赖旧 `ToolExecutor`，需要同步迁移到新 `Tool`。
- 系统 subagents 使用文件工具时，也走新工具 runner。

如果 subagents 迁移成本较高，本阶段可以先让主 Agent 完成结构化工具层，再单独迁移 subagent 调用入口。但不能长期保留两套工具实现。

## MCP 预留边界

本阶段不实现 MCP，但工具层要为 MCP 留出位置。

预留字段：

```text
source       local | mcp
mcp_info     可选，server_name / tool_name
input_json_schema
```

未来 MCP 接入时只需要：

```text
MCP tools/list
  -> 转成 Tool
  -> registry.register(tool)
```

Agent 和 ToolRunner 不需要知道这个工具来自 MCP 还是本地。

## 分步骤执行计划待办

每完成一个步骤，就把对应方框从 `[ ]` 改成 `[x]`。本清单用于跟踪第四阶段整体进度，下面“实施步骤”保留每一步的详细目标和验收标准。

- [x] Step 01：定义工具核心类型，建立 `Tool` / `ToolContext` / `ToolCall` / `ToolResult` / 权限结果等基础模型。
- [x] Step 02：实现 `ToolRegistry`，支持工具注册、查找、去重和 OpenAI-compatible tools schema 输出。
- [x] Step 03：实现 `ToolRunner`，串起查找、schema 校验、工具校验、权限判断、执行和异常转换。
- [x] Step 04：迁移本地文件工具，让 `list_files` / `read_file` / `write_file` / `edit_file` / `append_file` 使用 JSON 参数。
- [x] Step 05：迁移 shell 工具，让 `run_shell` 使用结构化参数、危险命令拒绝、超时和结构化结果。
- [x] Step 06：扩展 LLM Provider，增加 `chat(messages, tools)` 并标准化 OpenAI-compatible `tool_calls`。
- [x] Step 07：新增 `ToolCallAgent`，实现结构化 tool call 主循环和 `tool_call_id` 结果回灌。
- [x] Step 08：切换 CLI / JSONL 后端，默认使用新 Agent，并让权限桥接和前端事件支持结构化 args。
- [x] Step 09：移除旧文本 ReAct 工具协议主链路，确保默认架构不再依赖 `ToolName[input]`。
- [x] Step 10：补齐第四阶段测试，覆盖 registry、runner、本地工具、shell、Agent 主循环和协议事件。

## 实施步骤

### Step 01：定义工具核心类型

新增：

```text
src/zzcode/tools/base.py
src/zzcode/tools/results.py
```

完成：

- `Tool`
- `ToolContext`
- `ToolCall`
- `ToolResult`
- `ToolPermissionResult`
- 基础 JSON Schema 校验工具

验收：

- 单元测试能构造一个 fake tool 并执行成功。

### Step 02：实现 ToolRegistry

新增：

```text
src/zzcode/tools/registry.py
```

完成：

- 注册工具。
- 按名称查找工具。
- 生成 OpenAI-compatible tools schema。
- 工具名冲突报错。

验收：

- registry 能输出正确 `tools=[{"type":"function",...}]`。

### Step 03：实现 ToolRunner

新增：

```text
src/zzcode/tools/runner.py
```

完成：

- 未知工具错误。
- schema 校验。
- 工具自定义校验。
- 权限判断。
- 用户确认桥接。
- 工具异常转 `ToolResult`。

验收：

- allow / ask / deny 三种路径都有测试。

### Step 04：迁移本地文件工具

新增或重写：

```text
src/zzcode/tools/local/filesystem.py
src/zzcode/tools/local/search.py
src/zzcode/tools/builtin.py
```

完成：

- list_files
- glob
- grep
- read_file
- write_file
- edit_file
- append_file

验收：

- 文件工具全部使用 JSON 参数。
- 路径越界仍被拒绝。
- 写文件和编辑走权限确认。
- 用户给出文件名或部分路径时，可以通过 `glob` 定位候选文件。
- 可以通过 `grep` 按文本内容定位文件。

### Step 05：迁移 shell 工具

新增或重写：

```text
src/zzcode/tools/local/shell.py
```

完成：

- run_shell 使用 `{command, timeout_seconds}`。
- 危险命令拒绝。
- 超时处理。
- stdout / stderr / exit_code 进入结构化结果。

验收：

- 正常命令返回 ok。
- 危险命令返回 deny/error。
- 超时返回 error。

### Step 06：扩展 LLM Provider

修改：

```text
src/zzcode/llm/client.py
```

完成：

- 增加 `chat(messages, tools)`。
- 标准化 tool_calls。
- 保留必要的模型配置。

验收：

- mock response 可返回 tool_calls。
- OpenAI-compatible 返回可解析。

### Step 07：新增 ToolCallAgent

新增：

```text
src/zzcode/agent/tool_call_agent.py
```

完成：

- messages 主循环。
- assistant tool_calls 回灌。
- tool_result message 回灌。
- max_steps 控制。
- UI event 输出。

验收：

- mock LLM 可以完成：read_file -> final answer。
- mock LLM 可以完成：write_file -> permission ask -> tool_result -> final answer。

### Step 08：切换 CLI / JSONL 后端

修改：

```text
src/zzcode/cli/main.py
src/zzcode/protocol/server.py
```

完成：

- 默认使用新 `ToolCallAgent`。
- `build_tool_registry()` 返回 `ToolRegistry`。
- 权限桥接适配结构化 args。
- 前端 tool_use 事件支持 object input。

验收：

- CLI 能正常对话。
- React + Ink 前端能显示工具调用和结果。

### Step 09：移除旧工具主链路

处理：

```text
src/zzcode/tools/executor.py
src/zzcode/agent/react_text.py
```

原则：

- 不再作为默认路径引用。
- 如果测试、阶段回顾或 subagents 临时兼容仍需要教学版，必须显式标记为 legacy。
- 第四阶段完成后，项目主架构不再依赖 `ToolName[input]`。

验收：

- CLI / JSONL 默认入口不再引用 `ToolExecutor`、`TextReActAgent` 或 `ToolName[input]`。
- `build_legacy_tools()` 是 subagents 旧链路的临时边界，后续 subagents 迁移完成后删除。

## 测试计划

重点测试：

```text
tests/test_tools_registry.py
tests/test_tools_runner.py
tests/test_tools_filesystem.py
tests/test_tools_search.py
tests/test_tools_shell.py
tests/test_tool_call_agent.py
tests/test_protocol_tool_events.py
```

覆盖场景：

- 工具注册成功。
- 工具名冲突。
- OpenAI tools schema 生成。
- 未知工具调用。
- 参数缺失。
- 参数类型错误。
- 工具自定义校验失败。
- 只读工具默认 allow。
- 写工具触发 ask。
- 用户拒绝权限。
- 工具执行异常。
- 文件路径越界。
- glob 项目内路径搜索。
- grep 项目内文本搜索。
- 搜索工具跳过重目录并限制结果数量。
- shell 危险命令。
- tool_call_id 正确回灌。
- 多轮 tool call 后 final answer。
- 用户拒绝 destructive 工具后停止当前 turn。

## 风险与取舍

### 风险 1：一次性替换主链路影响较大

工具层会影响 CLI、JSONL、subagents、memory 更新。需要按步骤迁移，并用 mock LLM 测试主循环。

### 风险 2：OpenAI-compatible 差异

不同兼容服务对 `tool_calls` 细节支持不完全一致。Provider 层要做最小标准化，Agent 不直接依赖原始响应结构。

### 风险 3：权限体验退化

原来权限确认只展示字符串。结构化 args 需要生成清晰 summary，否则前端不好读。本阶段至少要为文件和 shell 工具提供可读 summary。

### 风险 4：Subagents 迁移成本

Subagents 已经接入现有 `ToolExecutor`。第四阶段不要长期维护两套工具层；如果无法一次迁完，必须明确临时兼容边界和删除点。

## 完成后的架构状态

第四阶段完成后，ZzCode 的工具层应变为：

```text
Agent Core
  -> ToolRegistry
      -> Local Tool objects
      -> future MCP Tool objects
  -> ToolRunner
      -> schema validation
      -> permission check
      -> execution
      -> ToolResult
  -> LLM Provider
      -> OpenAI-compatible tool_calls
```

这时第五阶段或后续 MCP 阶段就可以把 MCP tools 包装成同样的 `Tool` 对象接入，而不需要再改 Agent 主循环。
