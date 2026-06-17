# 第六阶段：日志系统方案

## 阶段目标

第六阶段按 Claude Code 的实现思路，补齐 ZzCode 的日志系统边界。

本阶段的重点不是“把后端打印直接显示到前端”，而是建立一套独立于 UI 展示链路的日志体系：

```text
业务代码
  -> 统一日志入口
  -> 按类型分流
  -> debug / error / transcript
  -> 独立持久化
  -> 需要时再选择是否输出 stderr
```

这一阶段不保留 ZzCode 现有“前端接管后端 stderr，并把部分内容转成前端提示”的实现思路作为主方案。

## 验收标准

完成第六阶段时，应满足：

1. ZzCode 有统一日志入口，而不是业务代码分散 `print()`。
2. 调试日志、错误日志、会话 transcript 分层管理，不混写。
3. `stdout` 继续只承载 JSON Lines 协议，不承载调试输出。
4. 默认调试日志落盘到独立全局日志目录，而不是默认进入前端 UI。
5. 错误日志具备结构化字段，至少包含时间、session、cwd 和错误内容。
6. 需要时可以显式切换为输出到 `stderr`，但这只是调试模式，不是默认链路。
7. 前端不再承担“后端调试日志查看器”的职责。

## 暂不实现

本阶段暂不做：

- 远程日志上报。
- telemetry / analytics 平台对接。
- 日志搜索 UI。
- Web 控制台查看器。
- 多进程集中聚合。
- 日志脱敏平台化处理。
- IDE 内嵌日志面板。

本阶段只先把本地日志边界、类型分层、持久化方式和查看路径打稳。

## Claude Code 参考实现

本节基于以下实现观察整理：

- `agent_learn/claude-code-sourcemap/restored-src/src/utils/debug.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/utils/log.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/utils/errorLogSink.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/utils/sessionStorage.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/services/PromptSuggestion/speculation.ts`

### 1. 调试日志有统一入口

Claude Code 不鼓励业务代码直接散落 `console.log`。

它提供统一入口：

```text
logForDebugging(message, { level })
```

这说明日志首先是“基础设施能力”，不是某个页面或某个进程局部处理的副作用。

统一入口带来的好处：

- 可统一控制开关。
- 可统一控制级别。
- 可统一控制输出目标。
- 可统一处理多行文本和格式问题。

### 2. 默认写文件，不默认进前端

Claude Code 的 debug 日志默认写到独立文件，路径由 `getDebugLogPath()` 决定，默认形态类似：

```text
~/.claude/debug/<sessionId>.txt
```

同时维护一个 `latest` 软链，方便直接查看最近日志。

这说明 Claude 的核心思路是：

- 调试日志属于运行时观测能力。
- 它应独立于 UI。
- 它应默认可落盘、可回看、可追溯。

而不是把“能否看到后端打印”绑定在前端是否愿意转发 `stderr`。

### 3. 只有显式开关时才写 stderr

Claude Code 支持显式参数把 debug 日志输出到 `stderr`，例如：

```text
--debug-to-stderr
```

这里的重点不是参数名本身，而是设计原则：

- `stderr` 是一种可选调试出口。
- 它不是默认主出口。
- 更不是协议主通道。

这和当前 ZzCode 的 JSON Lines 协议边界是一致的：协议输出必须稳定，调试输出不能污染协议流。

### 4. 调试日志支持过滤和级别

Claude Code 的 debug 能力不是单一开关，而是带过滤能力：

- `--debug`
- `--debug=pattern`
- `--debug-file`
- `CLAUDE_CODE_DEBUG_LOG_LEVEL`

日志级别至少区分：

```text
verbose
debug
info
warn
error
```

这说明 Claude 不是把“日志”理解成简单文本输出，而是把它视为一个可控观测面。

### 5. 调试日志使用缓冲写入

Claude Code 的调试日志写入不是每次直接裸写文件，而是通过 `BufferedWriter` 做缓冲。

其核心取舍是：

- 普通模式下降低频繁 IO。
- 调试模式下必要时同步写入，减少崩溃前日志丢失。
- 进程退出时统一 flush。

这个设计很适合 Agent 进程，因为：

- 工具调用多。
- 事件频率高。
- 长会话里日志量可能明显增长。

### 6. 错误日志和 debug 日志分层

Claude Code 不把所有错误都只当成 debug 文本。

它把错误日志抽成独立体系：

- `log.ts` 负责轻量接口和排队。
- `errorLogSink.ts` 负责真正落盘。

这里有两个关键点。

第一，初始化前错误不会直接丢失，而是先排队，等 sink 挂载后再 drain。

第二，错误日志写成结构化 JSONL，而不是仅仅拼接一行字符串。

典型路径类似：

```text
~/.claude/errors/<date>.jsonl
~/.claude/mcp-logs/<server>/<date>.jsonl
```

这说明 Claude 区分了：

- 方便人眼看的 debug 文本日志。
- 方便程序处理和归档的结构化错误日志。

### 7. 每条错误日志带运行上下文

Claude Code 在错误日志中会补充上下文字段，例如：

