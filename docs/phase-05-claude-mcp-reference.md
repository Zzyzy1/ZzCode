# 第五阶段：Claude Code MCP 实现参考

## 文档目标

本文只总结 Claude Code sourcemap 中 MCP 相关实现，为后续第五阶段设计做参考。

当前不做：

- 不写 ZzCode 第五阶段执行方案。
- 不修改 ZzCode MCP 代码。
- 不推导未读源码中的实现细节。

## 阅读范围

本次按 MCP 关键路径定向阅读，没有对 `claude-code-sourcemap` 做全盘扫描。

已阅读的主要源码：

- `restored-src/src/services/mcp/types.ts`
- `restored-src/src/services/mcp/config.ts`
- `restored-src/src/services/mcp/client.ts`
- `restored-src/src/services/mcp/mcpStringUtils.ts`
- `restored-src/src/tools.ts`
- `restored-src/src/Tool.ts`
- `restored-src/src/tools/MCPTool/MCPTool.ts`
- `restored-src/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts`
- `restored-src/src/tools/ListMcpResourcesTool/prompt.ts`
- `restored-src/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts`
- `restored-src/src/tools/ReadMcpResourceTool/prompt.ts`

## 总体结构

Claude Code 把 MCP 看作一种工具来源，而不是 Agent 执行循环里的特殊分支。

整体链路是：

```text
MCP 配置
  -> 连接 MCP server
  -> 读取 server capabilities
  -> tools/list 发现 MCP tools
  -> 转换成 Claude 内部 Tool 对象
  -> 与内置工具合并成 tool pool
  -> 模型按普通 tool_use 调用
  -> 运行统一权限检查
  -> client.callTool 调 MCP server
  -> 转换 MCP result 为 tool_result
```

资源也是 MCP 的能力之一，但 Claude 没有把资源当成本地文件系统搜索。资源通过 MCP server 的 `resources/list` 和 `resources/read` 协议显式访问。

## 配置来源

Claude 的 MCP server 配置定义在 `services/mcp/types.ts`，支持多种 transport：

- `stdio`
- `sse`
- `http`
- `ws`
- `sdk`
- IDE 专用的 `sse-ide`、`ws-ide`
- Claude.ai proxy 专用的 `claudeai-proxy`

每个 server 配置会带上 scope：

- `local`
- `user`
- `project`
- `dynamic`
- `enterprise`
- `claudeai`
- `managed`

`services/mcp/config.ts` 负责合并这些配置。主要来源包括：

- 当前项目和父目录中的 `.mcp.json`
- 用户全局配置
- 当前项目本地配置
- enterprise managed MCP 配置
- plugin 提供的 MCP server
- Claude.ai connector
- dynamic server

Claude 会读取从当前工作目录向上的 `.mcp.json`，用于 project scope 配置合并。这里检查的是固定文件名的配置文件，不是为了发现资源或文件而扫描整个目录树。

合并时有明确优先级和约束：

- enterprise 配置存在时可以独占 MCP server 来源。
- plugin MCP server 会和手工配置做去重，手工配置优先。
- project scope server 需要被批准后才进入可连接集合。
- allowlist、denylist、disabled server 会在连接前过滤。
- 合并顺序体现了 `plugin < user < project < local` 的优先级。

## 连接与状态

MCP server 的连接状态定义在 `services/mcp/types.ts`：

- `connected`
- `failed`
- `needs-auth`
- `pending`
- `disabled`

`services/mcp/client.ts` 中的 `connectToServer` 根据 server 配置创建不同 transport，并返回统一的 `MCPServerConnection`。

连接过程有几个重要特点：

- 连接结果 memoize，避免重复连接同一个 server 配置。
- 断线或 session 失效时清理连接缓存和工具/资源缓存。
- local server 包括 `stdio` 和 `sdk`，连接并发较低。
- remote server 使用更高并发。
- disabled server 不会发起连接。
- 对需要认证的 server，会返回 `needs-auth` 状态并暴露认证工具。

Claude 把 local 和 remote server 分组并发连接：

- local 默认并发较小，避免同时拉起过多本地进程。
- remote 默认并发较大，因为主要是网络连接。

## MCP 工具发现

MCP 工具发现核心函数是 `fetchToolsForClient`。

流程是：

```text
connected client
  -> 检查 capabilities.tools
  -> request({ method: "tools/list" })
  -> 清理 server 返回的 unicode 数据
  -> 对每个 MCP tool 构造 Claude Tool
```

Claude 内部有一个通用 `MCPTool` 模板，实际 MCP 工具是在发现阶段复制并覆盖字段：

- `name`
- `mcpInfo`
- `description`
- `prompt`
- `inputJSONSchema`
- `checkPermissions`
- `call`
- `userFacingName`
- 只读、破坏性、open world、并发安全等分类函数

