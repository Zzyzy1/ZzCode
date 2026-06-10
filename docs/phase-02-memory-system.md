# 第二阶段：Claude Code 风格 Memory System

## 阶段目标

第二阶段把 ZzCode 当前的短期 `session_history` 升级为 Claude Code 风格的记忆系统。

本阶段不采用 HelloAgents 的 Qdrant、Neo4j、Embedding、MemoryManager 数据库路线，而是优先参考 Claude Code 的实现方式：

```text
Markdown memory files
-> context loader
-> prompt context injection
-> /memory editor command
-> session notes
-> compact support
```

核心目标：

1. 用 markdown 文件承载长期记忆和项目规则。
2. 每次请求前读取记忆文件，并作为上下文注入 Agent。
3. 提供 `/memory` 命令，让用户选择和编辑记忆文件。
4. 保留当前短期会话历史，作为工作上下文。
5. 后续增加 session notes，用于长会话总结和上下文压缩。

子 Agent 相关记忆先写为 TODO。ZzCode 还没有子 Agent，不在本阶段前半部分实现。

## Claude Code 记忆系统要点

Claude Code 的记忆不是单一数据库，而是多层上下文系统。

### 指令记忆

Claude Code 会读取多种 markdown 记忆文件：

```text
Managed memory: /etc/claude-code/CLAUDE.md
User memory: ~/.claude/CLAUDE.md
Project memory: ./CLAUDE.md, ./.claude/CLAUDE.md, ./.claude/rules/*.md
Local memory: ./CLAUDE.local.md
Auto memory: 自动记忆入口
Team memory: 团队共享记忆入口
```

这些文件会被拼接成 user context，再通过类似 `<system-reminder>` 的隐藏上下文注入模型。

关键思想：

- 记忆首先是可读、可编辑的 markdown。
- 项目规则和用户偏好直接进入 prompt。
- 文件越接近当前工作目录，优先级越高。
- 本地私有记忆和项目共享记忆分开。
- 记忆文件可以使用 `@path` include 其他文本文件。

### `/memory` 命令

Claude Code 的 `/memory` 命令不是模型工具，而是一个本地 UI 命令。

它做的事情：

1. 列出可编辑的记忆文件。
2. 如果文件不存在，则创建。
3. 用 `$VISUAL` 或 `$EDITOR` 打开。
4. 编辑结束后清理记忆缓存。
5. 下一次请求重新读取记忆文件并注入上下文。

ZzCode 第二阶段也优先采用这个思路，而不是一开始让模型主动调用 `memory` 工具。

### Session Memory

Claude Code 还有一层会话笔记，用于长会话连续性和 compact。

它会维护一个 markdown 文件，结构类似：

```text
# Session Title
# Current State
# Task specification
# Files and Functions
# Workflow
# Errors & Corrections
# Codebase and System Documentation
# Learnings
# Key results
# Worklog
```

Claude Code 会在后台用 forked agent 更新这个文件。ZzCode 当前没有子 Agent，所以本阶段只预留结构和 TODO，不实现后台子 Agent 总结。

## 当前 ZzCode 状态

当前 ZzCode 有一个轻量短期上下文机制：

```text
src/zzcode/protocol/server.py
└── session_history: list[str]
```

行为：

- 每次成功回答后保存 `User: ...` 和 `Assistant: ...`。
- 最多保留 12 条，大约 6 轮对话。
- 下一轮请求时通过 `session_context` 注入 `TextReActAgent.run()`。
- `/clear` 会清空。
- 后端进程退出后丢失。

这个机制可以保留，作为 Claude Code 风格系统里的 working context。第二阶段重点不是立刻删除它，而是把它从唯一记忆来源降级为“当前会话上下文”。

## ZzCode 目标记忆分层

### User Memory

用户级记忆，跨项目生效。

建议路径：

```text
~/.zzcode/ZZCODE.md
```

用途：

- 用户偏好。
- 用户身份、技术背景。
- 用户常用工作方式。
- 用户对 ZzCode 的长期要求。

