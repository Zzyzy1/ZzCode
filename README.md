# ZzCode

一个用于学习现代 Code Agent 工作机制的 Python + React Ink 终端编程助手。

ZzCode 的目标不是一开始就做成完整的 Claude Code，而是从最小 ReAct + Tool Call 循环开始，逐步理解终端智能体中的模型调用、工具执行、权限确认、事件协议和前端交互。

![ZzCode terminal UI](docs/img/1.png)

## What It Does

ZzCode 当前已经跑通一个可交互的 Code Agent CLI：

```text
用户输入任务
  -> 模型判断是否需要调用工具
  -> Python 后端执行本地工具
  -> 工具结果回灌给模型
  -> 模型继续推理或输出最终答案
```

当前重点是学习和拆解核心机制，而不是追求生产级完整能力。

## Features

- Python 版 ReAct Agent 主循环
- OpenAI-compatible LLM Client
- 内置本地工具：`list_files`、`read_file`、`write_file`、`run_shell`
- React + Ink 终端 UI
- JSON Lines 前后端事件协议
- 常驻 Python backend session
- Slash Commands：`/help`、`/clear`、`/mock`、`/mode`、`/exit`
- 多行输入、历史输入、光标编辑
- 工具执行前权限确认
- `write_file` 执行前 diff 预览
- 按工具类型展示结果
- 柔和终端配色和欢迎页

## Architecture

```text
frontend/ React + Ink
  -> terminal UI
  -> prompt input
  -> message rendering
  -> permission prompt
  -> JSON Lines client

src/zzcode/ Python Core
  -> Agent loop
  -> LLM client
  -> tool registry
  -> local tool execution
  -> JSON Lines server
```

前端不直接依赖 Python Agent 内部实现，只通过 JSON Lines 事件通信。这样后续接入 MCP、Memory、Plan Mode 或多 Agent 时，可以优先扩展协议和后端能力，而不是重写 UI。

## Project Structure

```text
ZzCode/
├── README.md
├── AGENTS.md
├── docs/
│   ├── img/
│   │   └── 1.png
│   └── phase-01-react-toolcall-demo.md
├── frontend/
│   ├── package.json
│   └── src/
├── src/
│   └── zzcode/
│       ├── agent/
│       ├── cli/
│       ├── llm/
│       ├── protocol/
│       ├── runtime/
│       ├── tools/
│       └── ui/
└── tests/
```

## Quick Start

### React + Ink UI

```bash
cd frontend
npm install
npm run dev
```

默认会启动 Python JSON Lines 后端，驱动现有 `TextReActAgent`、DeepSeek 和本地工具。

如果只想看 UI mock 效果：

```powershell
$env:ZZCODE_USE_MOCK="1"
npm run dev
```

如果 Windows 环境中 `python` 命令不可用：

```powershell
$env:ZZCODE_PYTHON="py"
npm run dev
```

### Python Teaching CLI

```bash
PYTHONPATH=src python -m zzcode.cli.main
```

## Commands

```text
/help     显示帮助
/clear    清空前端消息和 Python 会话历史
/mock     在 mock/python 后端之间切换
/mode     查看或切换模式：default / readonly / plan
/exit     退出 ZzCode
```

## Input

```text
Enter       发送
Shift+Enter 插入换行
\ + Enter   续行输入
↑/↓         多行内移动；到边界后切换历史输入
←/→         移动光标
Ctrl+A/E    跳到行首/行尾
Ctrl+U      清空当前行光标前内容
Ctrl+C      当前输入为空时退出，否则清空输入
```

## Tool Permissions

工具执行前会进入权限确认界面：

```text
↑/↓       移动选项
Enter     确认当前选项
1/2/3     直接选择对应选项
```

`write_file` 会在确认前展示 diff 预览，帮助用户看清楚即将写入的内容。

## Current Phase

当前处于第一阶段：**ReAct + Tool Call Demo**。

已经完成：

- CLI 交互入口
- ReAct Agent 主循环
- Mock LLM Client
- OpenAI-compatible LLM Client
- 工具注册表
- 基础文件和 shell 工具
- React + Ink UI 壳子
- JSON Lines 前后端通信
- 常驻 Python backend session
- 工具权限确认
- 文件 diff 预览
- 多行输入和启动欢迎页

## Roadmap

后续计划按学习进度逐步推进：

- 更安全的文件和命令工具
- 配置系统
- 更完整的测试覆盖
- Plan Mode
- Memory 与上下文管理
- MCP 接入
- 多 Agent
- 更完整的终端 UI

## Learning Notes

- `AGENTS.md`：项目协作说明、架构约定和阶段规划
- `docs/phase-01-react-toolcall-demo.md`：第一阶段实现方案和学习笔记

ZzCode 会参考 PaiCLI、hello-agents、Claude Code 等工具的思想，但实现上保持 Python CLI 项目的自然组织方式，优先让每个阶段的核心机制清晰可读。
