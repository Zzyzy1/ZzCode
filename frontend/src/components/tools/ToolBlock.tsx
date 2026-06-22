import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";
import { ToolResultView } from "./ToolResultView.js";
import { formatToolUseSummary } from "./toolUiRegistry.js";

type Props = {
  name: string;
  displayName?: string;
  input: unknown;
  output?: string;
  ok?: boolean;
  source?: string;
};

/**
 * 展示一次工具调用和可选结果。
 * name/input/output 对应协议事件字段；返回 Claude 风格的工具块。
 */
export function ToolBlock({ name, displayName, input, output, ok = true, source }: Props) {
  const label = source === "mcp" ? name : displayName ?? name;
  const summary = formatToolUseSummary(name, input, { source });

  return (
    <Box flexDirection="column" marginY={0}>
      <Text>
        <Text color={defaultTheme.accent}>●</Text> {label}
        {source === "mcp" && displayName ? <Text color={defaultTheme.muted}> [{displayName}]</Text> : null}
        {summary !== null && summary !== "" ? <Text color={defaultTheme.muted}>({summary})</Text> : null}
      </Text>
      {output ? (
        <Box paddingLeft={2}>
          <ToolResultView toolName={name} output={output} ok={ok} />
        </Box>
      ) : null}
    </Box>
  );
}
