import React from "react";
import { Box, Text } from "ink";
import type { MessageNode } from "../../protocol/events.js";
import { defaultTheme } from "../../app/theme.js";
import { ToolBlock } from "../tools/ToolBlock.js";

type Props = {
  message: MessageNode;
  toolOutputById: Map<string, MessageNode>;
};

/**
 * 渲染单条消息。
 * message 是协议事件节点；toolOutputById 用于把工具调用和结果合并展示；返回一行或一个工具块。
 */
export function MessageRow({ message, toolOutputById }: Props) {
  if (message.type === "user_message") {
    return <Text color={defaultTheme.user}>› {message.text}</Text>;
  }

  if (message.type === "assistant_thought") {
    return (
      <Box flexDirection="column">
        <Text><Text color={defaultTheme.accent}>●</Text> Thought</Text>
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>{message.text}</Text>
        </Box>
      </Box>
    );
  }

  if (message.type === "tool_use") {
    const result = toolOutputById.get(message.id);
    return (
      <ToolBlock
        name={message.name}
        displayName={message.displayName}
        input={message.input}
        output={result?.type === "tool_result" ? result.output : undefined}
        ok={result?.type === "tool_result" ? result.ok : true}
      />
    );
  }

  if (message.type === "tool_result") {
    return null;
  }

  if (message.type === "request_done") {
    return null;
  }

  if (message.type === "permission_request") {
    return (
      <Box flexDirection="column">
        <Text>
          <Text color={defaultTheme.warning}>●</Text> Permission
          <Text color={defaultTheme.muted}> {message.displayName ?? message.toolName}({message.input})</Text>
        </Text>
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>等待确认，风险级别：{message.risk}</Text>
        </Box>
      </Box>
    );
  }

  if (message.type === "assistant_final") {
    return (
      <Box flexDirection="column">
        <Text><Text color={defaultTheme.success}>●</Text> Final</Text>
        <Box paddingLeft={2}>
          <Text>{message.text}</Text>
        </Box>
      </Box>
    );
  }

  const color = message.level === "error" ? defaultTheme.danger : message.level === "warning" ? defaultTheme.warning : defaultTheme.muted;
  return <Text color={color}>● {message.text}</Text>;
}
