# 第四阶段：Claude Code 工具层参考实现

## 阶段目标

第四阶段先理解工具层，不急着设计 ZzCode 的新实现。

当前文档只做两件事：

1. 说明 ZzCode 现在的工具是如何实现的。
2. 整理 Claude Code sourcemap 中工具层的关键实现位置和架构思路。

暂不实现：

- ZzCode 结构化工具层方案。
- MCP 接入方案。
- Plan Mode 与工具层联动方案。

后续再查 Claude Code 关于工具层的实现时，先看本文档，再按文档里的文件路径定位源码。

## ZzCode 当前工具实现

ZzCode 当前工具层是一个教学版、文本协议驱动的最小实现。

整体链路是：

```text
用户输入
  -> TextReActAgent 组装 prompt
  -> prompt 中写入可用工具说明
  -> LLM 输出 Action: ToolName[input]
  -> Agent 解析 ToolName 和 input
  -> ToolExecutor 按名称找到工具函数
  -> 执行本地函数
  -> 把执行结果作为 Observation 回灌给模型
  -> 模型继续调用工具或 Finish
```

### 工具注册表

核心文件：

- `src/zzcode/tools/executor.py`

当前 `ToolExecutor` 同时承担两个职责：

- 保存工具注册信息。
- 根据工具名执行工具。

每个工具注册成一个 `RegisteredTool`：

```text
name          模型调用时使用的工具名
description   写进 ReAct prompt 的工具说明
func          真正执行的 Python 函数
display_name  UI 展示名
```

工具函数的形态非常简单：

```text
Callable[[str], str]
```

也就是说，当前所有工具都只接收一个字符串参数，并返回一个字符串结果。

### 内置工具

核心文件：

- `src/zzcode/tools/builtin.py`
- `src/zzcode/cli/main.py`

当前内置工具包括：

- `list_files`
- `read_file`
- `write_file`
- `edit_file`
- `append_file`
- `run_shell`
- `Calculator`
- 可选的 `Agent` subagent 工具

这些工具都通过 `register_builtin_tools()` 或 `build_tools()` 注册到同一个 `ToolExecutor`。

文件写入和编辑因为还没有 JSON 参数，所以使用文本分隔符：

```text
write_file[path|||content]
edit_file[path|||old_text|||new_text]
append_file[path|||content]
```

这说明当前工具层还不是结构化参数，而是靠 prompt 约定和字符串解析维持。

### Agent 如何调用工具

核心文件：

- `src/zzcode/agent/react_text.py`

`TextReActAgent` 会把工具说明放进 prompt：

```text
- read_file: 读取项目内文本文件...
- write_file: 写入项目内文本文件...
```

模型必须返回：

```text
Thought: ...
Action: read_file[README.md]
```

Agent 通过正则和括号平衡解析 `Action`，得到：

```text
tool_name = read_file
tool_input = README.md
```

然后调用：

```text
ToolExecutor.execute(tool_name, tool_input)
```

执行结果会追加到当前轮 history：

```text
Action: read_file[README.md]
Observation: 文件内容...
```

下一次请求模型时，history 会再次进入 prompt。

### 权限与安全

核心文件：

- `src/zzcode/tools/safety.py`
- `src/zzcode/protocol/server.py`
- `src/zzcode/agent/react_text.py`

当前安全机制主要有三层：

1. 路径围栏  
   `resolve_project_path()` 会把路径解析到项目根目录内，拒绝访问项目外路径。

2. shell 危险命令拦截  
   `reject_dangerous_command()` 会拒绝 `sudo`、`rm -rf /`、`shutdown`、`curl | sh` 等明显高风险命令。

3. 执行前权限确认钩子  
   `TextReActAgent` 在工具执行前调用 `permission_checker`。JSONL 后端通过 `PermissionBridge` 把确认请求交给前端。

当前权限系统还比较轻：它能在执行前询问用户，但还没有完整的工具权限规则、schema 级别权限、持久 allow/deny、MCP 权限命名空间等能力。

### 当前实现特点

ZzCode 当前工具层适合作为 ReAct 教学闭环：

- 简单直接。
- 容易看懂。
- 能证明模型调用本地工具的流程。

但它还不是正式工具架构：

- 没有结构化 `tool_calls`。
- 没有 JSON Schema 参数。
- 没有统一 `ToolCall` / `ToolResult` 数据模型。
- 工具执行结果只有字符串。
- 工具定义、权限、UI 展示、执行策略还没有分层。
- MCP 还不能作为工具来源接入。

