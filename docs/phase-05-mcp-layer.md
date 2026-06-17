# 第五阶段：MCP 工具来源接入方案

## 阶段目标

第五阶段按 Claude Code 的实现思路，把 MCP 接入 ZzCode 的结构化工具层。

本阶段的核心目标不是增加某个具体 MCP server，而是建立一条稳定链路：

```text
MCP 配置
  -> MCP client 连接 server
  -> 发现 MCP tools/resources
  -> 转换为 ZzCode Tool
  -> 合并进 ToolRegistry
  -> 复用 ToolRunner 权限和执行管线
  -> 把 MCP 结果作为 tool_result 回灌模型
```

MCP 只能作为工具来源接入，不应该成为 Agent 主循环里的特殊分支。

参考文档：

- `docs/phase-05-claude-mcp-reference.md`

## 验收标准

完成第五阶段时，应满足：

1. ZzCode 可以从配置文件读取 MCP server 配置。
2. MCP server 有明确连接状态：`connected`、`failed`、`disabled` 等。
3. 已连接 server 可以通过 MCP 协议发现 tools。
4. MCP tools 会转换成现有 `Tool` 协议对象。
5. MCP tools 使用独立命名空间，默认格式为 `mcp__server__tool`。
6. MCP tools 进入现有 `ToolRegistry`，Agent 不需要知道工具来自 MCP。
7. MCP tool 调用复用现有 `ToolRunner` 的 schema 校验、权限确认和异常转换。
8. MCP tool 默认需要权限确认，权限请求展示完整 MCP 工具名和参数。
9. MCP resources 通过 `ListMcpResourcesTool` 和 `ReadMcpResourceTool` 显式访问。
10. resource 不存在时只返回 MCP server 错误，不退化为本地文件搜索或全盘扫描。
11. CLI 和 JSON Lines 前端仍能展示 MCP 工具调用、权限确认和结果。
12. 每步完成后说明是否运行测试；默认不新增测试代码，关键风险点只列出建议验证项，等待确认后再补测试。

## 暂不实现

本阶段暂不做：

- Claude.ai connector。
- plugin 提供 MCP server。
- enterprise managed MCP 配置。
- OAuth / XAA / 浏览器 URL elicitation 完整流程。
- IDE 专用 MCP server。
- WebSocket transport。
- MCP prompts 转 slash command。
- MCP skills。
- ToolSearch / deferred MCP tools。
- hooks。
- auto mode classifier。
- 大规模并发连接优化。
- 二进制结果复杂预览。

这些能力可以在基础 MCP 工具来源稳定后继续分阶段补齐。

## Claude Code 参考原则

本阶段优先吸收 Claude Code 的以下设计：

1. MCP 是工具来源，不改变 Agent 主循环。
2. MCP server 配置、连接状态、工具发现和工具调用分层管理。
3. MCP tool 转换为普通 Tool 后进入统一工具池。
4. MCP tool 使用 `mcp__server__tool` 命名，避免和内置工具冲突。
5. 权限匹配使用完整 MCP 工具身份。
6. resources 通过 `resources/list` 和 `resources/read` 显式访问。
7. 不因为 resource 或文件名找不到而做本地全盘搜索。
8. 连接和发现结果可以缓存，但必须有明确失效边界。

不照搬 Claude Code 的复杂部分：

- 多来源配置合并的完整企业策略。
- 多 transport 全覆盖。
- UI 组件级 MCP 渲染。
- 遥测、feature flag 和生产级认证逻辑。
- 大量 SDK/浏览器/IDE 专用分支。

## 第一版范围

第一版建议只支持最小可运行 MCP 工具链。

### 配置范围

支持项目级配置文件：

```text
.zzcode/mcp.json
```

配置结构参考 Claude 的 `mcpServers`：

```json
{
  "mcpServers": {
    "demo": {
      "type": "stdio",
      "command": "python",
      "args": ["server.py"],
      "env": {}
    }
  }
}
```

第一版只要求 `stdio` 可用。`http` 和 `sse` 可以在模块接口中预留，但不作为第一版验收条件。