- `timestamp`
- `cwd`
- `sessionId`
- `version`

这类字段非常关键，因为它们让“日志”从一段打印文字升级为“可定位问题的运行记录”。

### 8. transcript 不是 debug log

Claude Code 还维护独立 session transcript，路径类似：

```text
<project session dir>/<sessionId>.jsonl
```

像 `speculation.ts` 里的事件会追加到 transcript，但 transcript 不等于 debug log。

这体现出第三层边界：

- `debug log` 用于开发调试。
- `error log` 用于异常记录。
- `transcript` 用于会话事实和恢复。

三者职责不同，不能混为一个文件或一个输出通道。

## Claude Code 参考原则

第六阶段只吸收 Claude Code 日志系统的核心思路：

1. 日志必须有统一入口，不能依赖零散 `print()`。
2. `stdout` 只承载协议或正式输出，不能混入调试日志。
3. 调试日志默认落盘，`stderr` 只作为显式调试出口。
4. debug、error、transcript 三类记录必须分层。
5. 错误日志尽量结构化，便于后续排查和扩展。
6. 日志写入要考虑缓冲、flush 和退出时机。
7. 前端 UI 负责展示用户需要看的信息，不负责承接全部后端调试输出。

不照搬 Claude Code 的复杂部分：

- ant 用户分层逻辑。
- telemetry / analytics 全链路。
- 软链、feature flag、隐私等级等生产细节。
- 大量平台专用分支。

## 对 ZzCode 的约束

### 旧实现不保留

ZzCode 当前已有一些后端调试信息写到 `stderr`，并由前端进程接管；部分带前缀的信息再被前端转换成 `system_notice`。

第六阶段不保留这种实现作为日志系统主方案。

原因：

1. 日志是否可见被绑定到前端运行方式，不稳定。
2. 日志无法天然持久化，回看成本高。
3. 前端被迫承担后端调试链路，边界不清。
4. 难以区分调试日志、错误日志和协议事件。
5. 后续接入更多能力后，日志噪声会明显增长。

## ZzCode 实现方案

第六阶段不做折中方案，直接按 Claude Code 的日志分层思路改造 ZzCode。

唯一明确调整的是日志目录不落到项目内，也不落到任何 `.zzcode` 路径中。

### 日志根目录

日志统一写到独立全局目录：

```text
Linux/macOS:
~/.local/state/zzcode/logs/

Windows:
%LOCALAPPDATA%/ZzCode/logs/
```

这条规则优先级高于项目内所有路径约定。

原因：

1. 日志不属于项目运行结果本身。
2. 日志不应该污染项目目录。
3. 跨项目调试时需要统一查看入口。
4. 后续错误归档、MCP 日志和调试日志都应集中管理。

### 目录结构

建议目录结构：

```text
logs/
  debug/
    <session_id>.log
    latest.log
  errors/
    <date>.jsonl
  mcp/
    <server_name>/
      <date>.jsonl
```

同时保留项目内原有会话态数据：

```text
<project>/.zzcode/
  sessions/<session_id>/transcript.jsonl
  sessions/<session_id>/session-memory/summary.md
  session/notes.md
  mcp.json
```

这里要明确区分：

- 全局日志目录存放运行时日志。
- 项目 `.zzcode` 只存放当前项目的配置、会话和运行产物。

### 三类记录分层

第六阶段把记录体系固定为三层。

#### 1. Debug Log

用于开发调试和运行时观测。

特点：

- 人类可读文本格式。
- 默认写入独立全局目录。
- 不默认显示在前端。
- 可按级别过滤。

#### 2. Error Log

用于错误归档和后续排查。

特点：

- JSONL 结构化格式。
- 一行一条记录。
- 带运行上下文。
- 与普通 debug 文本日志分离。

#### 3. Transcript

用于会话事实记录、恢复、compact、memory、subagent 链路回放。

特点：

- 继续保留现有 session transcript 设计。
- 继续放在项目内 `.zzcode/sessions/...`。
- 不和 debug / error log 混写。

### 模块拆分

建议新增：

```text
src/zzcode/logging/
├── __init__.py
├── debug.py
├── error_sink.py
├── paths.py
├── process.py
└── writer.py
```

模块职责：

```text
paths.py       解析全局日志根目录和各类日志文件路径
writer.py      提供缓冲写入、flush、关闭和 latest.log 维护
process.py     提供安全 stderr 输出和退出前清理
debug.py       提供统一 debug 入口、级别过滤、stderr 开关
error_sink.py  提供结构化 error / mcp error / mcp debug 写入
```

这里直接对标 Claude 的设计，不把日志逻辑散落在 `protocol/`、`llm/`、`mcp/` 等模块里。

### 统一日志入口

ZzCode 业务代码不再直接散落 `print(..., file=sys.stderr)`。

统一入口建议至少包括：

```text
log_debug(message, level="debug")
log_error(error, context=None)
log_mcp_error(server_name, error, context=None)
log_mcp_debug(server_name, message, context=None)
flush_debug_logs()
```

设计要求：