## Claude Code 工具层参考

Claude Code 的工具层不是一个简单函数注册表，而是一套围绕 `Tool` 对象、执行上下文、权限系统和 MCP 工具来源构建的运行时。

本次没有全盘扫描，只按名称和职责定位了关键代码。

主要参考路径：

- `restored-src/src/Tool.ts`
- `restored-src/src/tools.ts`
- `restored-src/src/services/tools/toolExecution.ts`
- `restored-src/src/query.ts`
- `restored-src/src/QueryEngine.ts`
- `restored-src/src/utils/permissions/permissions.ts`
- `restored-src/src/services/mcp/client.ts`
- `restored-src/src/tools/MCPTool/MCPTool.ts`
- `restored-src/src/services/mcp/mcpStringUtils.ts`
- `restored-src/src/services/mcp/types.ts`

### 1. Tool 是标准对象，不是普通函数

核心文件：

- `restored-src/src/Tool.ts`

Claude 的每个工具都是一个 `Tool` 对象。

一个工具对象大体包含这些能力：

```text
name                    工具名
aliases                 兼容旧名称
description()           给模型看的简短说明
prompt()                给模型看的完整工具说明
inputSchema             Zod 参数 schema
inputJSONSchema         MCP 等外部工具可直接提供 JSON Schema
outputSchema            输出 schema
validateInput()         工具自己的输入校验
checkPermissions()      工具自己的权限判断
call()                  真正执行工具
mapToolResult...()      把工具结果转成 API tool_result
renderToolUseMessage()  UI 渲染工具调用
renderToolResult...()   UI 渲染工具结果
isReadOnly()            是否只读
isDestructive()         是否破坏性操作
isConcurrencySafe()     是否可并发
isMcp                   是否 MCP 工具
mcpInfo                 MCP server/tool 原始信息
```

这和 ZzCode 当前 `Callable[[str], str]` 很不一样。Claude 把工具的模型说明、参数结构、执行、权限、UI、并发、安全属性都放进统一对象里。

### 2. buildTool 提供默认行为

核心文件：

- `restored-src/src/Tool.ts`

Claude 使用 `buildTool()` 创建工具对象。

`buildTool()` 会给工具补默认值，例如：

- 默认启用。
- 默认不是并发安全。
- 默认不是只读。
- 默认不是破坏性操作。
- 默认权限行为是 allow。
- 默认 auto classifier 输入为空。
- 默认 user-facing name 使用工具名。

这样每个工具只需要覆盖自己关心的部分，调用方拿到的一定是完整 `Tool`。

### 3. ToolUseContext 是工具运行环境

核心文件：

- `restored-src/src/Tool.ts`

Claude 的工具执行不是只传参数，还会传入 `ToolUseContext`。

这个上下文包含：

- 当前可用工具列表。
- MCP clients。
- MCP resources。
- 命令列表。
- agent 定义。
- 当前消息历史。
- 文件读取缓存。
- AppState 读写函数。
- 权限上下文。
- UI 回调。
- abort controller。
- progress 回调。
- session / agent id。
- token/result 长度统计。
- hooks 和 prompt 请求能力。

可以把 `ToolUseContext` 理解成工具运行时的环境对象。工具通过它访问当前会话状态，而不是依赖全局变量或 CLI 入口直接传参。

### 4. tools.ts 汇总内置工具

核心文件：

- `restored-src/src/tools.ts`

`tools.ts` 是内置工具集合的主要入口。

它导入并组合大量工具，例如：

- `AgentTool`
- `BashTool`
- `FileReadTool`
- `FileEditTool`
- `FileWriteTool`
- `GlobTool`
- `GrepTool`
- `WebFetchTool`
- `WebSearchTool`
- `TodoWriteTool`
- `EnterPlanModeTool`
- `ExitPlanModeV2Tool`
- `ListMcpResourcesTool`
- `ReadMcpResourceTool`
- `ToolSearchTool`

它还负责根据环境和权限过滤工具：

- simple mode 只暴露少量工具。
- deny 规则可以让工具在进入模型上下文前就被过滤。
- REPL mode 下隐藏底层 primitive tools。
- feature flag 控制某些工具是否出现。
- MCP 工具和内置工具最后合并成一个工具池。

关键函数：

```text
getAllBaseTools()
getTools(permissionContext)
filterToolsByDenyRules(...)
assembleToolPool(permissionContext, mcpTools)
```

其中 `assembleToolPool()` 是本地工具和 MCP 工具合并的关键点：