选择 `.zzcode/mcp.json` 的原因：

- ZzCode 当前已经有 `.zzcode/` 作为项目运行状态目录。
- 不和 Claude Code 的 `.mcp.json` 混用，避免误读用户已有 Claude 配置。
- 读取固定文件，不做目录扫描。

后续如需兼容 `.mcp.json`，应作为显式兼容功能加入，而不是默认读取。

### 连接范围

第一版只连接配置中明确启用的 server。

不做：

- 向上查找父目录配置。
- 自动发现 MCP server。
- 插件扫描。
- 网络 registry 查询。

### 工具范围

支持：

- `tools/list`
- `tools/call`

暂不支持：

- `prompts/list`
- `prompts/get`
- `resources/templates/list`
- `completion/complete`

### 资源范围

支持：

- `resources/list`
- `resources/read`

资源访问必须由 MCP server 返回的 URI 驱动。ZzCode 不对 URI 做本地路径猜测，也不因为读取失败而调用 `glob` 或 `find_file`。

## 目标架构

第五阶段后的建议结构：

```text
src/zzcode/
├── mcp/
│   ├── __init__.py
│   ├── config.py
│   ├── connection.py
│   ├── manager.py
│   ├── names.py
│   ├── resources.py
│   └── tool_adapter.py
├── tools/
│   ├── builtin.py
│   ├── registry.py
│   ├── runner.py
│   └── mcp/
│       ├── __init__.py
│       ├── list_resources.py
│       └── read_resource.py
└── cli/
    └── main.py
```

模块职责：

```text
mcp/config.py        读取和校验 .zzcode/mcp.json
mcp/connection.py    表示单个 MCP server 连接和状态
mcp/manager.py       管理多个 server 的连接、工具发现和资源缓存
mcp/names.py         MCP 工具名规范化、构造和解析
mcp/resources.py     resources/list 和 resources/read 的 client 封装
mcp/tool_adapter.py  把 MCP tool 定义转换成 ZzCode Tool
tools/mcp/           ZzCode 内置的 MCP resource 工具
tools/builtin.py     组装本地工具和 MCP 工具来源
```

## 核心数据模型

### McpServerConfig

建议字段：

```text
name
type
command
args
env
enabled
timeout_seconds
```

第一版 `type` 只支持：

```text
stdio
```

### McpConnection

建议字段：

```text
name
config
status
client
capabilities
server_info
error
```

`status` 建议使用：

```text
pending
connected
failed
disabled
```

后续再扩展：

```text
needs_auth
```

### McpToolInfo

保存 MCP server 返回的原始工具信息：

```text
server_name
tool_name
description
input_schema
annotations
```

### McpToolAdapter

`McpToolAdapter` 实现现有 `Tool` 协议。

字段映射：

```text
name              mcp__server__tool
description       MCP tool description
input_schema      MCP tool inputSchema
display_name      server:tool
source            mcp
mcp_info          { server_name, tool_name }
is_read_only      annotations.readOnlyHint
is_destructive    annotations.destructiveHint
requires_approval true
```

调用行为：

```text
Tool.call(args)
  -> manager.call_tool(server_name, tool_name, args)
  -> 转换 MCP result
  -> ToolResult.success / ToolResult.failure
```

### McpResource

资源列表项建议包含：

```text
server
uri
name
description
mime_type
```

读取资源时必须同时提供：

```text
server
uri
```

## 命名规则

MCP 工具名默认格式：

```text
mcp__{server_name}__{tool_name}
```

需要实现：

```text
normalize_mcp_name(value) -> str
build_mcp_tool_name(server_name, tool_name) -> str
parse_mcp_tool_name(name) -> McpToolName | None
get_mcp_permission_name(tool) -> str
```

规范化规则第一版保持简单：

- 去除首尾空白。
- 非字母、数字、下划线字符替换为 `_`。
- 连续 `_` 合并。
- 空名称视为非法。

注意事项：

