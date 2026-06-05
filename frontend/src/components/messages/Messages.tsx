import React from "react";
import { Box } from "ink";
import type { MessageNode } from "../../protocol/events.js";
import { MessageRow } from "./MessageRow.js";
import { WelcomeScreen } from "../welcome/WelcomeScreen.js";

type Props = {
  messages: MessageNode[];
};

/**
 * 渲染消息列表。
 * messages 是完整事件流；返回去重后的可见消息区域。
 */
export function Messages({ messages }: Props) {
  const toolOutputById = new Map<string, MessageNode>();

  // 工具结果不单独成行，而是合并到对应 tool_use 中，这更接近 Claude 的阅读节奏。
  for (const message of messages) {
    if (message.type === "tool_result") {
      toolOutputById.set(message.id, message);
    }
  }

  if (messages.length === 0) {
    return <WelcomeScreen />;
  }

  return (
    <Box flexDirection="column" gap={1}>
      {messages.map((message) => (
        <MessageRow key={message.key} message={message} toolOutputById={toolOutputById} />
      ))}
    </Box>
  );
}
