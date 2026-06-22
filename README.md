# ZzCode

ZzCode 是一个用于学习现代 Code Agent 工作机制的 Python + React Ink 终端编程助手。

它不是为了直接复刻完整的 Claude Code，而是从一个可运行、可调试、可逐步扩展的最小 Agent 开始，分阶段理解终端智能体中的结构化工具调用、权限确认、上下文记忆、前后端协议和 TUI 交互。

![ZzCode terminal UI](docs/img/1.png)

## Overview

ZzCode 当前的核心形态是一个本地 Code Agent CLI：

```text
Terminal UI
  -> JSON Lines Protocol
  -> Python Agent Core
  -> LLM Provider
  -> Structured Tool Registry
  -> Local Tool Runner
```

前端负责终端交互和消息展示，后端负责 OpenAI-compatible `tool_calls` 主循环、模型调用、工具执行、权限确认、上下文管理和子 Agent 调度。两侧通过事件协议通信，便于后续继续扩展 Plan Mode、MCP 和更完整的多 Agent 能力。

## Capabilities

- OpenAI-compatible 结构化 tool call Agent 主循环
- OpenAI-compatible LLM 接入
- 本地文件、搜索和命令工具
- `glob` / `grep` 项目内文件定位和内容搜索
- React + Ink 终端 UI
- JSON Lines 前后端通信
- 工具执行前权限确认
- 用户拒绝破坏性工具后停止当前 turn，避免换工具绕过拒绝
- 多行输入和历史输入
- Markdown 风格记忆文件
- 当前会话短期记忆
- Session notes 和基础 Compact 支持
- 用户可调用 Subagents
- 系统 Subagents，用于 session memory 更新和 auto memory 提取
- MCP stdio server 接入，作为结构化工具来源

## Architecture

```text
ZzCode/
├── frontend/          React + Ink terminal UI
├── src/zzcode/        Python Agent core
│   ├── agent/         structured tool-call loop
│   ├── llm/           model provider adapter
│   ├── legacy/        temporary text ReAct compatibility
│   ├── memory/        markdown memory and context
│   ├── mcp/           MCP config, stdio connection and tool/resource adapters
│   ├── protocol/      JSON Lines backend
│   ├── subagents/     user and system subagents
│   └── tools/         structured local tool runtime
├── docs/              phase notes and design records
└── tests/             focused behavior tests
```

## Learning Roadmap

ZzCode 按阶段推进，每个阶段都优先让核心机制清晰可见：

1. ReAct + Tool Call 最小闭环
2. React + Ink 终端 UI 和 JSON Lines 协议
3. 工具权限确认和文件变更预览
4. Claude Code 风格 Markdown Memory
5. Session notes 和基础 Compact
6. Claude Code 风格 Subagents
7. Claude Code 风格结构化工具层
8. Plan Mode
9. MCP 接入

当前主链路已经切换到结构化 `ToolCallAgent`。早期文本 ReAct 实现仍保留在 legacy 边界中，主要用于阶段回顾和部分 subagents 临时兼容。

## MCP First Version

ZzCode 当前支持项目级 MCP 配置文件：

```text
.zzcode/mcp.json
```

配置结构：

```json
{
  "mcpServers": {
    "demo": {
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

第一版限制：

- 只支持 `stdio` transport。
- 只读取当前项目的 `.zzcode/mcp.json`，不向父目录扫描，也不读取 Claude Code 的 `.mcp.json`。
- MCP tools 会作为普通结构化工具进入 `ToolRegistry`，名称格式为 `mcp__server__tool`。
- MCP tool 默认需要权限确认；权限请求使用完整 MCP 工具名。
- MCP resources 只能通过 `list_mcp_resources` 和 `read_mcp_resource` 显式访问。
- resource 读取必须提供 `server` 和 `uri`；URI 不存在时只返回 MCP server 错误，不退化为本地 `glob`、`grep`、`find_file` 或 shell 搜索。
- binary/blob resource 当前不会以 base64 直接进入上下文，会返回明确的不支持结果。

## Documentation

- [AGENTS.md](AGENTS.md)：项目协作规则、架构约定和注释规范
- [docs/phase-01-react-toolcall-demo.md](docs/phase-01-react-toolcall-demo.md)：第一阶段 ReAct + Tool Call 学习记录
- [docs/phase-02-memory-system.md](docs/phase-02-memory-system.md)：第二阶段 Memory System 学习记录
- [docs/phase-03-subagents.md](docs/phase-03-subagents.md)：第三阶段 Subagents 学习记录
- [docs/phase-03-claude-subagents-reference.md](docs/phase-03-claude-subagents-reference.md)：Claude Code 子 Agent 实现参考摘录
- [docs/phase-04-tools-layer.md](docs/phase-04-tools-layer.md)：第四阶段结构化工具层实现方案
- [docs/phase-04-claude-tools-reference.md](docs/phase-04-claude-tools-reference.md)：第四阶段 Claude Code 工具层参考实现
- [docs/phase-05-mcp-layer.md](docs/phase-05-mcp-layer.md)：第五阶段 MCP 工具来源接入方案
- [docs/phase-05-claude-mcp-reference.md](docs/phase-05-claude-mcp-reference.md)：第五阶段 Claude Code MCP 实现参考

README 只保留项目展示和总体框架。具体设计取舍、实现步骤、验收记录和后续 TODO 放在 `docs/` 中维护。
