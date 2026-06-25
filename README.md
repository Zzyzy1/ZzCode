# ZzCode

基于 **Python + React Ink** 的终端 Code Agent CLI，用于学习现代 AI 编程助手的工作原理。

ZzCode 不是为了完整复刻 Claude Code 产品，而是从**一个可运行的最小 Agent 开始，逐步学习并实现其核心机制**——从结构化工具调用、权限确认、上下文记忆，到子 Agent 调度、MCP 接入、实时联网工具和并发工具执行。每个阶段都有独立的设计文档，方便追溯设计决策。

![ZzCode terminal UI](docs/img/1.png)

## 当前能力

- **结构化 tool-call Agent 主循环** — 基于 OpenAI-compatible `tool_calls`，统一使用 `ToolRegistry` + `ToolRunner`
- **流式输出** — 支持 `assistant_delta` 实时文本流式，前端自动合并增量，避免逐 token 刷屏
- **React + Ink 终端 UI** — 多行输入、列宽感知光标、逐行独立渲染、viewport 滚动
- **权限确认系统** — 工具执行前需用户确认，破坏性工具默认要求授权，拒绝后停止当前 turn
- **Markdown 记忆文件** — Claude Code 风格的 `.zzcode/memory/` 目录，支持自动提取用户偏好
- **短期会话记忆** — compact / trim / 自动摘要，带上下文预算感知
- **子 Agent（Subagents）** — 用户可调用的 `general-purpose` 子 Agent，以及后台系统 worker（会话记忆更新、自动记忆提取）
- **MCP stdio 接入** — 通过 `.zzcode/mcp.json` 将 MCP server 作为结构化工具来源
- **JSON Lines 前后端协议** — 前后端通过 stdin/stdout JSONL 通信，解耦清晰，便于调试和扩展
- **工具折叠展示** — 连续的 `read_file` / `glob` / `grep` 调用自动折叠为摘要，减少刷屏
- **运行时上下文注入** — Claude 风格 `currentDate` user context，处理“今天 / 最新 / 近期”时无需先探测系统日期
- **联网搜索与抓取** — 通过博查 API 的 `web_search` 获取实时搜索结果，`web_fetch` 支持 URL 校验、HTTPS 升级、缓存、超时/大小限制、页面提取与压缩
- **联网工具预算与收敛** — 每 turn 限制 `web_search` / `web_fetch` 调用预算，预算耗尽后要求基于已有来源回答或说明不确定
- **Shell / PowerShell 权限分级** — Shell prompt 强调专用工具优先，`date` / `Get-Date` 等只读命令低风险处理，危险参数拒绝
- **并发工具执行** — 对只读且安全的工具调用按批次并发执行，`ZZCODE_MAX_TOOL_CONCURRENCY` 控制最大并发数

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- 一个 OpenAI-compatible 的 LLM 接口（API key、base URL、model ID）

### 配置

```bash
# 克隆项目
git clone <repo-url>
cd ZzCode

# 配置 LLM（创建 .env 文件或导出环境变量）
export LLM_MODEL_ID="your-model"
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://your-endpoint/v1"

# 可选：关闭流式输出（默认开启）
export ZZCODE_STREAM=0

# 可选：启用联网搜索（需要博查 API key）
export BOCHA_API_KEY="your-bocha-api-key"

# 可选：将 debug 日志输出到 stderr
export ZZCODE_DEBUG_TO_STDERR=1
```

### 启动

```bash
# 启动终端 UI
cd frontend && npm install && npm run build && npm start
```

## 整体架构

```
终端 UI（React + Ink）
  → JSON Lines 协议（stdin/stdout）
  → Python Agent 核心（ToolCallAgent）
  → LLM 接口（OpenAI-compatible，支持 SSE 流式）
  → 结构化工具注册与执行（ToolRegistry + ToolRunner，安全只读工具可并发）
  → 本地工具、MCP 工具、联网工具、子 Agent
```

### 项目结构

```
ZzCode/
├── frontend/                     React + Ink 终端 UI
│   └── src/
│       ├── protocol/             事件类型定义、Python Agent 桥接
│       ├── screens/              REPL 状态管理（reducer）
│       ├── components/
│       │   ├── input/            BaseTextInput、Cursor、useTextInput
│       │   ├── messages/         MessageRow、MarkdownMessage、CollapsedToolGroup
│       │   ├── prompt/           PromptInput（历史记录、撤销、多行）
│       │   └── tools/            ToolBlock、ToolResultView
│       └── app/                  主题、App 根组件
├── src/zzcode/                   Python Agent 核心
│   ├── agent/                    ToolCallAgent、上下文预算、工具并发执行
│   ├── context/                  运行时 user context（当前日期等）
│   ├── llm/                      OpenAI-compatible 客户端（chat + stream）
│   ├── memory/                   Markdown 记忆、会话作用域
│   ├── mcp/                      MCP 配置、stdio 连接
│   ├── protocol/                 JSON Lines server、事件写入器
│   ├── subagents/                结构化子 Agent runner、受限工具
│   ├── tools/                    工具注册、执行、内置工具、安全检查
│   │   └── local/                本地工具（文件系统、搜索、Shell、web 搜索/抓取）
│   └── ui/                       UI 消息类型、渲染器
├── docs/                         各阶段设计文档与参考
├── tests/                        行为测试
└── .zzcode/                      会话数据、记忆文件、MCP 配置
```

