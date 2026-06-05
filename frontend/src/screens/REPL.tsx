import React, { useReducer, useState } from "react";
import { Box, useApp } from "ink";
import { FullscreenLayout } from "../components/layout/FullscreenLayout.js";
import { Messages } from "../components/messages/Messages.js";
import { PromptInput } from "../components/prompt/PromptInput.js";
import { StatusBar } from "../components/status/StatusBar.js";
import { PermissionPrompt } from "../components/tools/PermissionPrompt.js";
import { appModes, describeMode, isAppMode, type AppMode } from "../app/modes.js";
import { runMockAgent } from "../protocol/mockAgent.js";
import { clearPythonSession, runPythonAgent, shutdownPythonSession } from "../protocol/pythonAgent.js";
import type { AgentEvent, PermissionDecision, PermissionRequestEvent } from "../protocol/events.js";
import { replReducer } from "./reducer.js";

const initialState = {
  messages: [],
  status: "idle" as const
};

type PendingPermission = {
  request: PermissionRequestEvent;
  resolve: (decision: PermissionDecision) => void;
};

/**
 * 主 REPL 屏幕。
 * 无入参；返回完整终端交互界面，后续会把 mockAgent 替换成 Python JSONL 客户端。
 */
export function REPL() {
  const app = useApp();
  const [state, dispatch] = useReducer(replReducer, initialState);
  const [backendMode, setBackendMode] = useState(process.env.ZZCODE_USE_MOCK === "1" ? "mock" : "python");
  const [appMode, setAppMode] = useState<AppMode>("default");
  const [pendingPermission, setPendingPermission] = useState<PendingPermission | null>(null);
  const disabled = state.status === "thinking" || state.status === "running_tool" || pendingPermission !== null;
  const model = "deepseek-v4-flash";
  const cwd = process.cwd();

  async function handleSubmit(value: string) {
    if (value.startsWith("/")) {
      await handleCommand(value);
      return;
    }

    const events = backendMode === "mock"
      ? runMockAgent(value)
      : runPythonAgent(value, { onPermission: confirmPermission });

    for await (const event of events) {
      dispatch({ type: "append_event", event });
    }
  }

  function confirmPermission(request: PermissionRequestEvent): Promise<PermissionDecision> {
    return new Promise((resolve) => {
      setPendingPermission({ request, resolve });
    });
  }

  function handlePermissionDecision(decision: PermissionDecision) {
    if (!pendingPermission) {
      return;
    }
    pendingPermission.resolve(decision);
    appendNotice(permissionDecisionText(pendingPermission.request, decision));
    setPendingPermission(null);
  }

  async function handleCommand(value: string) {
    const [command] = value.trim().split(/\s+/, 1);

    if (command === "/help") {
      appendNotice(helpText());
      return;
    }
    if (command === "/clear") {
      dispatch({ type: "clear" });
      if (backendMode === "python") {
        for await (const event of clearPythonSession()) {
          dispatch({ type: "append_event", event });
        }
      }
      appendNotice("前端消息已清空。");
      return;
    }
    if (command === "/mock") {
      const nextMode = backendMode === "mock" ? "python" : "mock";
      setBackendMode(nextMode);
      appendNotice(`后端已切换为 ${nextMode}。`);
      return;
    }
    if (command === "/mode") {
      handleModeCommand(value);
      return;
    }
    if (command === "/exit" || command === "/quit") {
      shutdownPythonSession();
      app.exit();
      return;
    }

    appendNotice(`未知命令：${command}。输入 /help 查看可用命令。`, "warning");
  }

  function appendNotice(text: string, level: "info" | "warning" | "error" = "info") {
    const event: AgentEvent = { type: "system_notice", level, text };
    dispatch({ type: "append_event", event });
  }

  return (
    <FullscreenLayout>
      <Box flexDirection="column">
        <Messages messages={state.messages} />
      </Box>
      <PromptInput disabled={disabled} onSubmit={handleSubmit} onExit={() => {
        shutdownPythonSession();
        app.exit();
      }} />
      {pendingPermission ? (
        <PermissionPrompt request={pendingPermission.request} onDecision={handlePermissionDecision} />
      ) : null}
      <StatusBar
        status={state.status}
        lastToolName={state.lastToolName}
        backendMode={backendMode}
        appMode={appMode}
        model={model}
        cwd={cwd}
        waitingForPermission={pendingPermission !== null}
      />
    </FullscreenLayout>
  );

  function handleModeCommand(value: string) {
    const [, rawMode] = value.trim().split(/\s+/, 2);
    if (!rawMode) {
      appendNotice(`当前模式：${appMode}（${describeMode(appMode)}）。可用模式：${appModes.join(", ")}。`);
      return;
    }
    if (!isAppMode(rawMode)) {
      appendNotice(`未知模式：${rawMode}。可用模式：${appModes.join(", ")}。`, "warning");
      return;
    }
    setAppMode(rawMode);
    appendNotice(`模式已切换为 ${rawMode}（${describeMode(rawMode)}）。`);
  }
}

function helpText(): string {
  return [
    "Commands:",
    "  /help     显示帮助",
    "  /clear    清空前端消息和 Python 会话历史",
    "  /mock     在 mock/python 后端之间切换",
    "  /mode     查看或切换模式：/mode default|readonly|plan",
    "  /exit     退出 ZzCode",
    "",
    "Input:",
    "  Enter     发送",
    "  ↑/↓       切换历史输入",
    "  ←/→       移动光标",
    "  Ctrl+A/E  跳到行首/行尾",
    "  Ctrl+U    清空当前输入"
  ].join("\n");
}

function permissionDecisionText(request: PermissionRequestEvent, decision: PermissionDecision): string {
  const tool = request.displayName ?? request.toolName;
  if (decision === "allow_once") {
    return `已允许本次执行：${tool}`;
  }
  if (decision === "allow_session") {
    return `本会话已允许工具：${tool}`;
  }
  return `已拒绝执行：${tool}`;
}
