# 第二阶段：Claude Code 风格 Memory System

## 阶段目标

第二阶段把 ZzCode 当前的短期 `session_history` 升级为 Claude Code 风格的记忆系统。

本阶段不采用 HelloAgents 的 Qdrant、Neo4j、Embedding、MemoryManager 数据库路线，而是优先参考 Claude Code 的实现方式：

```text
Markdown memory files
-> context loader
-> prompt context injection
-> /memory editor command
-> session memory
-> compact support
```

核心目标：

1. 用 markdown 文件承载长期记忆和项目规则。
2. 每次请求前读取记忆文件，并作为上下文注入 Agent。
3. 提供 `/memory` 命令，让用户选择和编辑记忆文件。
4. 保留当前短期会话历史，作为工作上下文。
5. 后续增加 session memory updater，用于长会话总结和上下文压缩。

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

### Claude Code 后台记忆更新参考

Claude Code 还有两条后台更新链路，用于让 memory 文件随着对话推进自动变化。

#### Auto memory extraction

Claude Code 的 Auto memory 不只依赖主对话模型主动写文件。它还有一个后台提取器：

```text
stop hook
-> executeExtractMemories()
-> runForkedAgent(...)
-> 只允许读文件、搜索、只读 shell、以及 memory 目录内 Write/Edit
-> 写入 topic markdown 文件
-> 更新 MEMORY.md 索引
```

关键行为：

- 在完整 query loop 结束后触发。
- 用 `lastMemoryMessageUuid` 只处理上次提取之后的新消息。
- 如果主 Agent 已经写过 memory 文件，则跳过后台提取，避免重复。
- 先扫描已有 memory manifest，优先更新已有文件，避免重复创建。
- `MEMORY.md` 是索引，详细记忆写入独立 markdown 文件。
- 后台提取器是 forked agent，不阻塞主对话。

#### Session memory updater

Claude Code 会维护一个当前 session 专属 markdown notes 文件，用于长会话连续性和 compact。它会在后台用 forked agent 周期更新这个文件。

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

关键行为：

- 在 startup 阶段注册 post-sampling hook。
- 根据 token 增长、工具调用次数、自然停顿点判断是否更新。
- 更新前读取当前 notes 文件。
- 构建专用 update prompt。
- 通过 forked agent 只允许 `Edit` 当前 session memory 文件。
- 更新成功后记录 `lastSummarizedMessageId`，供 compact 判断哪些消息已经被 session memory 覆盖。

ZzCode 当前已经有 memory 文件结构、注入机制、权限边界和 transcript 记录，但还没有 Auto memory extraction worker，也没有 Session memory updater worker。

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

### 与 Claude Code 后台更新机制的差异

当前 ZzCode 和 Claude Code 在“memory 文件是否随对话自动更新”这一点上差异最大。

| 维度 | Claude Code | ZzCode 当前 |
| --- | --- | --- |
| Auto memory 写入 | 主 Agent 可以直接写；完整 query loop 结束后还有 `extractMemories` 后台 forked agent 兜底 | 主 Agent 只能按 prompt 自己调用普通文件工具写 `.zzcode/memory/`，没有后台提取器 |
| Auto memory 触发 | stop hook 触发，按新增消息游标处理 | 没有 stop hook 触发 |
| Auto memory 去重 | 后台提取器扫描已有 memory manifest，优先更新已有 topic 文件 | prompt 要求先读再改，但没有确定性去重流程 |
| Auto memory 权限 | forked agent 只允许读、搜索、只读 shell，以及 memory 目录内 Write/Edit | `.zzcode/memory/**/*.md` 自动允许，其他路径走原权限 |
| `MEMORY.md` 维护 | 后台提取器写详细文件后更新索引 | 依赖主 Agent 主动写详细文件并更新索引 |
| Session memory 更新 | post-sampling hook 按 token、工具调用次数和自然停顿点触发 | 只创建并读取当前 session summary 文件，没有 updater |
| Session memory 写入权限 | forked agent 只允许 Edit 当前 session memory 文件 | 当前 session memory markdown 自动允许，但没有后台 agent 使用 |
| compact 联动 | Session memory 更新 `lastSummarizedMessageId`，compact 可以保留未总结消息 | compact 只压缩进程内短期历史，尚未和 session summary/transcript 联动 |
| transcript | 作为恢复、compact、后台提取的基础记录 | 已写入结构化 `.zzcode/sessions/<session-id>/transcript.jsonl`，暂未被后台提取器消费 |

因此，ZzCode 当前如果 `.zzcode/memory/` 或 `.zzcode/sessions/<session-id>/session-memory/summary.md` 没有变化，通常代表主 Agent 没有主动调用文件工具；代码里还没有后台 worker 去确定性更新这些文件。

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

### Session Memory