`MCPTool` 自身的 input schema 是 `z.object({}).passthrough()`，因为 MCP tool 的真实参数 schema 来自 server 返回的 `inputSchema`。

## 工具命名

MCP 工具默认使用完整限定名：

```text
mcp__server__tool
```

相关函数在 `services/mcp/mcpStringUtils.ts`：

- `buildMcpToolName(serverName, toolName)`
- `getMcpPrefix(serverName)`
- `mcpInfoFromString(toolString)`
- `getToolNameForPermissionCheck(tool)`
- `getMcpDisplayName(fullName, serverName)`

命名会先做 MCP 名称规范化。完整名的目的不是展示友好，而是隔离命名空间。

权限匹配使用完整 MCP 工具名，而不是只用 MCP server 返回的短工具名。这样可以避免外部 MCP tool 和内置工具同名时错误复用权限规则。

SDK MCP server 有一个特殊模式：如果开启 `CLAUDE_AGENT_SDK_MCP_NO_PREFIX`，模型调用名可以不带 `mcp__` 前缀，但 `mcpInfo` 仍保留原始 server/tool 信息，权限检查仍能使用完整 MCP 身份。

## 工具池合并

工具池合并在 `tools.ts`：

- `getAllBaseTools()` 返回所有可能的内置工具。
- `getTools(permissionContext)` 返回当前模式下可用的内置工具。
- `assembleToolPool(permissionContext, mcpTools)` 把内置工具和 MCP 工具合并。

合并规则：

- 先对内置工具按权限 deny rule 过滤。
- 再对 MCP 工具按同一套 deny rule 过滤。
- 内置工具和 MCP 工具分别按名称排序，保证 prompt cache 稳定。
- 最后按名称去重，内置工具优先。

Claude 还会在模型看到工具前过滤 blanket deny 的工具。对 MCP 来说，类似 `mcp__server` 的 deny rule 可以在工具暴露给模型前移除该 server 的工具。

## MCP 工具权限

MCP tool 默认 `checkPermissions()` 返回 `passthrough`，并给出允许规则建议。

建议规则使用完整工具名：

```text
mcp__server__tool
```

这说明 Claude 不默认信任外部 MCP tool。即使 MCP tool 标注了 read-only，也仍然进入统一权限体系。

MCP tool 的分类信息主要来自 MCP annotations：

- `readOnlyHint` 用于只读和并发安全判断。
- `destructiveHint` 用于破坏性判断。
- `openWorldHint` 用于 open world 判断。

这些 hint 是分类依据，不等同于直接跳过权限检查。

## MCP 工具调用

MCP tool 调用逻辑在 `fetchToolsForClient` 构造出来的 `call()` 中。

主要流程：

```text
Claude Tool.call(args)
  -> 提取 tool_use_id
  -> 发 started progress
  -> ensureConnectedClient
  -> callMCPToolWithUrlElicitationRetry
  -> client.callTool({ name, arguments, _meta })
  -> processMCPResult
  -> 发 completed progress
  -> 返回 ToolResult data
```

调用时会传入 `_meta`，其中可以包含 `claudecode/toolUseId`。

`callMCPTool` 有几个关键保护：

- 使用 abort signal 支持取消。
- 使用 MCP SDK 的 timeout。
- 自己额外包一层 timeout，处理 SDK 内部 timeout 不生效的情况。
- 长时间运行时记录 progress。
- 401 会转换为 MCP auth error。
- session 失效会清理连接缓存，供下一次重新初始化。
- MCP result 标记 `isError` 时转成工具调用错误。

`callMCPToolWithUrlElicitationRetry` 处理 MCP server 要求用户打开 URL 的场景。它会在有限次数内处理 URL elicitation，然后重试原工具调用。

## MCP 结果转换

MCP 工具返回结果经过 `processMCPResult` 和 `transformResultContent` 规范化后再进入 Claude 的 tool result。

已阅读到的结果类型包括：

- `text`
- `image`
- `audio`
- `resource`
- `resource_link`
- `structuredContent`
- `_meta`

处理方式：

- 文本直接转为 text block。
- 图片会按 API 限制做 resize/downsample 后转为 image block。
- 音频和非图片二进制内容会落盘保存，再把保存路径作为文本返回。
- resource text 会带上 server 和 URI 来源说明。
- resource blob 如果是图片，按图片处理；否则保存到磁盘并返回路径说明。
- resource link 转成文本链接说明。
- structured content 和 `_meta` 会保留在 MCP meta 中。

这样做的目的，是避免把大块 base64 二进制直接塞进上下文。

## MCP Resources

Claude 把 MCP resources 作为独立能力处理，不把它们混进普通文件工具。

资源相关工具有两个：

- `ListMcpResourcesTool`
- `ReadMcpResourceTool`