```text
built-in tools
  + allowed MCP tools
  + 去重
  + 排序保证 prompt cache 稳定
```

### 5. 具体工具实现示例：FileReadTool

核心文件：

- `restored-src/src/tools/FileReadTool/FileReadTool.ts`

`FileReadTool` 展示了 Claude 工具的典型结构：

- 用 Zod 定义输入参数：`file_path`、`offset`、`limit`、`pages`。
- 输出是结构化 union，可以是 text、image、notebook、pdf、parts、file_unchanged。
- `isReadOnly()` 返回 true。
- `isConcurrencySafe()` 返回 true。
- `getPath()` 返回文件路径。
- `validateInput()` 做页码、二进制文件、设备文件、deny rule 等校验。
- `checkPermissions()` 调用文件系统权限逻辑。
- `call()` 执行真正读取，并处理缓存、图片、PDF、notebook、token 限制。
- `mapToolResultToToolResultBlockParam()` 把结果转成 API 的 tool_result。

这个例子说明 Claude 的工具不只是“执行函数”，而是包含完整生命周期。

### 6. 工具执行链路

核心文件：

- `restored-src/src/services/tools/toolExecution.ts`
- `restored-src/src/query.ts`
- `restored-src/src/QueryEngine.ts`

Claude 从模型返回的 assistant message 中识别 `tool_use` block。每个 tool_use 里有：

```text
id
name
input
```

工具执行主流程在 `runToolUse()` 和后续函数中完成。

核心顺序是：

```text
1. 根据 tool_use.name 从工具池查找 Tool
2. 如果找不到，返回 is_error 的 tool_result
3. 用 tool.inputSchema 解析 input
4. 调用 tool.validateInput()
5. 执行 PreToolUse hooks
6. 调用 canUseTool / 权限系统
7. 如果权限拒绝，返回 is_error 的 tool_result
8. 调用 tool.call()
9. 调用 tool.mapToolResultToToolResultBlockParam()
10. 把结果作为 user message 的 tool_result 回灌
```

Claude 会维护 `tool_use_id` 和 `tool_result.tool_use_id` 的对应关系。这样模型知道每个工具结果对应哪一次工具调用。

### 7. 权限系统是通用层 + 工具自定义层

核心文件：

- `restored-src/src/utils/permissions/permissions.ts`
- `restored-src/src/Tool.ts`
- 各工具自己的 `checkPermissions()`

Claude 权限不是简单 yes/no。

权限上下文 `ToolPermissionContext` 包含：

- 当前 permission mode。
- always allow rules。
- always deny rules。
- always ask rules。
- 额外工作目录。
- bypass permissions 是否可用。
- auto mode 是否可用。
- plan mode 前的权限模式。
- 后台 agent 是否应避免弹窗。

每次工具执行时：

1. 工具自己的 `checkPermissions()` 可以先判断。
2. 通用权限系统再应用 allow/deny/ask 规则。
3. hooks 可以参与权限决策。
4. auto mode 可以用 classifier 判断。
5. dontAsk / acceptEdits / bypass / plan 等模式会改变行为。
6. headless 或 async agent 没有 UI 时，会走自动拒绝或 hook 决策。

MCP 工具也进入同一套权限系统，只是权限匹配名使用 `mcp__server__tool` 形式，避免和内置工具重名。

### 8. MCP 是工具来源，不是 Agent 特例

核心文件：

- `restored-src/src/services/mcp/client.ts`
- `restored-src/src/tools/MCPTool/MCPTool.ts`
- `restored-src/src/services/mcp/mcpStringUtils.ts`
- `restored-src/src/services/mcp/types.ts`

Claude 把 MCP 工具转换成内部 `Tool` 对象。

基础模板是 `MCPTool`：

- `isMcp: true`
- 默认 name 是 `mcp`
- input schema 允许任意 object
- 输出是字符串
- 默认 `call()` 为空实现
- 默认 `checkPermissions()` 要求权限

真正连接 MCP server 后，`fetchToolsForClient()` 会：

1. 请求 MCP server 的 `tools/list`。
2. 清洗 server 返回的 tool 定义。
3. 为每个 MCP tool 生成内部 Tool。
4. 使用 `mcp__server__tool` 形式生成唯一名称。
5. 保存 `mcpInfo: { serverName, toolName }`。
6. 把 MCP 的 inputSchema 作为 `inputJSONSchema`。
7. 用 MCP annotations 设置只读、破坏性、open world、并发等提示。
8. 覆盖 `call()`，内部调用 MCP `callTool()`。
9. 把 MCP 返回值映射成 Claude 的工具结果。

