# ZzCode

A terminal Code Agent CLI built with **Python + React Ink**, designed for learning how modern AI coding assistants work under the hood.

ZzCode is not a clone of Claude Code. It's a **from-scratch, incrementally built** agent — starting from a minimal runnable loop and progressively adding structured tool calling, permission checks, memory, subagents, MCP integration, and streaming output. Each phase is documented so you can trace the design decisions.

![ZzCode terminal UI](docs/img/1.png)

## Features

- **Structured tool-call agent loop** — OpenAI-compatible `tool_calls` with `ToolRegistry` + `ToolRunner`
- **Streaming output** — real-time `assistant_delta` text streaming with proper frontend delta merging
- **React + Ink terminal UI** — multiline input with column-aware cursor, per-line rendering, and viewport scrolling
- **Permission system** — tool execution requires user confirmation; destructive tools are always confirmed
- **Markdown memory files** — Claude Code-style `.zzcode/memory/` directory with auto-extraction
- **Short-term session memory** — compact/trim/auto-summarize with context budget awareness
- **Subagents** — user-callable (`general-purpose`) and system workers (memory update, auto-extraction)
- **MCP stdio support** — MCP servers as structured tool sources via `.zzcode/mcp.json`
- **JSON Lines protocol** — clean frontend/backend separation, easy to debug and extend
- **Collapsible tool groups** — consecutive `read_file`/`glob`/`grep` calls folded into summaries

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI-compatible LLM endpoint (API key, base URL, model ID)

### Setup

```bash
# Clone and install
git clone <repo-url>
cd ZzCode

# Configure LLM (create .env or export env vars)
export LLM_MODEL_ID="your-model"
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://your-endpoint/v1"

# Optional: enable streaming (default: on)
export ZZCODE_STREAM=1

# Optional: show debug logs in stderr
export ZZCODE_DEBUG_TO_STDERR=1
```

### Run

```bash
# Start the terminal UI
cd frontend && npm install && npm run build && npm start
```

## Architecture

```
Terminal UI (React + Ink)
  → JSON Lines Protocol (stdin/stdout)
  → Python Agent Core (ToolCallAgent)
  → LLM Provider (OpenAI-compatible, streaming SSE)
  → Structured Tool Registry + Runner
  → Local Tools, MCP Tools, Subagents
```

### Project Structure

```
ZzCode/
├── frontend/                    React + Ink terminal UI
│   └── src/
│       ├── protocol/            event types, Python agent bridge
│       ├── screens/             REPL state reducer
│       ├── components/
│       │   ├── input/           BaseTextInput, Cursor, useTextInput
│       │   ├── messages/        MessageRow, MarkdownMessage, CollapsedToolGroup
│       │   ├── prompt/          PromptInput (history, undo, multiline)
│       │   └── tools/           ToolBlock, ToolResultView
│       └── app/                 theme, App root
├── src/zzcode/                  Python agent core
│   ├── agent/                   ToolCallAgent, context budget
│   ├── llm/                     OpenAI-compatible client (chat + stream)
│   ├── memory/                  markdown memory, session scope
│   ├── mcp/                     MCP config, stdio connection
│   ├── protocol/                JSON Lines server, event writer
│   ├── subagents/               structured runner, restricted tools
│   ├── tools/                   registry, runner, builtins, safety
│   └── ui/                      message types, renderer
├── docs/                        Phase design notes and references
├── tests/                       Focused behavior tests
└── .zzcode/                     Session data, memory, MCP config
```

## Learning Roadmap

ZzCode is built in phases. Each phase adds one capability, and the design decisions are documented.

| Phase | Topic | Key Files |
|-------|-------|-----------|
| 1 | ReAct + Tool Call minimal loop | `docs/phase-01-react-toolcall-demo.md` |
| 2 | Memory system (markdown, session) | `docs/phase-02-memory-system.md` |
| 3 | Subagents (user + system) | `docs/phase-03-subagents.md` |
| 4 | Structured tool layer | `docs/phase-04-tools-layer.md` |
| 5 | MCP integration (stdio transport) | `docs/phase-05-mcp-layer.md` |
| 8 | Structured subagents + streaming | `docs/phase-08-structured-subagents.md` |

> Phases 6–7 were absorbed into the Phase 03 and Phase 04 work streams. Phase 8 is the current milestone.

## MCP Configuration

Place a `.zzcode/mcp.json` in your project root:

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

MCP tools appear in the tool registry as `mcp__<server>__<tool>` and follow the same permission flow as built-in tools.

### Current MCP Limitations

- `stdio` transport only (no SSE/HTTP)
- Project-local `.zzcode/mcp.json` only (no parent directory scanning)
- MCP resources accessible via explicit `list_mcp_resources` / `read_mcp_resource` calls
- Binary/blob resources not yet supported

## Input System

ZzCode's input system follows Claude Code's design:

- **Column-aware cursor** — cursor position based on visual column width (`stringWidth`), not character offset, correctly handling CJK characters and emoji
- **Per-line rendering** — each visual line is a separate `<Text>` element, preventing terminal double-wrapping
- **Viewport scrolling** — multiline input capped at 10 visible lines with automatic viewport centering
- **Keybindings** — Enter/Shift+Enter for submit/newline, Ctrl+A/E/U/K for line operations, Up/Down for history, Ctrl+_ for undo
- **Paste detection** — heuristic-based paste accumulation (80ms window) with separate paste events

## Development

```bash
# Python tests
python -m pytest tests/ -v

# Frontend dev mode (hot reload)
cd frontend && npm run dev

# Frontend type check
cd frontend && npx tsc -p tsconfig.json --noEmit
```

## Documentation

- [AGENTS.md](AGENTS.md) — project conventions, architecture rules, and code style
- [docs/phase-01-react-toolcall-demo.md](docs/phase-01-react-toolcall-demo.md) — Phase 1: ReAct + Tool Call
- [docs/phase-02-memory-system.md](docs/phase-02-memory-system.md) — Phase 2: Memory System
- [docs/phase-03-subagents.md](docs/phase-03-subagents.md) — Phase 3: Subagents
- [docs/phase-03-claude-subagents-reference.md](docs/phase-03-claude-subagents-reference.md) — Claude Code subagent reference
- [docs/phase-04-tools-layer.md](docs/phase-04-tools-layer.md) — Phase 4: Structured Tool Layer
- [docs/phase-04-claude-tools-reference.md](docs/phase-04-claude-tools-reference.md) — Claude Code tool layer reference
- [docs/phase-05-mcp-layer.md](docs/phase-05-mcp-layer.md) — Phase 5: MCP Integration
- [docs/phase-05-claude-mcp-reference.md](docs/phase-05-claude-mcp-reference.md) — Claude Code MCP reference
- [docs/phase-08-structured-subagents.md](docs/phase-08-structured-subagents.md) — Phase 8: Structured Subagents & Streaming

## License

MIT