### Project Memory

项目级共享记忆。

建议路径：

```text
./ZZCODE.md
./.zzcode/ZZCODE.md
./.zzcode/rules/*.md
```

用途：

- 项目结构说明。
- 编码规则。
- 工具使用约定。
- 当前项目的长期背景。

### Local Memory

本地私有项目记忆。

建议路径：

```text
./ZZCODE.local.md
```

用途：

- 当前机器路径。
- 用户本地环境。
- 不适合提交到仓库的项目备注。

### Session History

会话内短期上下文。

来源：

```text
server.py session_history
```

用途：

- 最近几轮对话。
- 本轮任务的短期连续性。
- 不持久化。

### Session Notes

长会话笔记，后续用于 compact。

建议路径：

```text
.zzcode/session/notes.md
```

用途：

- 当前任务状态。
- 已完成步骤。
- 关键文件。
- 错误和修正。
- 后续 compact 的摘要来源。

当前阶段先手动或命令触发，子 Agent 自动总结写为 TODO。

## 最小设计

### 新增模块

```text
src/zzcode/
├── memory/
│   ├── __init__.py
│   ├── files.py
│   ├── context.py
│   └── session_notes.py
```

职责：

- `files.py`：发现、读取、创建记忆文件。
- `context.py`：把记忆文件拼成 prompt 上下文。
- `session_notes.py`：管理 session notes 文件和模板。

暂不创建复杂 `MemoryItem`、`WorkingMemory`、`EpisodicMemory` 数据模型。Claude Code 路线的第一步是 markdown context，而不是数据库记忆。

### 记忆文件发现顺序

ZzCode 第一版可采用：

```text
1. User memory: ~/.zzcode/ZZCODE.md
2. Project memory: 从项目根到当前目录逐级加载 ZZCODE.md 和 .zzcode/ZZCODE.md
3. Project rules: .zzcode/rules/*.md
4. Local memory: ZZCODE.local.md
```

加载顺序保持低优先级到高优先级。拼接时后加载内容靠后，让模型更关注更具体的规则。

当前 ZzCode 以前端 `cwd` 启动 Python 后端，项目根优先使用：

```text
ZZCODE_PROJECT_ROOT
```

后续如果支持多工作目录，再扩展发现逻辑。

### 记忆上下文格式

注入给 Agent 的上下文建议保持稳定：

```text
Memory context:
Codebase and user instructions are shown below. Follow them when relevant.

Contents of /path/to/ZZCODE.md (user memory):

...

Contents of /path/to/.zzcode/ZZCODE.md (project memory):

...

Recent session:
User: ...
Assistant: ...
```

然后继续通过 `TextReActAgent.run(question, session_context=...)` 注入。

第一版不改 Agent 架构，只替换 `session_context` 的构建来源。

### Include 规则

Claude Code 支持 `@path` include。ZzCode 可以分两步：

第一步：

- 不实现 include。

第二步：

- 支持 `@./relative.md`。
- 只允许文本文件。
- 防止循环 include。
- 不存在文件静默忽略或输出 debug。

### `/memory` 命令

ZzCode 前端增加本地命令：

```text
/memory
```

第一版可先显示记忆文件列表和路径，不强制做复杂 UI。

候选子命令：

```text
/memory list
/memory user
/memory project
/memory local
/memory session
```

执行行为：

- `list`：列出已发现和可创建的记忆文件。
- `user`：打开或创建 `~/.zzcode/ZZCODE.md`。
- `project`：打开或创建 `./ZZCODE.md`。
- `local`：打开或创建 `./ZZCODE.local.md`。
- `session`：打开或创建 `.zzcode/session/notes.md`。

打开编辑器可以先由 Python 后端处理，也可以由前端 Node 侧处理。第一版优先选择实现简单、不会破坏 JSONL 协议的方案。

### 调试信息

保留当前 `[zzcode memory]` 调试日志，但内容改成 Claude Code 风格：

