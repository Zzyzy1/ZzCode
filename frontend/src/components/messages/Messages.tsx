import React from "react";
import { Box } from "ink";
import type { MessageNode } from "../../protocol/events.js";
import { MessageRow } from "./MessageRow.js";
import type { CollapsedToolGroupNode, ToolUseMessageNode } from "./CollapsedToolGroup.js";
import { WelcomeScreen } from "../welcome/WelcomeScreen.js";

type Props = {
  messages: MessageNode[];
  verbose?: boolean;
};

/**
 * 渲染消息列表。
 * messages 是完整事件流；返回去重后的可见消息区域。
 */
export function Messages({ messages, verbose }: Props) {
  const toolOutputById = new Map<string, MessageNode>();
  const visibleMessages = buildVisibleMessages(messages);

  // 工具结果不单独成行，而是合并到对应 tool_use 中，这更接近 Claude 的阅读节奏。
  // subagent_tool_result 也通过 id 合并到对应的 subagent_tool_use。
  for (const message of messages) {
    if (message.type === "tool_result" || message.type === "subagent_tool_result") {
      toolOutputById.set(message.id, message);
    }
  }

  if (messages.length === 0) {
    return <WelcomeScreen />;
  }

  return (
    <Box flexDirection="column" gap={1}>
      {visibleMessages.map((message) => (
        <MessageRow key={message.key} message={message} toolOutputById={toolOutputById} verbose={verbose} />
      ))}
    </Box>
  );
}

function buildVisibleMessages(messages: MessageNode[]): Array<MessageNode | CollapsedToolGroupNode> {
  const visible: Array<MessageNode | CollapsedToolGroupNode> = [];
  let group: ToolUseMessageNode[] = [];
  let groupStartKey = "";
  let groupCreatedAt = 0;

  for (const message of messages) {
    if (message.type === "tool_result" || message.type === "subagent_tool_result" || message.type === "request_done") {
      continue;
    }

    if (message.type === "tool_use" && isCollapsibleTool(message.name)) {
      if (group.length === 0) {
        groupStartKey = message.key;
        groupCreatedAt = message.createdAt;
      }
      group.push(message);
      continue;
    }

    flushGroup();
    visible.push(message);
  }

  flushGroup();
  return visible;

  function flushGroup() {
    if (group.length === 0) {
      return;
    }
    if (group.length === 1) {
      visible.push(group[0]);
    } else {
      visible.push({
        type: "collapsed_tool_group",
        key: `${groupStartKey}-collapsed`,
        createdAt: groupCreatedAt,
        toolUses: [...group]
      });
    }
    group = [];
    groupStartKey = "";
    groupCreatedAt = 0;
  }
}

function isCollapsibleTool(name: string): boolean {
  return name === "read_file" || name === "list_files" || name === "glob" || name === "grep";
}
