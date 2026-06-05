import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { defaultTheme } from "../../app/theme.js";
import type { PermissionDecision, PermissionRequestEvent } from "../../protocol/events.js";
import { DiffPreview } from "./DiffPreview.js";

type Props = {
  request: PermissionRequestEvent;
  onDecision: (decision: PermissionDecision) => void;
};

type PermissionOption = {
  decision: PermissionDecision;
  label: string;
  hint: string;
};

const permissionOptions: PermissionOption[] = [
  { decision: "allow_once", label: "Allow once", hint: "本次允许" },
  { decision: "allow_session", label: "Allow for session", hint: "本会话允许该工具" },
  { decision: "deny", label: "Deny", hint: "拒绝执行" }
];

/**
 * 渲染工具权限确认选单。
 * request 是后端发来的权限请求；onDecision 把用户选择回传给协议层。
 */
export function PermissionPrompt({ request, onDecision }: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  useInput((input, key) => {
    if (key.upArrow) {
      setSelectedIndex((current) => Math.max(0, current - 1));
      return;
    }

    if (key.downArrow) {
      setSelectedIndex((current) => Math.min(permissionOptions.length - 1, current + 1));
      return;
    }

    if (key.return) {
      onDecision(permissionOptions[selectedIndex].decision);
      return;
    }

    const optionIndex = Number(input) - 1;
    if (Number.isInteger(optionIndex) && permissionOptions[optionIndex]) {
      onDecision(permissionOptions[optionIndex].decision);
    }
  });

  const color = request.risk === "high" ? defaultTheme.danger : request.risk === "medium" ? defaultTheme.warning : defaultTheme.success;

  return (
    <Box borderStyle="single" borderColor={color} paddingX={1} marginTop={1} flexDirection="column">
      <Text color={color}>Tool permission required</Text>
      <Text>
        <Text bold>{request.displayName ?? request.toolName}</Text>
        <Text color={defaultTheme.muted}>({request.input})</Text>
      </Text>
      <Text color={defaultTheme.muted}>risk: {request.risk} · ↑/↓ select · Enter confirm</Text>
      {request.preview?.type === "write_file_diff" ? <DiffPreview preview={request.preview} /> : null}
      <Box flexDirection="column" marginTop={1}>
        {permissionOptions.map((option, index) => {
          const isSelected = index === selectedIndex;

          return (
            <Text key={option.decision} color={isSelected ? color : undefined} inverse={isSelected}>
              {isSelected ? ">" : " "} {index + 1}. {option.label}
              <Text color={isSelected ? undefined : defaultTheme.muted}> - {option.hint}</Text>
            </Text>
          );
        })}
      </Box>
    </Box>
  );
}
