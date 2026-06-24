import React from "react";
import { Box, Text } from "ink";
import type { AgentStatus } from "../../protocol/events.js";
import { defaultTheme } from "../../app/theme.js";
import type { AppMode } from "../../app/modes.js";
import { describeMode } from "../../app/modes.js";

type Props = {
  status: AgentStatus;
  lastToolName?: string;
  backendMode?: string;
  appMode: AppMode;
  model: string;
  cwd: string;
  waitingForPermission?: boolean;
};

const labels: Record<AgentStatus, string> = {
  idle: "就绪",
  thinking: "思考中",
  running_tool: "正在运行工具",
  done: "完成"
};

/**
 * 渲染底部运行状态。
 * status 表示 Agent 状态；appMode/backendMode/model/cwd 是当前运行上下文；返回单行状态栏。
 */
export function StatusBar({ status, lastToolName, backendMode = "python", appMode, model, cwd, waitingForPermission = false }: Props) {
  const activeStatus = waitingForPermission ? "等待权限确认" : labels[status];
  const color = waitingForPermission
    ? defaultTheme.warning
    : status === "done"
      ? defaultTheme.success
      : status === "running_tool"
        ? defaultTheme.warning
        : defaultTheme.muted;
  const toolText = lastToolName ? ` · 工具：${lastToolName}` : "";

  return (
    <Box marginTop={1} flexDirection="column">
      <Text>
        <Text color={color}>● {activeStatus}{toolText}</Text>
        <Text color={defaultTheme.muted}>  模式：{appMode}（{describeMode(appMode)}） · 后端：{backendMode}</Text>
      </Text>
      <Text color={defaultTheme.muted}>模型：{model} · 当前目录：{cwd}</Text>
    </Box>
  );
}