1. 所有 debug 信息都走 `log_debug()`。
2. 所有错误都走 `log_error()` 或 MCP 专用入口。
3. 多行文本进入 debug 前统一压缩或安全格式化。
4. 进程退出前统一 flush。

### 开关设计

对齐 Claude 的设计语义，提供显式开关。

建议支持：

```text
ZZCODE_DEBUG=1
ZZCODE_DEBUG_LEVEL=verbose|debug|info|warn|error
ZZCODE_DEBUG_TO_STDERR=1
ZZCODE_DEBUG_FILE=/absolute/path/to/file.log
```

行为约定：

1. 默认不把 debug 日志送到前端。
2. 开启 `ZZCODE_DEBUG=1` 后写 debug 文件。
3. 开启 `ZZCODE_DEBUG_TO_STDERR=1` 后，同时输出到 `stderr`。
4. `ZZCODE_DEBUG_FILE` 可覆盖默认 debug 文件路径。
5. 即使写 `stderr`，`stdout` 仍然只能承载 JSON Lines 协议。

### 写入策略

写入策略按 Claude 的思路实现，不采用每条日志直接裸写文件的方式。

要求：

1. debug 日志使用缓冲写入。
2. 普通模式允许批量 flush，减少频繁 IO。
3. 强调试模式可切换为更及时的写入。
4. 进程正常退出、异常退出钩子都要尝试 flush。
5. `latest.log` 始终指向最近一次 session 的 debug 文件。

如果平台不方便维护符号链接，则退化为复制或覆盖一个 `latest.log` 文件，但语义上仍然保持“最近一次会话日志入口”。

### 错误日志字段

错误日志写成 JSONL，每条至少包含：

- `timestamp`
- `level`
- `kind`
- `session_id`
- `cwd`
- `component`
- `message`
- `traceback`

MCP 相关额外字段：

- `server_name`
- `operation`

工具相关错误可额外补：

- `tool_name`
- `tool_args`

这一步的目标不是“日志更多”，而是让错误可以被精确定位。

### 现有代码迁移要求

#### 协议层

[`src/zzcode/protocol/server.py`](../src/zzcode/protocol/server.py) 中当前 `_debug_memory()`、`_debug_system_agents()` 这类直接写 `stderr` 的函数，不再保留现状。

迁移后要求：

- memory 调试信息改走统一 `log_debug()`
- system subagents 调试信息改走统一 `log_debug()`
- `protocol/server.py` 只负责 JSONL 协议，不再承担日志实现职责

#### LLM 层

[`src/zzcode/llm/client.py`](../src/zzcode/llm/client.py) 中当前模型调用、返回内容和异常的 `stderr print`，迁移为统一日志入口：

- 模型请求开始走 `log_debug()`
- 模型文本返回走 `log_debug()`
- HTTP 异常和调用异常走 `log_error()`

#### 前端桥接层

[`frontend/src/protocol/pythonAgent.ts`](../frontend/src/protocol/pythonAgent.ts) 当前会解析后端 `stderr`，并把部分内容转成 `system_notice`。

第六阶段后要求：

- 前端不再承担 debug 日志展示职责
- 前端只消费 JSONL 协议事件
- 后端 crash 或启动失败时，前端仍可展示错误摘要
- 常规 debug 日志改为去全局日志文件查看

#### MCP 层

当前 MCP 已有独立 stderr 文件思路，第六阶段要与统一日志系统收口：

- MCP debug 记录进入 `mcp/<server_name>/<date>.jsonl`
- MCP error 记录进入同目录结构
- 是否保留原始 stderr tail 作为补充信息，可后续单独决定

### 日志查看方式

修改完成后，日志查看位置固定如下。

#### Debug 日志

最近一次 session：

```text
Linux/macOS:
~/.local/state/zzcode/logs/debug/latest.log

Windows:
%LOCALAPPDATA%/ZzCode/logs/debug/latest.log
```

指定 session：

```text
Linux/macOS:
~/.local/state/zzcode/logs/debug/<session_id>.log

Windows:
%LOCALAPPDATA%/ZzCode/logs/debug/<session_id>.log
```

#### Error 日志

```text
Linux/macOS:
~/.local/state/zzcode/logs/errors/<date>.jsonl

Windows:
%LOCALAPPDATA%/ZzCode/logs/errors/<date>.jsonl
```

#### MCP 日志

```text
Linux/macOS:
~/.local/state/zzcode/logs/mcp/<server_name>/<date>.jsonl

Windows:
%LOCALAPPDATA%/ZzCode/logs/mcp/<server_name>/<date>.jsonl
```

#### Transcript

```text
<project>/.zzcode/sessions/<session_id>/transcript.jsonl
```

这个文件继续用于会话事件、compact、memory、subagent 记录，不用来替代 debug log。

### 本阶段文档结论

第六阶段的最终方向明确如下：

1. 学习 Claude Code 的分层日志设计，不走前端接管后端打印的旧路。
2. 日志统一进入独立全局目录，不进入任何 `.zzcode` 日志路径。
3. debug、error、transcript 三类记录严格分层。
4. `stdout` 保持纯协议输出。
5. 调试日志默认查看方式改为查看日志文件，而不是看前端终端输出。