```text
[zzcode memory] loaded file type=user path=... chars=...
[zzcode memory] loaded file type=project path=... chars=...
[zzcode memory] context files=3 chars=2400 session_items=6
[zzcode memory] memory cache cleared
```

前端继续把这类日志转成 `system_notice`，不要直接写 stderr 干扰 Ink UI。

## 分步待办

### Step 01：定义指令记忆候选文件

目标：

- 新增 `src/zzcode/memory/instruction.py`。
- 定义 User、Project、Rule、Local 四类指令记忆候选文件。
- 返回路径、类型、作用域、优先级、是否应提交仓库、是否存在等元信息。
- 暂不读取文件内容。

验收：

- 没有记忆文件时不报错。
- 给定 `project_root` 后能稳定列出所有候选位置。
- 候选文件按低优先级到高优先级排序。
- 能标记候选文件或 rules 目录当前是否存在。

状态：

- 已完成。

### Step 02：实现 Memory Loader

目标：

- 新增 `src/zzcode/memory/loader.py`。
- 基于 Step 01 的候选文件，读取已存在的指令记忆内容。
- 展开 `.zzcode/rules/*.md`，按文件名排序。
- 对单个文件应用长度限制，默认 40000 字符。
- 暂不支持 `@include`，暂不注入 prompt。

验收：

- 没有记忆文件时返回空列表。
- 存在 User、Project、Local 记忆时能读取内容并保持优先级顺序。
- rules 目录下只有 `.md` 文件会被读取。
- 超长文件会被截断并标记 `truncated=True`。

状态：

- 已完成。

### Step 03：支持 `@include` 文件引用

目标：

- 支持 memory 文件中的 `@./path.md`。
- 只读取安全的文本扩展名。
- 防止循环引用。
- 不存在文件静默忽略或输出 debug。

验收：

- `ZZCODE.md` 可以引用 `.zzcode/rules/python.md`。
- 循环引用不会卡死。
- 二进制文件不会被读入上下文。

状态：

- 已完成第一版：支持 `@./relative`，跳过代码块和行内代码，限制在允许根目录内。

### Step 04：记忆注入

目标：

- 新增 memory context builder。
- 把已加载的指令记忆拼成稳定上下文。
- 通过 `TextReActAgent.run(question, session_context=...)` 注入。
- 保持 Agent 架构不变。

验收：

- `ZZCODE.md` 中写入的规则能影响下一次回答。
- debug 日志显示加载文件数和上下文字数。
- 不影响当前 ReAct 输出解析。

状态：

- 已完成：新增 memory context builder，并在 JSONL 后端请求前加载和注入指令记忆。

### Step 05：实现 `/memory` 命令

目标：

- 前端支持 `/memory list`。
- 支持 `/memory user`、`/memory project`、`/memory local`。
- 文件不存在时创建。
- 使用 `$VISUAL`、`$EDITOR` 或默认编辑器打开。

验收：

- 用户能看到当前 ZzCode 会读取哪些记忆文件。
- 用户可以通过命令编辑 `~/.zzcode/ZZCODE.md`。
- 编辑后下一次请求重新加载记忆。
- 不破坏 Ink UI 和 JSONL stdout。

状态：

- 已完成第一版：前端本地处理 `/memory list`、`/memory user`、`/memory project`、`/memory local`。

### Step 06：当前会话短期记忆

目标：

- 保留当前 `session_history` 作为 recent session。
- 把短期会话历史并入 memory context。
- 明确它不持久化，后端退出后丢失。

验收：

- 原来的“张三、李四、王五”短期记忆测试仍然可用。
- `/clear` 仍然能清空当前会话短期记忆。

状态：

- 已完成：新增 `ShortTermSessionMemory` 封装当前进程内最近 User/Assistant 历史，后端继续通过 memory context 注入。

### Step 07：Session Memory Markdown

目标：

- 新增 `.zzcode/session/notes.md` 模板。
- 支持 `/memory session` 打开 session notes。
- 暂时由用户手动编辑。

模板：

