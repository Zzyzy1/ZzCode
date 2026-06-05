import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";

type Props = {
  model: string;
  cwd: string;
};

/**
 * 渲染顶部状态头。
 * model/cwd 用于展示当前模型和工作目录；返回一行紧凑标题。
 */
export function Header({ model, cwd }: Props) {
  return (
    <Box borderStyle="single" borderColor={defaultTheme.border} paddingX={1} marginBottom={1}>
      <Text bold color={defaultTheme.accent}>ZzCode</Text>
      <Text color={defaultTheme.muted}>  model: {model}  cwd: {cwd}</Text>
    </Box>
  );
}