- `mcp__` 前缀是模型调用名和权限名的一部分。
- 权限确认必须展示完整 MCP 工具名。
- MCP server 原始名称和 tool 原始名称要保存在 `mcp_info`，不能只保存规范化后的名字。

## 权限策略

第一版策略：

- MCP tool 默认 `requires_approval = True`。
- 即使 MCP annotations 标注 read-only，也先进入权限确认。
- 权限请求的 `tool_name` 使用完整 `mcp__server__tool`。
- 用户拒绝后，当前工具调用直接失败，不自动换 shell 或本地文件工具绕过。

这和第四阶段已经实现的“拒绝后停止当前工具调用”保持一致。

后续可扩展：

- 按 `mcp__server__tool` 记住允许规则。
- 按 `mcp__server` 允许整个 server。
- 只读 MCP tool 的自动允许策略。

## 工具池合并

ZzCode 当前已有 `ToolRegistry`。

第五阶段只增加工具来源：

```text
local tools
  + MCP tools
  + MCP resource tools
  -> ToolRegistry
```

建议实现一个组装函数：

```text
build_tool_registry(project_root, mcp_manager=None) -> ToolRegistry
```

合并规则：

- 先注册本地内置工具。
- 再注册 MCP tools。
- 如果工具名冲突，保留本地工具，跳过 MCP tool 并记录 warning。
- 只有当至少一个 connected server 支持 resources 时，才注册 `list_mcp_resources` 和 `read_mcp_resource`。

第一版不做复杂排序和 prompt cache 优化，但要保证注册顺序稳定。

## MCP Resources 工具

### list_mcp_resources

输入：

```json
{
  "server": "optional server name"
}
```

行为：

- 不传 server 时列出所有 connected server 暴露的 resources。
- 传 server 时只列出指定 server。
- 如果 server 不存在，返回明确错误。
- 调用 MCP `resources/list`，不访问本地文件系统。

### read_mcp_resource

输入：

```json
{
  "server": "server name",
  "uri": "resource URI"
}
```

行为：

- 检查 server 是否存在且 connected。
- 检查 server 是否支持 resources。
- 调用 MCP `resources/read`。
- 文本内容直接返回。
- blob 内容第一版可以返回“暂不支持二进制 resource”的错误或保存到 `.zzcode/sessions/<session>/artifacts/`。

第一版建议先保存到 artifacts，并返回路径说明。这样和 Claude “二进制不直接进入上下文”的原则一致。

## 扫描边界

第五阶段必须保持以下边界：

1. MCP 配置只读取 `.zzcode/mcp.json`。
2. MCP tool 只来自已配置 server 的 `tools/list`。
3. MCP resource 只来自已连接 server 的 `resources/list`。
4. 读取 resource 必须使用明确的 `server + uri`。
5. MCP 失败时不调用本地 `glob`、`grep`、`find_file` 或 shell 做兜底。
6. 本地搜索工具仍然只在用户意图需要搜索项目文件时由模型显式调用。

这条边界用于避免“没找到文件就新建”或“没找到 resource 就全盘扫”的错误行为。

## 分步骤执行计划

- [x] 第 1 步：新增第五阶段文档和 MCP 目录骨架，不接入主链。
- [x] 第 2 步：实现 MCP 配置模型和 `.zzcode/mcp.json` 读取校验。
- [x] 第 3 步：实现 MCP 工具名构造、解析和权限名辅助函数。
- [x] 第 4 步：实现 stdio MCP connection，支持启动、初始化、关闭和状态记录。
- [x] 第 5 步：实现 `McpManager`，管理多个 server 的连接、失败隔离和工具发现。
- [x] 第 6 步：实现 `tools/list` 到 `McpToolAdapter` 的转换。
- [x] 第 7 步：把 MCP tools 合并进 `ToolRegistry`，保持 Agent 主循环不变。
- [x] 第 8 步：实现 MCP tool 调用链路，复用 `ToolRunner` 权限确认和异常转换。
- [x] 第 9 步：实现 MCP resource 列表缓存和 `list_mcp_resources` 工具。
- [x] 第 10 步：实现 `read_mcp_resource` 工具，明确禁止本地搜索兜底。
- [x] 第 11 步：接入 CLI 和 JSON Lines 事件展示，确认前端能显示 MCP 权限请求和结果。
- [x] 第 12 步：整理风险复查和可选测试清单，不默认新增测试代码。
- [x] 第 13 步：更新 README，说明 MCP 配置、边界和第一版限制。