当前 session 专属记忆，后续用于 compact。

建议路径：

```text
.zzcode/sessions/<session-id>/session-memory/summary.md
```

用途：

- 当前任务状态。
- 已完成步骤。
- 关键文件。
- 错误和修正。
- 后续 compact 的摘要来源。
- 默认新会话只读取当前 session 的 summary。

当前阶段已经创建 current session summary 文件并注入当前上下文；后台自动总结写为 TODO。

## 当前设计

### Memory 模块

```text
src/zzcode/
├── memory/
│   ├── __init__.py
│   ├── instruction.py
│   ├── loader.py
│   ├── context.py
│   ├── auto.py
│   ├── session.py
│   ├── session_scope.py
│   └── session_notes.py
```

职责：

- `instruction.py`：发现 User、Project、Rule、Local 指令记忆候选文件。
- `loader.py`：读取指令记忆，展开 rules，并处理 `@include`。
- `context.py`：把记忆文件拼成 prompt 上下文。
- `auto.py`：管理 `.zzcode/memory/MEMORY.md` 索引和受控长期记忆目录。
- `session.py`：管理当前进程内短期会话历史和基础 compact。
- `session_scope.py`：管理当前 sessionId、transcript 和 session memory 路径。
- `session_notes.py`：旧全局 session notes 兼容模块；JSONL 后端启用 sessionId 隔离后默认不再注入。

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
```

执行行为：

- `list`：列出已发现和可创建的记忆文件。
- `user`：打开或创建 `~/.zzcode/ZZCODE.md`。
- `project`：打开或创建 `./ZZCODE.md`。
- `local`：打开或创建 `./ZZCODE.local.md`。

说明：

- 旧版 `/memory session` 打开 `.zzcode/session/notes.md`，属于全局 session notes 兼容路径。
- JSONL 后端启用 sessionId 隔离后，当前 session summary 路径由后端创建为 `.zzcode/sessions/<session-id>/session-memory/summary.md`。
- 当前文档后续不再把旧 `/memory session` 作为新 session memory updater 的实现入口。

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

- 新增当前 session 专属 summary 文件。
- 路径为 `.zzcode/sessions/<session-id>/session-memory/summary.md`。
- 新会话只读取当前 session 的 summary，不自动携带旧 session summary。
- 当前阶段只创建、读取和注入，后台自动更新写为 TODO。

模板：

```text
# Session Title
# Current State
# Task Specification
# Files and Functions
# Workflow
# Errors & Corrections
# Learnings
# Key Results
# Worklog
```

验收：

- 新后端会话会创建当前 session summary 文件。
- 当前 session summary 非模板内容可以被注入上下文。
- 旧 session summary 不会进入新 session 上下文。
- 当前 session summary 路径会出现在 `Current session memory` 上下文中。

TODO：

- 参考 Claude Code 的 Session Memory updater。
- 在主对话采样后注册后台 updater。
- 后台 fork agent 读取 transcript 和当前 summary，更新 `.zzcode/sessions/<session-id>/session-memory/summary.md`。
- 子 Agent 只允许编辑当前 session summary 文件。
- 不允许它执行其他工具。
- 更新成功后记录类似 `lastSummarizedMessageId` 的边界，供 compact 使用。

验收留待子 Agent 阶段定义。

状态：

- 已完成：新增当前 session summary 默认模板。
- 已完成：JSONL 后端启动时创建 `.zzcode/sessions/<session-id>/session-memory/summary.md`。
- 已完成：memory context 会注入当前 session summary 路径和非模板内容。
- 已调整：旧 `.zzcode/session/notes.md` 不再作为 JSONL 后端新会话默认注入来源。
- 已完成：参考 Claude Code `SessionMemory/prompts.ts`，新增默认模板识别、section 体量分析、尺寸提醒和 compact 前 section 截断工具。
- 暂未实现：后台 Session Memory updater。

### Step 08：Compact 机制

当前状态：

- ZzCode 还没有 Claude Code 那种 transcript boundary 级别的上下文压缩机制。

目标：

- 当消息过长时，压缩当前进程内短期会话历史。
- 保留最近未总结消息。
- 避免切断 tool_use/tool_result 配对。

实现说明：

- Claude Code 的 compact 会在 transcript 中插入 compact boundary，并保留 boundary 后的消息段。
- Claude Code 的 Session Memory Compact 会读取 session memory 内容，作为压缩后的 summary 注入。
- ZzCode 当前会读取当前 session summary，但不包含后台 updater。
- ZzCode 当前有 JSONL transcript 事件记录，但 compact 尚未消费 transcript。
- ZzCode 当前还没有 Anthropic block 级 `tool_use/tool_result` 消息链。
- 因此第一版只压缩 `ShortTermSessionMemory` 中的完整 User/Assistant 文本项。
- 压缩只发生在完整文本项边界，不切断本轮 ReAct 内部工具调用过程。
- 当前 session summary 会在上下文构建时读取并注入；默认模板不注入正文。

验收：

- `/compact` 可以手动压缩 Python 后端短期会话历史。
- 每轮回答保存后，如果短期历史超过阈值，会自动压缩旧历史。
- 压缩后保留最近若干条 User/Assistant 历史。
- 旧历史以 `Compacted session summary` 形式继续注入上下文。
- 当前 session summary 中的非默认内容会以 `Current session memory` 形式注入上下文。

状态：

- 已完成第一版：`ShortTermSessionMemory` 支持手动压缩和阈值自动压缩。
- 已完成第一版：前端新增 `/compact` 命令，通过 JSONL 请求后端压缩当前短期历史。
- 已完成第一版：memory context 会注入当前 session summary 和 compact summary。
- 已调整：JSONL 后端启用 sessionId 隔离后，不再把旧 `.zzcode/session/notes.md` 注入新会话。
- TODO：后续有结构化 transcript 和后台 updater 后，再实现 Claude Code 风格的 compact boundary、session summary 联动和 tool block 级配对保护。

### Step 09：受控 Auto Memory 写入

背景：

- 仅实现 `ZZCODE.md` 读取和注入后，模型会把“请记住”理解为普通文件任务。
- 这会导致模型创建 `memory.txt`，或使用 `run_shell echo >> memory.txt` 追加内容。
- 该行为不符合 Claude Code 的 auto-memory 思路，也会触发普通文件/命令权限确认。

Claude Code 参考点：

- `CLAUDE.md` 指令记忆通过 `getMemoryFiles()` 发现和注入。
- `/memory` 是本地 UI 命令，负责让用户编辑记忆文件。
- auto-memory 通过系统提示告诉模型：有一个 persistent file-based memory system。
- 用户明确要求 remember 时，模型应写入受控 memory directory。
- `MEMORY.md` 是索引，详细记忆写入独立 markdown 文件。
- session memory 的后台 fork agent 只允许编辑指定 memory 文件，不允许任意工具。

目标：

- 新增 `.zzcode/memory/` 作为受控长期记忆目录。
- 新增 `.zzcode/memory/MEMORY.md` 作为索引文件。
- 让语义上的长期记忆请求进入受控 memory 写入流程。
- 禁止模型为记忆创建 `memory.txt` 或用 shell 追加。
- 长期记忆通过普通文件工具写入 `.zzcode/memory/`，但该目录内 markdown 写入自动允许。
- memory 目录外的文件继续保持原权限策略。

目录结构：

```text
.zzcode/memory/
├── MEMORY.md
├── user/
├── project/
├── feedback/
└── reference/
```

工具：

```text
read_file[path]
write_file[path|||content]
edit_file[path|||old_text|||new_text]
append_file[path|||content]
```

规则：

- 不注册专用 `memory_save` / `memory_read` 工具。
- Auto memory 只能通过普通文件工具访问 `.zzcode/memory/`。
- 详细记忆写入独立 markdown 文件，`MEMORY.md` 只维护索引。
- 更新已有记忆前优先 `read_file`，然后用 `edit_file` 或 `append_file` 增量修改。
- `.zzcode/memory/**/*.md` 的普通文件读写自动允许。
- `.zzcode/memory/` 外的文件继续走原权限确认。
- 触发保存记忆依赖用户语义意图，不依赖固定关键词。

验收：

- 用户表达需要长期保存偏好、事实、反馈或项目约定时，模型应使用普通文件工具更新 `.zzcode/memory/`。
- 同一 topic 后续更新时应保留旧内容，使用 `edit_file` 或 `append_file` 增量修改。
- 项目根目录不应生成 `memory.txt`。
- `.zzcode/memory/MEMORY.md` 应出现对应索引项。
- 下一轮请求时，`MEMORY.md` 索引以 `Auto memory index` 注入上下文。

状态：

- 已完成：新增受控 auto memory 目录和索引管理。
- 已完成：移除专用 memory 工具注册。
- 已完成：ReAct prompt 增加 memory mechanics，并改为语义触发。
- 已完成：新增 `edit_file` 和 `append_file` 普通文件能力。
- 已完成：memory context 注入 `Auto memory index`。
- 已完成：`.zzcode/memory/**/*.md` 的普通文件工具自动通过权限，memory 目录外保持原权限确认。
- 已完成：参考 Claude Code `scanMemoryFiles` / `formatMemoryManifest`，新增 auto memory manifest 扫描和格式化能力。
- 暂未实现：Claude Code 风格的 `extractMemories` 后台提取器。
- 暂未实现：基于 transcript 的后台去重、写入决策和索引维护。

### Step 10：Session 隔离和 Transcript 持久化

背景：

- 用户重新打开对话时，希望获得一段新的会话记忆。
- 旧对话历史需要保留在磁盘，后续用于 `/resume`、搜索或命令恢复。
- 本步骤先实现 Claude Code 的默认新会话边界，不实现命令恢复。

Claude Code 参考点：

- 默认启动是新 session，不自动加载旧 transcript。
- `--continue`、`--resume`、`/resume` 才会读取旧 session。
- transcript 按 session 写入 JSONL 文件。
- Session Memory 路径按 `sessionId` 隔离：`{projectDir}/{sessionId}/session-memory/summary.md`。
- Session Memory 后台 updater 只允许编辑当前 session 的 summary 文件。

ZzCode 目录结构：

```text
.zzcode/
└── sessions/
    └── <session-id>/
        ├── transcript.jsonl
        └── session-memory/
            └── summary.md