这两个工具在 `tools.ts` 中属于 base tools，但在普通 `getTools()` 中会作为 special tools 排除。只有当至少一个已连接 MCP server 支持 resources 时，MCP client 聚合阶段才会把它们加入 MCP tools 集合，并且只加入一次。

### ListMcpResourcesTool

输入：

- `server` 可选，用于限定某个 MCP server。

行为：

- 如果传入 server，只列出该 server 的 resources。
- 如果不传 server，列出所有已连接 MCP server 的 resources。
- 对每个 connected client 调用 `fetchResourcesForClient`。
- `fetchResourcesForClient` 调用 MCP 协议 `resources/list`。
- 返回结果中的每个 resource 都补充 `server` 字段。

重要点：

- `fetchResourcesForClient` 按 server name 做 LRU cache。
- cache 会在连接关闭和 `resources/list_changed` 通知后失效。
- 列资源是 MCP 协议调用，不是本地目录 glob。

### ReadMcpResourceTool

输入：

- `server` 必填。
- `uri` 必填。

行为：

- 先按 server name 找到 MCP client。
- server 不存在、未连接或不支持 resources 时直接报错。
- 调用 MCP 协议 `resources/read`，参数只有 URI。
- 文本内容直接返回。
- blob 内容先 base64 解码并保存到磁盘，然后返回保存路径说明。

这说明 Claude 读取 MCP resource 的边界由 MCP server 和 URI 决定。Claude 侧不会因为 URI 不存在就去本地全盘搜索。

## Prompts 与 Commands

MCP server 如果支持 prompts，Claude 会通过 `prompts/list` 发现 prompt，并把它们转换成内部 command。

命名方式同样使用 MCP 前缀：

```text
mcp__server__prompt
```

执行 command 时会调用 `client.getPrompt()`，再把返回 message content 走同一套 `transformResultContent`。

## Skills

在已读代码中，Claude 有可选的 `MCP_SKILLS` feature。若开启且 server 支持 resources，会从 `skill://` resources 发现 MCP skills。

这部分不是本次重点，只确认它依赖 resources 能力，不是本地目录扫描。

## 关于扫描边界

Claude MCP 相关实现里有三类“查找”：

1. 配置查找：从当前目录向上读取固定文件名 `.mcp.json`，并合并其他配置来源。
2. 工具发现：对已配置且已连接的 MCP server 调 `tools/list`。
3. 资源发现：对已连接且支持 resources 的 MCP server 调 `resources/list`。

这些都不是对用户项目文件做全盘扫描。

资源的可见范围由 MCP server 自己决定。Claude 只消费 server 暴露出来的资源列表和 URI；读取资源时也必须带 server name 和 URI。

如果某个 MCP server 自己内部实现了大范围扫描，那是该 MCP server 的行为，不是 Claude Code MCP client 自动做的行为。

## 对第五阶段后续设计有用的观察

以下只是 Claude 实现事实的抽象，不是 ZzCode 方案：

- MCP 应作为工具来源接入统一工具系统。
- MCP tool 应有独立命名空间，避免和内置工具冲突。
- 权限规则应匹配完整 MCP 工具身份。
- MCP resources 应通过 `list` 和 `read` 两步显式访问。
- Agent 不应该在 resource 不存在时自行退化成本地全盘搜索。
- MCP 连接、工具发现、资源发现都需要缓存与失效机制。
- 二进制结果不应直接进入上下文，应保存后返回路径或摘要。
- server 配置来源和 server 连接状态应该是显式模型，而不是散落在工具函数中。

## 针对 tests/mcp_test 问题的 Claude 实现补充

本节针对 ZzCode 当前 `tests/mcp_test` 中暴露的 stdio 连接失败问题，补充阅读 Claude Code sourcemap 中相关实现。

新增阅读片段：

- `restored-src/src/services/mcp/client.ts` 中 `connectToServer`
- `restored-src/src/services/mcp/client.ts` 中 `fetchToolsForClient`
- `restored-src/src/services/mcp/client.ts` 中 `fetchResourcesForClient`
- `restored-src/src/services/mcp/client.ts` 中 `getMcpToolsCommandsAndResources`
- `restored-src/src/services/mcp/client.ts` 中 `callMCPToolWithUrlElicitationRetry` / `callMCPTool`

### stdio transport

Claude 没有手写 stdout 行读取和 JSON-RPC 超时逻辑，而是使用 MCP 官方 SDK：

```text
new StdioClientTransport({
  command,
  args,
  env,
  stderr: "pipe"
})
```

随后通过 SDK `Client` 执行：

```text
client.connect(transport)
client.request({ method: "tools/list" }, schema)
client.callTool(...)
```

