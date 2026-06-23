# Phase 08: Structured Subagents & Streaming Output

## Goals

Phase 08 migrated ZzCode's user and system subagents from the legacy text ReAct loop to the structured `tool_calls` agent loop, and added streaming text output for final answers. The frontend was also updated to properly handle the new event types and fix input rendering issues.

## What Changed

### Python Backend

**Structured Subagent Runner** (`src/zzcode/subagents/structured_runner.py`)
- New `StructuredSubagentRunner` uses `ToolCallAgent` for all subagent execution
- User subagents and system subagents share the same runner
- `SubagentEventRenderer` forwards subagent tool progress to the parent session as `subagent_start`, `subagent_tool_use`, `subagent_tool_result`, and `subagent_done` events
- System memory workers (`SessionMemoryUpdateWorker`, `AutoMemoryExtractionWorker`) migrated to structured tool calls — no more `Invalid Action format` errors

**Restricted Tool Registry** (`src/zzcode/subagents/restricted_tool_registry.py`)
- `RestrictedToolWrapper` enforces tool allow/deny lists and path-based read/write restrictions
- Wraps existing structured tools without duplicating logic

**Structured AgentTool** (`src/zzcode/tools/local/agent.py`)
- New structured `Tool` definition for subagent invocation
- JSON schema: `{"subagent_type": "string", "description": "string", "prompt": "string"}`
- Result compression: returns excerpt + transcript path, not full 8k+ output

**Streaming LLM Output** (`src/zzcode/llm/client.py`, `src/zzcode/agent/tool_call_agent.py`)
- `ZzCodeLLM.stream_chat()` — OpenAI-compatible SSE streaming
- `LLMStreamEvent` types: `content_delta`, `tool_call_delta`, `message_done`, `error`
- `ToolCallAgent` streams text deltas to the renderer while buffering tool call arguments
- Controlled by `ZZCODE_STREAM` env var (default: enabled)

**Protocol Events** (`src/zzcode/protocol/events.py`, `src/zzcode/ui/messages.py`)
- New events: `assistant_delta`, `subagent_start`, `subagent_tool_use`, `subagent_tool_result`, `subagent_done`
- `SubagentEventRenderer` translates subagent internal events for the frontend

**Legacy Removal**
- Deleted: `react_text.py`, `executor.py`, `forked_runner.py`, `user_runner.py`, `restricted_tool_executor.py`, `tool.py`
- All runtime paths now use structured `ToolCallAgent` + `ToolRegistry`

### TypeScript Frontend

**Streaming Display Fixes** (`events.ts`, `reducer.ts`, `MessageRow.tsx`, `Messages.tsx`)
- Added TypeScript types for all new event types: `AssistantDeltaEvent`, `SubagentStartEvent`, `SubagentToolUseEvent`, `SubagentToolResultEvent`, `SubagentDoneEvent`
- `reducer.ts`: consecutive `assistant_delta` events are merged into a single message; `assistant_final` / `assistant_thought` replace the preceding delta to avoid duplicate display
- `MessageRow.tsx`: specific render branches for `assistant_delta` ("⟳ Streaming..."), `subagent_start`, `subagent_tool_use` (ToolBlock), `subagent_done` ("✓/✗ Subagent completed/failed")
- `Messages.tsx`: `subagent_tool_result` merged into `subagent_tool_use` via `toolOutputById`

**Input Rendering Fixes** (`Cursor.ts`, `BaseTextInput.tsx`, `useTextInput.ts`, `textInputTypes.ts`)
- `Cursor.render()`: new column-width-based cursor positioning (iterates graphemes with `stringWidth` accumulation), replacing the old character-offset-based `slice()` approach that broke on CJK and wrap boundaries
- `BaseTextInput.tsx`: changed from single `<Text>` with `\n`-joined fragments to `<Box flexDirection="column">` with per-line `<Text>` elements, preventing Ink double-wrapping
- `Cursor.renderLines()`: fixed space-cursor duplication bug (`cursorChar === " "` special case removed)
- Viewport scrolling: `maxVisibleLines={10}` prevents multiline input from overflowing the terminal

## Verification

Manual test scenarios:
- ✅ User subagent (`general-purpose`) successfully calls structured tools with visible progress
- ✅ System memory workers run silently in the background, no `Invalid Action format`
- ✅ Streaming text: single streaming line updates in place, no token-by-token message spam
- ✅ `assistant_final` replaces deltas — no duplicate final answer
- ✅ Subagent progress: `subagent_start` → `subagent_tool_use` → `subagent_done` visible in UI
- ✅ Tool call collapsing: `read_file`/`glob`/`grep` groups preserved
- ✅ Input: cursor positioning correct on CJK characters and wrap boundaries
- ✅ Input: multiline (15+ lines) remains within viewport, doesn't push messages off screen
- ✅ Path-based permission restrictions enforced for subagent tools
- ✅ `ZZCODE_STREAM=0` disables streaming, falls back to non-streaming path

## Architecture After Phase 08

```
src/zzcode/
├── agent/
│   ├── context_budget.py
│   └── tool_call_agent.py          ← supports streaming + non-streaming
├── subagents/
│   ├── definition.py
│   ├── structured_runner.py        ← unified runner for all subagents
│   ├── restricted_tool_registry.py ← tool + path filtering
│   ├── system.py                   ← structured memory workers
│   └── transcript.py
├── tools/
│   ├── base.py
│   ├── registry.py
│   ├── runner.py
│   ├── results.py
│   ├── builtin.py
│   └── local/
│       └── agent.py                ← structured AgentTool
├── protocol/
│   ├── events.py                   ← JsonLineRenderer: all event types
│   └── server.py                   ← JSON Lines backend
├── llm/
│   └── client.py                   ← chat() + stream_chat()
└── ui/
    └── messages.py                 ← UiMessage types

frontend/src/
├── protocol/
│   └── events.ts                   ← all AgentEvent types
├── screens/
│   └── reducer.ts                  ← delta merge logic
├── components/
│   ├── messages/
│   │   ├── MessageRow.tsx          ← all event render branches
│   │   └── Messages.tsx            ← subagent result merging
│   └── input/
│       ├── Cursor.ts               ← column-based render()
│       ├── BaseTextInput.tsx       ← per-line <Text> rendering
│       ├── useTextInput.ts         ← cursorChar wiring
│       └── textInputTypes.ts       ← renderedLines
```

## Completion Criteria

1. ✅ Main agent, user subagent, and system subagent all use `ToolCallAgent`
2. ✅ All runtime tool calls go through `ToolRegistry` and `ToolRunner`
3. ✅ System agents no longer produce `Invalid Action format`
4. ✅ Legacy text ReAct and string-based tool layer removed from `src/`
5. ✅ Subagent progress visible in frontend
6. ✅ Final answer streaming with proper delta merging
7. ✅ Input rendering: column-based cursor, per-line Text elements, viewport limit
