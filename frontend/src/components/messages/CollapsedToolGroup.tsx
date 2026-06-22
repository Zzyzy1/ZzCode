import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";
import type { MessageNode } from "../../protocol/events.js";
import { formatToolUseSummary } from "../tools/toolUiRegistry.js";

export type ToolUseMessageNode = Extract<MessageNode, { type: "tool_use" }>;

export type CollapsedToolGroupNode = {
  type: "collapsed_tool_group";
  key: string;
  createdAt: number;
  toolUses: ToolUseMessageNode[];
};

type Props = {
  message: CollapsedToolGroupNode;
};

/**
 * 折叠连续的 read/search 类工具调用，减少刷屏。
 * message 保存原始 tool_use 列表；返回一条摘要块。
 */
export function CollapsedToolGroup({ message }: Props) {
  const summary = buildGroupSummary(message.toolUses);
  const details = buildGroupDetails(message.toolUses);

  return (
    <Box flexDirection="column">
      <Text>
        <Text color={defaultTheme.accent}>●</Text> {summary}
      </Text>
      {details ? (
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>⎿ {details}</Text>
        </Box>
      ) : null}
    </Box>
  );
}

function buildGroupSummary(toolUses: ToolUseMessageNode[]): string {
  let readCount = 0;
  let listCount = 0;
  let searchCount = 0;

  for (const toolUse of toolUses) {
    if (toolUse.name === "read_file") {
      readCount += 1;
    } else if (toolUse.name === "list_files") {
      listCount += 1;
    } else {
      searchCount += 1;
    }
  }

  const parts: string[] = [];
  if (readCount) {
    parts.push(`Read ${readCount} file${readCount === 1 ? "" : "s"}`);
  }
  if (listCount) {
    parts.push(`Listed ${listCount} director${listCount === 1 ? "y" : "ies"}`);
  }
  if (searchCount) {
    parts.push(`Searched ${searchCount} target${searchCount === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

function buildGroupDetails(toolUses: ToolUseMessageNode[]): string {
  const summaries = toolUses
    .map((toolUse) => formatToolUseSummary(toolUse.name, toolUse.input, { source: toolUse.source }))
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0);

  if (summaries.length === 0) {
    return "";
  }

  const preview = summaries.slice(0, 3).join(" · ");
  return summaries.length > 3 ? `${preview} · ... ${summaries.length - 3} more` : preview;
}
