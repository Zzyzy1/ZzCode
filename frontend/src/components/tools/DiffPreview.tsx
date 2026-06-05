import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";
import type { DiffPreviewLine, WriteFileDiffPreview } from "../../protocol/events.js";

type Props = {
  preview: WriteFileDiffPreview;
};

/**
 * 渲染写文件前的 diff 预览。
 * preview 来自后端权限事件；返回有限行数的 unified diff。
 */
export function DiffPreview({ preview }: Props) {
  const title = preview.fileExists ? `Modify ${preview.path}` : `Create ${preview.path}`;

  return (
    <Box flexDirection="column" marginTop={1}>
      <Text color={defaultTheme.accent}>{title}</Text>
      {preview.error ? (
        <Text color={defaultTheme.danger}>{preview.error}</Text>
      ) : (
        <>
          <Text color={defaultTheme.muted}>
            {preview.oldLineCount ?? 0} lines {"->"} {preview.newLineCount ?? 0} lines
          </Text>
          <Box flexDirection="column" borderStyle="single" borderColor={defaultTheme.border} paddingX={1}>
            {(preview.lines ?? []).map((line, index) => (
              <DiffLine key={`${index}-${line.kind}`} line={line} />
            ))}
            {preview.truncated ? <Text color={defaultTheme.muted}>... diff truncated</Text> : null}
          </Box>
        </>
      )}
    </Box>
  );
}

function DiffLine({ line }: { line: DiffPreviewLine }) {
  const color = line.kind === "add"
    ? defaultTheme.success
    : line.kind === "remove"
      ? defaultTheme.danger
      : line.kind === "header"
        ? defaultTheme.accent
        : defaultTheme.muted;

  return <Text color={color}>{line.text || " "}</Text>;
}
