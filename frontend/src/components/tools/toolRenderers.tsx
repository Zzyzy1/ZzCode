import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";

type ToolResultRendererProps = {
  output: string;
};

export type ToolResultRenderer = (props: ToolResultRendererProps) => React.ReactNode;

const MAX_READ_LINES = 10;
const MAX_LIST_ITEMS = 30;

export const toolResultRenderers: Record<string, ToolResultRenderer> = {
  list_files: renderListFilesResult,
  read_file: renderReadFileResult,
  run_shell: renderShellResult,
  write_file: renderWriteFileResult
};

export function renderFallbackResult({ output }: ToolResultRendererProps) {
  return <Text color={defaultTheme.muted}>⎿ {compact(output)}</Text>;
}

export function renderFailedResult({ output }: ToolResultRendererProps) {
  return <Text color={defaultTheme.danger}>⎿ {compact(output)}</Text>;
}

function renderListFilesResult({ output }: ToolResultRendererProps) {
  const items = output.split("\n").filter(Boolean);
  const visibleItems = items.slice(0, MAX_LIST_ITEMS);

  return (
    <Box flexDirection="column">
      <Text color={defaultTheme.muted}>⎿ {items.length} item{items.length === 1 ? "" : "s"}</Text>
      {visibleItems.map((item) => (
        <Text key={item} color={item.endsWith("/") ? defaultTheme.accent : undefined}>  {item}</Text>
      ))}
      {items.length > visibleItems.length ? <Text color={defaultTheme.muted}>  ... {items.length - visibleItems.length} more</Text> : null}
    </Box>
  );
}

function renderReadFileResult({ output }: ToolResultRendererProps) {
  const lines = output.split("\n");
  const visibleLines = lines.slice(0, MAX_READ_LINES);
  const gutterWidth = String(visibleLines.length).length;

  return (
    <Box flexDirection="column">
      <Text color={defaultTheme.muted}>⎿ {lines.length} line{lines.length === 1 ? "" : "s"}</Text>
      {visibleLines.map((line, index) => (
        <Text key={index}>
          <Text color={defaultTheme.muted}>{String(index + 1).padStart(gutterWidth, " ")} │ </Text>
          <Text>{line}</Text>
        </Text>
      ))}
      {lines.length > visibleLines.length ? <Text color={defaultTheme.muted}>  ... {lines.length - visibleLines.length} more lines</Text> : null}
    </Box>
  );
}

function renderShellResult({ output }: ToolResultRendererProps) {
  const { body, stderr, exitCode } = splitShellOutput(output);

  return (
    <Box flexDirection="column">
      {body ? <Text color={defaultTheme.muted}>⎿ {compact(body)}</Text> : null}
      {stderr ? <Text color={defaultTheme.warning}>stderr: {compact(stderr)}</Text> : null}
      <Text color={exitCode === "0" ? defaultTheme.success : defaultTheme.danger}>exit_code: {exitCode ?? "unknown"}</Text>
    </Box>
  );
}

function renderWriteFileResult({ output }: ToolResultRendererProps) {
  return <Text color={defaultTheme.success}>⎿ {output}</Text>;
}

function splitShellOutput(output: string): { body: string; stderr: string; exitCode: string | null } {
  const exitMatch = output.match(/\n?exit_code: (-?\d+)\s*$/);
  const exitCode = exitMatch?.[1] ?? null;
  const withoutExit = exitMatch ? output.slice(0, exitMatch.index).trimEnd() : output;
  const stderrMarker = "\nstderr:\n";
  if (withoutExit.startsWith("stderr:\n")) {
    return { body: "", stderr: withoutExit.slice("stderr:\n".length).trim(), exitCode };
  }

  const stderrIndex = withoutExit.indexOf(stderrMarker);

  if (stderrIndex === -1) {
    return { body: withoutExit.trim(), stderr: "", exitCode };
  }

  return {
    body: withoutExit.slice(0, stderrIndex).trim(),
    stderr: withoutExit.slice(stderrIndex + stderrMarker.length).trim(),
    exitCode
  };
}

function compact(value: string): string {
  return value.length > 220 ? `${value.slice(0, 217)}...` : value;
}