```text
# Session Title
# Current State
# Task Specification
# Files and Functions
# Workflow
# Errors & Corrections
# Learnings
# Worklog
```

验收：

- session notes 可以被创建和打开。
- session notes 可以被注入上下文，或作为后续 compact 预留文件。

TODO：

- 子 Agent 实现后，参考 Claude Code 的 Session Memory。
- 后台 fork 子 Agent，读取对话，更新 `.zzcode/session/notes.md`。
- 子 Agent 只允许编辑 session notes 文件。
- 不允许它执行其他工具。

验收留待子 Agent 阶段定义。

状态：

- 已完成第一版：新增 `.zzcode/session/notes.md` 默认模板。
- 已完成第一版：`/memory session` 可以创建并打开 session notes，已存在内容不会被覆盖。
- 暂未实现自动总结；后续等子 Agent 和 Compact 机制接入。

### Step 08：Compact 机制

当前状态：

- ZzCode 还没有 Claude Code 那种 transcript boundary 级别的上下文压缩机制。

目标：

- 当消息过长时，用 session notes 作为 compact summary。
- 保留最近未总结消息。
- 避免切断 tool_use/tool_result 配对。

实现说明：

- Claude Code 的 compact 会在 transcript 中插入 compact boundary，并保留 boundary 后的消息段。
- Claude Code 的 Session Memory Compact 会读取 session memory 内容，作为压缩后的 summary 注入。
- ZzCode 当前还没有结构化 transcript，也没有 Anthropic block 级 `tool_use/tool_result` 消息。
- 因此第一版只压缩 `ShortTermSessionMemory` 中的完整 User/Assistant 文本项。
- 压缩只发生在完整文本项边界，不切断本轮 ReAct 内部工具调用过程。
- session notes 会在上下文构建时读取并注入；默认空模板不注入。

验收：

- `/compact` 可以手动压缩 Python 后端短期会话历史。
- 每轮回答保存后，如果短期历史超过阈值，会自动压缩旧历史。
- 压缩后保留最近若干条 User/Assistant 历史。
- 旧历史以 `Compacted session summary` 形式继续注入上下文。
- `.zzcode/session/notes.md` 中的非默认内容会以 `Session memory notes` 形式注入上下文。

状态：

- 已完成第一版：`ShortTermSessionMemory` 支持手动压缩和阈值自动压缩。
- 已完成第一版：前端新增 `/compact` 命令，通过 JSONL 请求后端压缩当前短期历史。
- 已完成第一版：memory context 会注入 session notes 和 compact summary。
- TODO：后续有结构化 transcript 和子 Agent 后，再实现 Claude Code 风格的 compact boundary、自动摘要更新和 tool block 级配对保护。

## 验收标准

第二阶段前半部分完成时，需要满足：

1. ZzCode 能发现并读取 markdown 记忆文件。
2. User、Project、Local 记忆有明确路径。
3. 记忆内容能注入 Agent prompt。
4. 当前短期 `session_history` 能继续工作。
5. `/memory list` 能展示记忆文件状态。
6. `/memory user/project/local/session` 能创建并编辑记忆文件。
7. debug 日志能解释加载了哪些记忆文件和上下文大小。
8. `/compact` 能压缩当前短期会话历史。
9. README 只保留项目展示和总体框架，不写具体实现方法。

## 暂不实现

以下内容不在第二阶段前半部分实现：

- RAG。
- Qdrant。
- Neo4j。
- Embedding。
- HelloAgents 风格 `MemoryItem` 数据库。
- 语义检索。
- 团队记忆同步。
- 子 Agent 自动总结。
- compact。
- Agent 专属记忆。
- 结构化 Claude tool_use 协议。

## 设计原则

1. 先做 markdown 记忆文件，不做数据库。
2. 先做显式编辑，不做模型自动写记忆。
3. 先注入完整可控上下文，不做向量检索。
4. 先保持 Agent 架构稳定，不为了记忆系统重写 ReAct。
5. 先让记忆可见、可调试、可手动修正。