```

规则：

- 每次 JSONL 后端启动都生成新的 `sessionId`。
- 新会话只读取当前 `sessionId` 下的 `session-memory/summary.md`。
- 旧 session 的 transcript 和 summary 文件保留在磁盘。
- 旧 session 不参与默认上下文构建。
- `.zzcode/session/notes.md` 不再作为 JSONL 后端新会话的默认注入来源。
- transcript 记录 user、assistant、tool_use、tool_result 事件。
- transcript 事件包含 `eventId`、`parentEventId`、`logicalParentEventId`、`turnId`、`sequence`。
- compact 会写入 `compact_boundary` 和 `compact_summary` 事件。
- 当前阶段不实现 `/resume`、`/continue`、历史搜索和后台 Session Memory updater。

权限：

- `.zzcode/memory/**/*.md` 仍按长期 Auto Memory 规则自动允许。
- `.zzcode/sessions/<current-session-id>/session-memory/**/*.md` 自动允许。
- `.zzcode/sessions/<current-session-id>/transcript.jsonl` 自动允许。
- 旧 session 目录不自动允许。
- 其他项目文件保持原权限策略。

验收：

- 后端每次启动会创建新的 `.zzcode/sessions/<session-id>/`。
- 当前请求会写入当前 session 的 `transcript.jsonl`。
- 当前上下文包含当前 session summary 路径。
- 旧 session summary 不会进入新 session 上下文。
- 旧 transcript 和旧 summary 文件不会被删除。

状态：

- 已完成：新增 `SessionScope` 和 `TranscriptRecorder`。
- 已完成：JSONL 后端启动时创建当前 session。
- 已完成：每轮记录 user、assistant、tool_use、tool_result。
- 已完成：transcript 事件增加 `eventId`、`parentEventId`、`logicalParentEventId`、`turnId`、`sequence`。
- 已完成：同一轮用户请求的 user、tool_use、tool_result、assistant 归入同一个 `turnId`。
- 已完成：compact 写入 `compact_boundary` 和 `compact_summary`，boundary 断开父链并保留 logical parent。
- 已完成：memory context 注入当前 session summary，并跳过旧全局 session notes。
- 已完成：权限层增加当前 session 目录边界。
- 暂未实现：后台 Session Memory updater。
- 暂未实现：当前 session summary 与 compact 的 `lastSummarizedMessageId` 类边界联动。

## 验收标准

第二阶段前半部分完成时，需要满足：

1. ZzCode 能发现并读取 markdown 记忆文件。
2. User、Project、Local 记忆有明确路径。
3. 记忆内容能注入 Agent prompt。
4. 当前短期 `session_history` 能继续工作。
5. `/memory list` 能展示记忆文件状态。
6. `/memory user/project/local` 能创建并编辑指令记忆文件。
7. debug 日志能解释加载了哪些记忆文件和上下文大小。
8. `/compact` 能压缩当前短期会话历史。
9. 语义上的长期记忆请求能写入 `.zzcode/memory/`，而不是创建 `memory.txt`。
10. 新后端会话只注入当前 session memory，不自动携带旧 session memory。
11. 当前 session transcript 能保留在 `.zzcode/sessions/<session-id>/transcript.jsonl`。
12. README 只保留项目展示和总体框架，不写具体实现方法。

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
- Auto memory 后台 updater。
- Session memory 后台 updater。
- `/resume`、`/continue` 和历史 session 搜索命令。
- Agent 专属记忆。
- 结构化 Claude tool_use 协议。

## 设计原则

1. 先做 markdown 记忆文件，不做数据库。
2. 先做主 Agent 按语义写入 Auto Memory，不声称已完成后台 updater。
3. 先注入完整可控上下文，不做向量检索。
4. 先保持 Agent 架构稳定，不为了记忆系统重写 ReAct。
5. 先让记忆可见、可调试、可手动修正。
