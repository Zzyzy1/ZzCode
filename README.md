# ZzCode

ZzCode 是一个用于学习的 Python 版 Code Agent CLI 项目。

项目目标是模仿现代终端编程智能体的核心能力，先从最小 ReAct + Tool Call demo 做起，再逐步加入 MCP、Memory、RAG、Plan 模式、多 Agent 等功能。

## 当前阶段

当前处于第一阶段：ReAct + Tool Call Demo。

这一阶段只关注一件事：让一个 Python CLI 能跑通 Agent 的核心循环。

核心流程：

```text
用户输入任务
  -> 模型判断是否需要调用工具
  -> Python 程序执行工具
  -> 工具结果回灌给模型
  -> 模型继续判断或输出最终答案
```

## 当前目录

```text
ZzCode/
├── README.md
├── AGENTS.md
├── docs/
│   └── phase-01-react-toolcall-demo.md
├── frontend/
│   ├── package.json
│   └── src/
├── src/
│   └── zzcode/
│       ├── cli/
│       ├── agent/
│       ├── llm/
│       ├── tools/
│       └── runtime/
└── tests/
```

## 文档

- `AGENTS.md`：项目协作说明、架构约定和阶段规划。
- `docs/phase-01-react-toolcall-demo.md`：第一阶段实现方案和学习笔记。

## 运行方式

当前有两个入口：

```bash
# Python 教学版 ReAct CLI
PYTHONPATH=src python -m zzcode.cli.main

# React + Ink UI 壳子
cd frontend
npm install
npm run dev
```

React + Ink 入口当前默认会启动 Python JSON Lines 后端，驱动现有 `TextReActAgent`、DeepSeek 和本地工具。

如果只想看 UI mock 效果，可以在 PowerShell 中运行：

```powershell
$env:ZZCODE_USE_MOCK="1"
npm run dev
```

如果你的 Windows 环境里 `python` 命令不可用，可以指定：

```powershell
$env:ZZCODE_PYTHON="py"
npm run dev
```

当前 Ink 命令：

```text
/help     显示帮助
/clear    清空前端消息和 Python 会话历史
/mock     在 mock/python 后端之间切换
/mode     查看或切换模式：default / readonly / plan
/exit     退出 ZzCode
```

当前输入能力：

```text
Enter     发送
Shift+Enter 插入换行
\ + Enter  续行输入
↑/↓       多行内移动；到边界后切换历史输入
←/→       移动光标
Ctrl+A/E  跳到行首/行尾
Ctrl+U    清空当前行光标前内容
Ctrl+C    当前输入为空时退出，否则清空输入
```

当前界面体验：

```text
启动时展示欢迎页、卡通终端形象、快捷命令和 tips
输入框支持多行编辑和多行粘贴
主题颜色调整为柔和低饱和配色
```

当前工具权限确认：

```text
↑/↓       移动选项
Enter     确认当前选项
1/2/3     直接选择对应选项
```

当前工具结果展示：

```text
write_file 权限确认前展示 diff 预览
list_files/read_file/run_shell/write_file 按工具类型展示结果
```

## 第一阶段计划实现

- CLI 交互入口。
- ReAct Agent 主循环。
- Mock LLM Client。
- OpenAI-compatible LLM Client。
- 工具注册表。
- 四个基础工具：`list_files`、`read_file`、`write_file`、`run_shell`。
- React + Ink 终端 UI 壳子。
- React + Ink 通过 JSON Lines 调用 Python Agent Core。
- Ink 斜杠命令、常驻 Python 后端、输入历史和光标编辑。
- 工具执行前权限确认。
- 基础测试。

## 暂不实现

第一阶段暂不实现 MCP、Memory、RAG、Plan DAG、多 Agent、复杂 TUI、Git 快照等功能。

先把最核心的 Agent Loop 理解清楚，再继续扩展。
