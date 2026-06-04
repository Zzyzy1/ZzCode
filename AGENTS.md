# ZzCode 协作说明

## 项目方向

ZzCode 是一个用于学习的 Python 版 Code Agent CLI。它的目标不是一开始就做成完整的 Claude Code，而是通过分阶段实现，逐步理解现代终端编程智能体背后的核心机制。

第一阶段只完成一个能跑通的 ReAct + Tool Call 命令行 demo。后续再逐步加入 MCP、Memory、RAG、Plan 模式、多 Agent、TUI 等能力。

这个项目会参考 PaiCLI、hello-agents、Claude Code 这类工具的思想，但不要照搬 PaiCLI 的 Java 包结构。Python 版本应该遵循更自然的 Python CLI 项目组织方式，保持模块小、边界清晰、便于阅读和调试。

## 架构约定

- 使用 Python 常见的 `src/` 项目布局。
- CLI 入口保持轻量，只负责加载配置、组装依赖、启动交互循环。
- Agent 主循环不要和终端渲染细节强耦合。
- 工具以注册表方式管理，后续 MCP 也作为工具来源接入。
- LLM Provider 通过统一的小接口隔离，避免业务逻辑直接依赖某个模型厂商。
- 早期学习阶段优先使用标准库，只有明显能降低复杂度时再引入第三方依赖。
- 每个阶段都在 `docs/` 下维护一篇说明文档，便于复盘学习过程。

## 当前目录规划

```text
ZzCode/
├── README.md
├── AGENTS.md
├── docs/
│   └── phase-01-react-toolcall-demo.md
├── src/
│   └── zzcode/
│       ├── cli/
│       ├── agent/
│       ├── llm/
│       ├── tools/
│       └── runtime/
└── tests/
```

## 阶段规划

1. 第一阶段：ReAct + Tool Call CLI demo。
2. 第二阶段：更安全的文件/命令工具、配置系统、基础测试。
3. 第三阶段：Plan 模式。
4. 第四阶段：Memory 与上下文管理。
5. 第五阶段：MCP 接入。

阶段顺序可以根据学习进度调整，但每个阶段都应该先明确目标和验收标准，再开始写代码。

## 协作规则

- 如果项目约定变化，需要同步更新本文件。
- 每个阶段都需要在 `docs/` 下新增或维护对应 Markdown 文档。
- 阶段文档应包含：目标、核心概念、最小设计、验收标准、暂不实现的内容。
- 当前阶段只做必要改动，避免在学习过程中引入大范围重构。
- 用户希望边做边学时，优先解释为什么这么设计，再进入实现。
