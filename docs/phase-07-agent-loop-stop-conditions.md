# Phase 07: Agent Loop Stop Conditions

## 目标

为结构化 `ToolCallAgent` 增加第一版主循环停止保护，避免依赖过小的固定步数，也避免上下文过长或工具失败时继续无效请求模型。

## 借鉴点

Claude Code 主循环不是默认固定 5 轮，而是持续执行 `model -> tool_use -> tool_result -> model`，直到没有工具调用、用户中断、达到显式 `maxTurns`、上下文保护线、预算或错误保护触发。

ZzCode 第一版保留简化实现：

- 无 `tool_calls` 时自然结束。
- 用户拒绝工具后停止当前 turn。
- 最大 turn 数改为 `ZZCODE_MAX_TURNS`，默认 20。
- 连续工具失败达到 3 次后停止。
- 请求前估算上下文 token，接近上限时尝试 compact，超过阻断线时停止。

## 验收标准

- 主 Agent 默认最大 turn 数不再写死 5。
- `ZZCODE_MAX_TURNS` 可以覆盖最大 turn 数。
- 连续结构化工具失败会停止当前 turn。
- 后端日志打印 turn 级和 step 级上下文预算。
- JSONL 后端在上下文接近上限时先尝试压缩短期历史。
- 压缩后仍超过阻断阈值时，不再调用 LLM。

## 暂不实现

- 不接入真实 tokenizer，继续使用 `len(text) // 4` 粗略估算。
- 不实现 Claude Code 的 usage.iterations 精确上下文统计。
- 不实现 transcript-based compact。
- 不重构为完整 `QueryEngine`。

## 相关环境变量

```text
ZZCODE_MAX_TURNS=20
ZZCODE_CONTEXT_WINDOW_TOKENS=128000
ZZCODE_RESERVED_OUTPUT_TOKENS=8000
ZZCODE_AUTO_COMPACT_BUFFER_TOKENS=12000
ZZCODE_BLOCKING_BUFFER_TOKENS=3000
```

## 前端手测建议

1. 普通多步任务：

```text
请阅读 README 和 docs 目录，概括当前 Agent 主循环、工具层和 MCP 层分别在哪里实现。
```

2. 验证最大 turn 日志：

```text
请逐步检查 src/zzcode 下 agent、tools、memory、mcp、protocol 目录的职责，每次只读一个目录相关文件，最后总结。
```

同时把 `ZZCODE_MAX_TURNS` 临时设小，例如 `3`，观察日志中的 `max_turns`。

3. 验证上下文预算日志：

```text
请阅读 README、AGENTS.md 和所有 docs/phase-*.md，然后总结每个阶段的目标和未完成事项。
```

观察 debug log 中的 `turn context budget` 和 `context budget step=...`。

4. 验证自动 compact 阈值：

将环境变量临时设小：

```text
ZZCODE_CONTEXT_WINDOW_TOKENS=3000
ZZCODE_RESERVED_OUTPUT_TOKENS=500
ZZCODE_AUTO_COMPACT_BUFFER_TOKENS=1500
ZZCODE_BLOCKING_BUFFER_TOKENS=300
```

然后连续提问几轮较长任务，观察是否出现“上下文接近上限，已自动压缩短期会话历史”。

5. 验证阻断线：

将环境变量进一步设小：

```text
ZZCODE_CONTEXT_WINDOW_TOKENS=1200
ZZCODE_RESERVED_OUTPUT_TOKENS=300
ZZCODE_AUTO_COMPACT_BUFFER_TOKENS=500
ZZCODE_BLOCKING_BUFFER_TOKENS=100
```

发送长问题，观察是否出现“上下文已经接近模型上限，已停止本轮请求”。