## 每步验收细节

### 第 1 步：目录骨架

验收：

- 新增 `src/zzcode/mcp/`。
- 新增 `src/zzcode/tools/mcp/`。
- 不改变现有 Agent 行为。
- 默认不新增测试代码；如未运行测试，需要在阶段反馈中明确说明。

### 第 2 步：配置读取

验收：

- 无 `.zzcode/mcp.json` 时返回空配置。
- JSON 格式错误时返回可读错误。
- 不支持的 transport type 被拒绝。
- disabled server 不进入连接队列。

### 第 3 步：命名

验收：

- `build_mcp_tool_name("demo", "search") == "mcp__demo__search"`。
- 特殊字符被稳定规范化。
- 可以从完整工具名解析出 server/tool。
- 权限名不和本地工具名混用。

### 第 4 步：stdio connection

验收：

- 可以启动一个示例 MCP server。
- 初始化后记录 capabilities。
- server 启动失败不会中断 ZzCode。
- 会话结束时能关闭 server。

### 第 5 步：McpManager

验收：

- 多个 server 可以独立连接。
- 单个 server 失败不影响其他 server。
- 可以返回 connected clients、tools、resources。
- 连接状态可用于 UI 或 debug 输出。

### 第 6 步：McpToolAdapter

验收：

- MCP tool description 和 inputSchema 能进入 `to_openai_tool()`。
- `source == "mcp"`。
- `mcp_info` 保留原始 server/tool 名称。
- annotations 能映射到只读、破坏性和 open world metadata。

### 第 7 步：工具池合并

验收：

- Agent 获取 tools schema 时包含 MCP tools。
- 本地工具名冲突时本地工具优先。
- 未配置 MCP 时行为和第四阶段一致。

### 第 8 步：工具调用

验收：

- 模型调用 `mcp__server__tool` 时能转发到对应 MCP server。
- 权限确认出现在调用前。
- 拒绝后只返回当前 tool result 错误，不自动改用其他工具。
- MCP server 错误会变成结构化 `ToolResult.failure`。

### 第 9 步：资源列表

验收：

- 只有支持 resources 的 server 才参与列表。
- `list_mcp_resources` 不访问本地文件系统。
- cache 有明确清理入口。

### 第 10 步：资源读取

验收：

- `read_mcp_resource` 必须提供 server 和 uri。
- server 不存在、未连接、不支持 resources 都返回明确错误。
- URI 不存在时返回 MCP 错误，不搜索本地文件。
- blob 不直接以 base64 塞进上下文。

### 第 11 步：前端展示

验收：

- MCP tool 权限请求显示完整工具名。
- 用户允许后显示执行中和执行结果。
- 用户拒绝后显示拒绝结果。
- JSON Lines 事件中保留 `source=mcp` 和 `mcp_info`。

### 第 12 步：风险复查和可选测试清单

验收：

- 不默认新增测试代码。
- 汇总建议验证项：MCP config、names、manager、adapter、stdio 连接、权限拒绝、resource list/read、失败 server 隔离。
- 标明哪些验证项属于高风险，建议后续确认后再写测试。
- 如果本阶段未运行测试，需要在最终反馈中明确写明 `未运行测试`。

### 第 13 步：README

验收：

- README 说明 `.zzcode/mcp.json` 示例。
- README 说明第一版只支持 stdio。
- README 说明 MCP 不会做本地全盘扫描。
- README 说明 resources 的 list/read 使用方式。

## 风险与处理

### Python MCP SDK 依赖

MCP 协议实现不适合完全手写。第一版建议使用官方 Python MCP SDK 或项目可接受的最小依赖。

