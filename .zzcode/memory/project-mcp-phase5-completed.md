# ZzCode 第五阶段已接入 MCP

记录时间：2025-07-16

## 内容

ZzCode 第五阶段（MCP 工具来源接入）已完成开发。

### 已完成的核心能力

1. **MCP 配置读取**：支持 `.zzcode/mcp.json` 配置文件，读取和校验 MCP server 配置。
2. **MCP 连接管理**：支持 stdio transport 的 MCP server 连接，状态包括 `pending`、`connected`、`failed`、`disabled`。
3. **工具发现与适配**：通过 `tools/list` 发现 MCP tools，转换为 ZzCode `Tool` 协议对象，命名格式为 `mcp__server__tool`。
4. **工具池合并**：MCP tools 合并进 `ToolRegistry`，Agent 主循环不变，本地工具名冲突时本地工具优先。
5. **工具调用链路**：复用 `ToolRunner` 的 schema 校验、权限确认和异常转换，MCP tool 默认需要权限确认。
6. **资源访问**：通过 `list_mcp_resources` 和 `read_mcp_resource` 显式访问 MCP resources，不访问本地文件系统。
7. **前端展示**：CLI 和 JSON Lines 事件透传 `source=mcp` 和 `mcp_info` 字段。

### 边界约束

- MCP 配置只读取 `.zzcode/mcp.json`，不扫描父目录。
- MCP tool 只来自已配置 server 的 `tools/list`。
- MCP resource 只通过 `server + uri` 访问，不兜底本地文件搜索。
- MCP 失败时不调用本地 `glob`、`grep`、`find_file` 或 shell。

### 第一版限制

- 只支持 `stdio` transport。
- 不支持 HTTP/SSE/WebSocket/OAuth。
- 不支持 `prompts`、`templates`、`completion`。
- 不支持 `resources/list_changed` 通知。
- 不支持并发请求、取消和 progress。
- Blob resource 暂不支持直接进入上下文。

### 参考文档

- `docs/phase-05-mcp-layer.md`
- `docs/phase-05-claude-mcp-reference.md`\n\n### 后续变更\n\nZzCode 第五阶段已从自定义实现改为官方 MCP SDK 连接实现。\n\n- 原实现：自定义 stdio transport 连接、工具发现与适配\n- 新实现：基于官方 MCP SDK（`@modelcontextprotocol/sdk`）进行连接管理\n- 连接方式：使用 SDK 提供的 `Client` 和 `StdioClientTransport` 建立与 MCP server 的通信\n- 工具调用：通过 SDK 的 `listTools()`、`callTool()` 等标准接口完成\n- 相关文件：`src/mcp/` 目录下的 MCP 连接层代码已重构为 SDK 实现，配置读取仍基于 `.zzcode/mcp.json`