因此在 Agent 看来，MCP 工具和本地工具最终都是 `Tool`。

### 9. MCP 命名与权限

核心文件：

- `restored-src/src/services/mcp/mcpStringUtils.ts`

Claude 使用统一命名：

```text
mcp__serverName__toolName
```

相关函数：

```text
buildMcpToolName(serverName, toolName)
mcpInfoFromString(toolString)
getToolNameForPermissionCheck(tool)
```

这个设计解决两个问题：

1. 不同 MCP server 可能有同名工具。
2. MCP 工具可能和内置工具同名，例如 `Write`。

权限判断时，如果是 MCP 工具，会使用 fully-qualified name，而不是展示名。这样 `Write` 的本地权限规则不会误伤 MCP 的 `Write`。

### 10. MCP 连接与调用

核心文件：

- `restored-src/src/services/mcp/client.ts`
- `restored-src/src/services/mcp/types.ts`

Claude 支持多种 MCP transport：

- `stdio`
- `sse`
- `http`
- `ws`
- `sdk`
- Claude.ai proxy / IDE 内部 server

连接状态有：

- connected
- failed
- needs-auth
- pending
- disabled

执行 MCP 工具时，Claude 会：

1. 确保 client 仍连接。
2. 调用 MCP `client.callTool()`。
3. 传入工具名、arguments 和 `_meta`。
4. 支持 abort signal。
5. 支持 progress。
6. 支持 timeout。
7. 处理认证错误。
8. 处理 session expired 后重连重试。
9. 处理 MCP elicitation。
10. 对大输出、二进制输出、图片等做存储或转换。

### 11. Claude 工具层的核心理解

Claude 的工具层可以概括成：

```text
Model tool_use
  -> Tool lookup
  -> Schema parse
  -> Tool validate
  -> Hooks
  -> Permission system
  -> Tool.call()
  -> ToolResult
  -> API tool_result
  -> Message history
```

本地工具、MCP 工具、Plan 工具、Agent 工具、Skill 工具都尽量收敛到同一个 `Tool` 抽象。

这点是第四阶段最重要的参考：Claude 没有把 MCP 做成 Agent 主循环里的特殊分支，而是先把 MCP tool 包装成普通 Tool，再交给统一的工具执行管线。

## 与 ZzCode 当前状态的差异

只做理解，不写方案。

当前 ZzCode 和 Claude 的主要差异是：

| 维度 | ZzCode 当前 | Claude Code |
| --- | --- | --- |
| 工具参数 | 字符串 | JSON / Zod / JSON Schema |
| 工具调用 | `Action: Tool[input]` | assistant `tool_use` block |
| 工具结果 | 字符串 Observation | user `tool_result` block |
| 工具定义 | name / description / func | 完整 Tool 对象 |
| 权限 | 执行前确认钩子 + 简单安全检查 | 通用权限系统 + 工具自定义权限 + hooks + classifier |
| MCP | 未接入 | MCP tool 转成内部 Tool |
| UI | ToolUse / ToolResult 消息 | 工具自己提供渲染方法 |
| 上下文 | Agent 持有 history | ToolUseContext 提供运行环境 |
| 结果大小 | 简单字符串返回 | 大结果持久化、截断、结构化映射 |

## 后续查找索引

如果要看 Claude 工具定义：

- `restored-src/src/Tool.ts`

如果要看 Claude 内置工具集合：

- `restored-src/src/tools.ts`

如果要看某个具体工具：

- `restored-src/src/tools/<ToolName>/<ToolName>.ts`

如果要看工具执行主流程：

- `restored-src/src/services/tools/toolExecution.ts`

如果要看模型消息如何触发工具：

- `restored-src/src/query.ts`
- `restored-src/src/QueryEngine.ts`

如果要看权限：

- `restored-src/src/utils/permissions/permissions.ts`
- `restored-src/src/utils/permissions/PermissionMode.ts`
- `restored-src/src/utils/permissions/PermissionRule.ts`
- `restored-src/src/utils/permissions/filesystem.ts`

如果要看 MCP：

- `restored-src/src/services/mcp/client.ts`
- `restored-src/src/services/mcp/types.ts`
- `restored-src/src/services/mcp/mcpStringUtils.ts`
- `restored-src/src/tools/MCPTool/MCPTool.ts`
- `restored-src/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts`
- `restored-src/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts`