如果依赖安装不可用，先实现接口和 fake client 适配层，实际 stdio 连接延后。是否补测试代码单独确认。

### 异步与现有同步工具层

ZzCode 当前 `Tool.call()` 是同步接口，而 MCP client 可能是 async。

第一版可以选择：

- 在 MCP manager 内部封装同步调用入口。
- 或先把 MCP adapter 做成同步 wrapper，后续再统一工具层 async 化。

不建议在第五阶段一开始大规模改造整个 Agent 为 async。

### 资源与文件名混淆

MCP resource URI 不是本地路径。即使 URI 看起来像 `1.txt`，也不能自动映射到项目文件。

本地文件修改仍应走 `read_file`、`edit_file`、`glob` 等本地工具；MCP resource 只能通过 MCP server 暴露的 URI 读取。

### 权限绕过

MCP server 可能暴露和本地工具同名或类似的能力。

必须用完整 MCP 工具名做权限确认，并默认 ask，避免外部工具借用本地工具权限。

## 第 12 步复查结果

本步骤只整理风险和建议验证项，不新增测试代码。

### 已做手动验证

- MCP config：缺失配置、非法 JSON、unsupported transport、disabled server 过滤。
- MCP names：`mcp__server__tool` 构造、特殊字符规范化、解析、非 MCP 工具权限名保持本地名称。
- stdio connection：initialize、capabilities/server_info 记录、启动失败隔离、关闭进程。
- McpManager：多 server 连接、失败隔离、`tools/list`、`resources/list` cache、`resources/read` 错误路径。
- McpToolAdapter：schema 输出、`source=mcp`、`mcp_info` 原始名称保留、read-only hint 仍默认 ask。
- ToolRunner 权限链路：MCP tool 调用前确认，拒绝后不发送 `tools/call`。
- resource list/read：只走 MCP `resources/list/read`，不访问本地文件系统；blob 不直接进入上下文。
- JSON Lines / frontend：MCP tool_use、tool_result、permission_request 透传 `source` 和 `mcpInfo`，前端 TypeScript build 通过。

### 建议补测试清单

高风险，建议优先补自动化测试：

- `mcp/config.py`：配置读取、错误信息、disabled server 不进入连接队列。
- `mcp/names.py`：规范化和解析稳定性，特别是特殊字符、空名称和非 MCP 名称。
- `mcp/connection.py`：stdio server initialize、timeout、启动失败、进程关闭。
- `mcp/manager.py`：单 server 失败隔离、resource cache 清理、unknown server 和 unsupported capability 错误。
- `mcp/tool_adapter.py`：MCP result 转换、`isError` 失败、`mcp_info` 和权限请求元数据。
- `tools/mcp/list_resources.py` 与 `read_resource.py`：不调用本地文件工具、不做 URI 到本地路径兜底、blob 省略。
- JSON Lines：`tool_use/tool_result/permission_request` 对 MCP 字段的协议兼容性。

中风险，可在功能稳定后补：

- CLI/JSONL 启动时 MCP config 错误不会阻断本地工具。
- MCP tools 与本地工具冲突时本地工具优先。
- allow_session 对完整 MCP 工具名生效，不共享给同 server 其他工具。
- 前端展示 MCP 完整工具名、友好名和权限风险级别。

### 仍需注意

- 当前 stdio JSON-RPC 是最小同步实现，不支持完整 MCP SDK 能力、并发请求、取消和 progress。
- MCP resource blob 当前返回明确失败，后续如果改为 artifacts 写盘，需要补路径边界和清理策略。
- resources cache 只有显式清理入口，尚未处理 server 的 `resources/list_changed` 通知。
- HTTP/SSE/WebSocket/OAuth/prompts/templates 仍在本阶段暂不实现范围内。

## tests/mcp_test 当前问题复盘

本节来自 `tests/mcp_test/debug.txt` 和 `tests/mcp_test/debug/*.png` 的观察，只记录当前问题，不在本次直接修改代码。

### 测试场景

用户输入：