这个设计把跨平台 stdio pipe 读写、JSON-RPC framing、pending request 管理交给 SDK。对 ZzCode 当前问题最关键的是：Claude 不在 Windows 的普通进程 pipe 上使用 `select.select()`。

### 连接超时和失败处理

Claude 连接 server 时会把 `client.connect(transport)` 和一个显式 timeout promise 做 race：

```text
connectPromise = client.connect(transport)
timeoutPromise = setTimeout(...)
await Promise.race([connectPromise, timeoutPromise])
```

timeout 触发时会关闭 transport；连接失败时也会关闭 transport，并记录连接耗时和错误类型。

Claude 还会在连接前给 stdio transport 绑定 stderr handler：

- `stderr` 使用 pipe，不直接打印到 UI。
- stderr 内容累积到字符串中。
- 累积长度有上限，避免无限增长。
- 连接成功或失败时，如果有 stderr，会写入 MCP error log。
- cleanup 时移除 stderr listener，避免泄漏。

这和 ZzCode 当前 `stderr=subprocess.DEVNULL` 不同。Claude 的做法保留了 server 启动失败、包安装失败、协议输出错误等诊断线索。

### onerror / onclose 与缓存失效

Claude 在连接建立后重写 client 的错误和关闭处理：

- `client.onerror` 会按错误文本识别 `ECONNRESET`、`ETIMEDOUT`、`EPIPE`、`ECONNREFUSED`、`EHOSTUNREACH`、`spawn` 等常见失败。
- 对 HTTP/SSE 这类远端连接，连续 terminal errors 会触发 close，让挂起请求失败并允许下次重连。
- `client.onclose` 会清理连接缓存，以及按 server name 缓存的 tools、resources、commands、skills。
- 注释明确说明：调用 `client.close()` 会让 SDK 拒绝 pending request；只手动调用 onclose 不足以释放挂起调用。

这说明 Claude 把“连接失效”和“发现结果缓存失效”绑定处理。连接关闭后，下一次请求不会继续使用旧 tools/resources。

### 关闭 stdio 子进程

Claude 对 stdio server 的关闭不是只调用 transport close。cleanup 中会：

- 移除 stderr listener。
- 对 stdio child pid 先发送 `SIGINT`。
- 短时间等待优雅退出。
- 必要时升级到后续终止流程。

注释说明原因：部分 MCP server，尤其 Docker/container 类 server，只靠 SDK transport close 不一定能触发优雅关闭。

### 工具和资源发现失败隔离

Claude 的 `fetchToolsForClient`：

```text
if client.type !== "connected" return []
if !client.capabilities?.tools return []
request tools/list
catch error -> log -> return []
```

`fetchResourcesForClient` 也是同类策略：

```text
if client.type !== "connected" return []
if !client.capabilities?.resources return []
request resources/list
catch error -> log -> return []
```

在聚合层 `getMcpToolsCommandsAndResources` 中，单个 server 的连接、tools、commands、resources 发现被包在独立 `try/catch` 中。失败时会回调一个 `failed` client，并给空 tools/commands。这样单个 MCP server 失败不会中断其他 server。

### local / remote 分组连接

Claude 会按 server 类型分组：

- local server：`stdio` / `sdk`
- remote server：HTTP/SSE/其他远端类型

local server 使用较低并发，避免同时拉起过多本地进程；remote server 使用较高并发。ZzCode 第一版可以暂不做复杂并发，但这个设计说明 stdio server 启动被视为本地进程资源，需要单独的连接策略。

### MCP tool 调用保护

Claude MCP tool 的 `call()` 会：

- 发送 started/completed/failed progress。
- 调用前 `ensureConnectedClient`。
- 调用 `client.callTool({ name, arguments, _meta }, schema, { signal, timeout, onprogress })`。
- 额外包一层 timeout，防止 SDK timeout 未生效。
- 把 SDK progress 转为 MCP progress。
- MCP result 含 `isError` 时转为工具错误。
- session 过期时清缓存并有限重试。

这说明 Claude 不只在连接阶段做保护；实际 `tools/call` 也有取消、超时、progress、错误归一化和重连边界。

### 对 ZzCode 当前问题的直接启发

结合 `tests/mcp_test` 的 `WinError 10038`，最直接的差异是：

- Claude 使用 SDK `StdioClientTransport`，避免手写跨平台 pipe `select`。
- Claude 保留 stderr，连接失败时能看到 server 侧错误。
- Claude 连接失败会关闭 transport，并让 pending request 明确失败。
- Claude 连接关闭会清 tools/resources cache，避免旧发现结果污染后续状态。
- Claude 聚合层对单 server 失败做隔离，但仍把失败状态作为 client 状态上报。

ZzCode 后续如果继续保持同步 `Tool.call()`，也应把 stdio client 封装在一个跨平台安全的连接层里，而不是继续在 Windows pipe 上使用 `select.select()`。