## 学习路线

ZzCode 按阶段推进，每个阶段增加一项能力，设计决策记录在独立文档中。

| 阶段 | 主题 | 文档 |
|------|------|------|
| 1 | ReAct + Tool Call 最小闭环 | `docs/phase-01-react-toolcall-demo.md` |
| 2 | Memory 记忆系统（Markdown + 会话） | `docs/phase-02-memory-system.md` |
| 3 | Subagents 子 Agent（用户 + 系统） | `docs/phase-03-subagents.md` |
| 4 | 结构化工具层 | `docs/phase-04-tools-layer.md` |
| 5 | MCP 工具来源接入 | `docs/phase-05-mcp-layer.md` |
| 8 | 结构化子 Agent + 流式输出 | `docs/phase-08-structured-subagents.md` |
| 9 | Claude 上下文、搜索和 Shell 策略对齐 | `docs/phase-09-claude-context-search-shell-alignment.md` |

> 阶段 6–7 已并入阶段 3 和阶段 4 的工作流。阶段 9 为当前里程碑。

## MCP 配置

在项目根目录创建 `.zzcode/mcp.json`：

```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "python3",
      "args": ["server.py"],
      "env": {},
      "enabled": true,
      "timeout_seconds": 30
    }
  }
}
```

MCP 工具会以 `mcp__<server>__<tool>` 的命名注册到工具注册表，与内置工具共享同一套权限流程。

### 当前 MCP 限制

- 仅支持 `stdio` transport（暂不支持 SSE/HTTP）
- 仅读取当前项目的 `.zzcode/mcp.json`（不向父目录扫描）
- MCP resources 需通过 `list_mcp_resources` / `read_mcp_resource` 显式访问
- 暂不支持 binary/blob 类型 resource

## 输入系统

ZzCode 的输入系统参考了 Claude Code 的设计：

- **列宽感知光标** — 光标位置基于视觉列宽（`stringWidth`）计算，而非字符偏移量，正确处理 CJK 字符和 emoji
- **逐行独立渲染** — 每个视觉行是独立的 `<Text>` 元素，避免终端对 `\n` 拼接内容做二次折行
- **Viewport 滚动** — 多行输入最多显示 10 行，超出后自动启用 viewport，光标所在行始终可见
- **快捷键** — Enter 提交、Shift+Enter 换行、Ctrl+A/E/U/K 行操作、上下键浏览历史、Ctrl+_ 撤销
- **粘贴检测** — 基于字符量和换行符的启发式粘贴检测（80ms 累积窗口），大段粘贴合并为单次事件

## 开发

```bash
# Python 测试
python -m pytest tests/ -v

# 前端开发模式（热重载）
cd frontend && npm run dev

# 前端类型检查
cd frontend && npx tsc -p tsconfig.json --noEmit
```

## 文档索引

- [AGENTS.md](AGENTS.md) — 项目协作规则、架构约定和代码风格
- [docs/phase-01-react-toolcall-demo.md](docs/phase-01-react-toolcall-demo.md) — 阶段 1：ReAct + Tool Call
- [docs/phase-02-memory-system.md](docs/phase-02-memory-system.md) — 阶段 2：Memory 系统
- [docs/phase-03-subagents.md](docs/phase-03-subagents.md) — 阶段 3：Subagents
- [docs/phase-03-claude-subagents-reference.md](docs/phase-03-claude-subagents-reference.md) — Claude Code 子 Agent 实现参考
- [docs/phase-04-tools-layer.md](docs/phase-04-tools-layer.md) — 阶段 4：结构化工具层
- [docs/phase-04-claude-tools-reference.md](docs/phase-04-claude-tools-reference.md) — Claude Code 工具层实现参考
- [docs/phase-05-mcp-layer.md](docs/phase-05-mcp-layer.md) — 阶段 5：MCP 接入
- [docs/phase-05-claude-mcp-reference.md](docs/phase-05-claude-mcp-reference.md) — Claude Code MCP 实现参考
- [docs/phase-08-structured-subagents.md](docs/phase-08-structured-subagents.md) — 阶段 8：结构化子 Agent + 流式输出
- [docs/phase-09-claude-context-search-shell-alignment.md](docs/phase-09-claude-context-search-shell-alignment.md) — 阶段 9：Claude 上下文、搜索和 Shell 策略对齐

## License

MIT
