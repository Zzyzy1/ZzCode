import React from "react";
import { Box } from "ink";
import { AnsiText } from "./AnsiText.js";
import { formatMarkdown } from "./markdownFormatter.js";

type Props = {
  text: string;
};

/**
 * Claude 风格 Markdown 渲染：lexer/formatter 生成 ANSI，再交给 Ink 显示。
 */
export function MarkdownMessage({ text }: Props) {
  const formatted = React.useMemo(() => formatMarkdown(text), [text]);

  return (
    <Box flexDirection="column">
      <AnsiText>{formatted}</AnsiText>
    </Box>
  );
}
