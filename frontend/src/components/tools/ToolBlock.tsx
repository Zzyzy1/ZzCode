import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";
import { ToolResultView } from "./ToolResultView.js";

type Props = {
  name: string;
  displayName?: string;
  input: string;
  output?: string;
  ok?: boolean;
};

/**
 * 展示一次工具调用和可选结果。
 * name/input/output 对应协议事件字段；返回 Claude 风格的工具块。
 */
export function ToolBlock({ name, displayName, input, output, ok = true }: Props) {
  return (
    <Box flexDirection="column" marginY={0}>
      <Text>
        <Text color={defaultTheme.accent}>●</Text> {displayName ?? name}
        <Text color={defaultTheme.muted}>({input})</Text>
      </Text>
      {output ? (
        <Box paddingLeft={2}>
          <ToolResultView toolName={name} output={output} ok={ok} />
        </Box>
      ) : null}
    </Box>
  );
}