```text
用 MCP memory 记录一条信息：ZzCode 第五阶段已接入 MCP
```

当前 `.zzcode/mcp.json` 配置了两个 stdio server：

- `memory`：`cmd /c npx -y @modelcontextprotocol/server-memory`
- `git`：`cmd /c uvx mcp-server-git --repository D:\zzy\JavaLearn\agent_learn\ZzCode`

截图显示 Windows 环境中 `npx`、`uvx`、`node`、`npm`、`uv` 都存在，因此这次失败不能简单归因于命令不存在。

### 暴露的问题

1. MCP stdio 连接在 Windows 下失败。

   启动时 `git` 和 `memory` 都报：

   ```text
   [WinError 10038] 在一个非套接字上尝试了一个操作。
   ```

   当前 `src/zzcode/mcp/connection.py` 在 `_read_line_with_timeout()` 中对 `subprocess.PIPE` 返回的 stdout 调用 `select.select()`。Windows 的 `select` 只支持 socket，不支持普通进程 pipe；因此 stdio MCP server 即使成功启动，也可能在读取响应前失败。

2. MCP server 失败后没有进入工具池。

   transcript 里没有出现 `mcp__memory__...` 工具调用，也没有 MCP permission request。模型后续调用的是本地 `list_files`、`glob`、`read_file`、`write_file`、`edit_file`。这说明 MCP 连接失败后 `McpManager` 没有可用 connected server，MCP tools 没有注册进 `ToolRegistry`。

3. 用户明确要求使用 MCP memory，但系统退化为本地文件写入。

   模型最终写入了 `.zzcode/memory/project-mcp-phase5-completed.md` 并编辑 `.zzcode/memory/MEMORY.md`。这完成了“记录信息”的相似目标，但没有完成“用 MCP memory”的工具约束。后续需要在 MCP 指定工具不可用时给用户明确失败反馈，避免静默改用本地 memory 文件。

4. 失败诊断信息不足。

   当前 stdio server 的 `stderr=subprocess.DEVNULL`，如果 MCP server 本身输出了启动错误、包安装错误或协议错误，ZzCode 会丢失这部分信息。最终 UI 只显示 Python 侧的 `WinError 10038`，难以判断 server 是否已启动、是否已输出错误、是否返回了非 JSON 内容。

5. 本轮任务最后触发 `max steps reached`。

   debug 里最后显示：

   ```text
   request finished without answer; turn was not saved
   Stopped: max steps reached.
   ```

   这不是 MCP 协议错误本身，但它说明 MCP 不可用后模型走了较长的本地文件探索和写入路径，最终没有正常回答用户。后续应把 MCP 连接失败作为更早、更明确的系统反馈暴露给 Agent 或用户。

### 当前实现需要补强的点

- `mcp/connection.py` 不应在 Windows stdio pipe 上使用 `select.select()`。
- stdio 连接层需要保留 server stderr 的有限长度输出，用于失败诊断。
- 连接失败、工具发现失败、工具调用失败应区分错误类型，并保留 server name、transport、command 摘要。
- 当用户明确指定 MCP server/tool 意图，而 MCP tools 没有可用时，应返回“目标 MCP server 不可用”的结果，不应静默退化成本地文件工具。
- 第 12 步“stdio connection 已做手动验证”的结论需要按 Windows 测试结果修正：当前只证明失败隔离生效，没有证明 Windows stdio server 可连通。

### 建议下一步

优先级建议：

1. 替换 stdio 读写实现：优先接入官方 Python MCP SDK；如果暂不引入依赖，至少用后台 reader thread + queue 实现跨平台 stdout 读取超时。
2. 把 stderr 从 `DEVNULL` 改为 `PIPE`，累计有限长度并在连接失败时写入 `connection.error`。
3. 增加 Windows stdio MCP smoke test，覆盖 `npx @modelcontextprotocol/server-memory` 或一个本地最小 MCP server。
4. 在 CLI/JSONL 启动事件里展示 MCP failed server 的详细原因，并让 Agent 可感知“用户要求的 MCP memory 不可用”。
