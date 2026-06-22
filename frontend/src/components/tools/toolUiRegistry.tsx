import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";

type ToolUseOptions = {
  source?: string;
};

type ToolResultOptions = {
  ok: boolean;
};

type ToolUiDefinition = {
  formatToolUse?: (input: unknown, options: ToolUseOptions) => React.ReactNode | string | null;
  formatToolResult?: (output: string, options: ToolResultOptions) => React.ReactNode | null;
};

const MAX_INPUT_CHARS = 160;
const MAX_OUTPUT_CHARS = 220;

const TOOL_UI: Record<string, ToolUiDefinition> = {
  read_file: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const path = asString(value?.path);
      if (!path) {
        return null;
      }
      return path;
    },
    formatToolResult: (output, { ok }) => {
      if (!ok) {
        return renderErrorResult(output);
      }
      const lines = output.split("\n");
      return (
        <Text color={defaultTheme.muted}>
          ⎿ Read {lines.length} line{lines.length === 1 ? "" : "s"}
        </Text>
      );
    }
  },
  list_files: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      return asString(value?.path) ?? ".";
    },
    formatToolResult: (output, { ok }) => {
      if (!ok) {
        return renderErrorResult(output);
      }
      const items = output.split("\n").filter(Boolean);
      return (
        <Text color={defaultTheme.muted}>
          ⎿ Listed {items.length} item{items.length === 1 ? "" : "s"}
        </Text>
      );
    }
  },
  glob: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const pattern = asString(value?.pattern);
      const path = asString(value?.path);
      if (!pattern) {
        return path ?? null;
      }
      return path && path !== "." ? `${pattern} in ${path}` : pattern;
    },
    formatToolResult: (output, { ok }) => {
      if (!ok) {
        return renderErrorResult(output);
      }
      const items = countNonEmptyLines(output);
      return (
        <Text color={defaultTheme.muted}>
          ⎿ Found {items} match{items === 1 ? "" : "es"}
        </Text>
      );
    }
  },
  grep: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const pattern = asString(value?.pattern);
      const path = asString(value?.path);
      if (!pattern) {
        return path ?? null;
      }
      const label = `"${pattern}"`;
      return path && path !== "." ? `${label} in ${path}` : label;
    },
    formatToolResult: (output, { ok }) => {
      if (!ok) {
        return renderErrorResult(output);
      }
      const items = countNonEmptyLines(output);
      return (
        <Text color={defaultTheme.muted}>
          ⎿ Found {items} text match{items === 1 ? "" : "es"}
        </Text>
      );
    }
  },
  run_shell: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const command = asString(value?.command);
      return command ? compactMultiline(command, MAX_INPUT_CHARS) : null;
    },
    formatToolResult: (output) => renderShellResult(output)
  },
  write_file: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      return asString(value?.path) ?? null;
    },
    formatToolResult: (output, { ok }) => (
      <Text color={ok ? defaultTheme.success : defaultTheme.danger}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>
    )
  },
  edit_file: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      return asString(value?.path) ?? null;
    },
    formatToolResult: (output, { ok }) => (
      <Text color={ok ? defaultTheme.success : defaultTheme.danger}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>
    )
  },
  append_file: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      return asString(value?.path) ?? null;
    },
    formatToolResult: (output, { ok }) => (
      <Text color={ok ? defaultTheme.success : defaultTheme.danger}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>
    )
  }
};

/**
 * 生成工具调用标题中的摘要文本。
 * 保留原始 input 供逻辑使用，展示层只消费摘要。
 */
export function formatToolUseSummary(name: string, input: unknown, options: ToolUseOptions = {}): React.ReactNode | string | null {
  const summary = TOOL_UI[name]?.formatToolUse?.(input, options);
  if (summary !== undefined) {
    return summary;
  }
  if (options.source === "mcp") {
    return compact(stringifyInput(input), MAX_INPUT_CHARS);
  }
  return fallbackToolUseSummary(input);
}

/**
 * 渲染工具结果摘要。
 */
export function renderToolResultSummary(name: string, output: string, options: ToolResultOptions): React.ReactNode | null {
  const renderer = TOOL_UI[name]?.formatToolResult;
  if (renderer) {
    return renderer(output, options);
  }
  return options.ok ? renderFallbackResult(output) : renderErrorResult(output);
}

function renderShellResult(output: string) {
  const { body, stderr, exitCode } = splitShellOutput(output);
  return (
    <Box flexDirection="column">
      {body ? <Text color={defaultTheme.muted}>⎿ {compact(body, MAX_OUTPUT_CHARS)}</Text> : null}
      {stderr ? <Text color={defaultTheme.warning}>stderr: {compact(stderr, MAX_OUTPUT_CHARS)}</Text> : null}
      <Text color={exitCode === "0" ? defaultTheme.success : defaultTheme.danger}>exit_code: {exitCode ?? "unknown"}</Text>
    </Box>
  );
}

function renderFallbackResult(output: string) {
  return <Text color={defaultTheme.muted}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>;
}

function renderErrorResult(output: string) {
  return <Text color={defaultTheme.danger}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>;
}

function fallbackToolUseSummary(input: unknown): string {
  if (typeof input === "string") {
    return compactMultiline(input, MAX_INPUT_CHARS);
  }
  const value = asRecord(input);
  const path = asString(value?.path) ?? asString(value?.command);
  if (path) {
    return compactMultiline(path, MAX_INPUT_CHARS);
  }
  return compact(stringifyInput(input), MAX_INPUT_CHARS);
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

function stringifyInput(input: unknown): string {
  try {
    return typeof input === "string" ? input : JSON.stringify(input);
  } catch {
    return String(input);
  }
}

function asRecord(input: unknown): Record<string, unknown> | null {
  return input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>) : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function compact(value: string, maxChars: number): string {
  return value.length > maxChars ? `${value.slice(0, maxChars - 3)}...` : value;
}

function compactMultiline(value: string, maxChars: number): string {
  const normalized = value
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join(" ");
  return compact(normalized || value.trim(), maxChars);
}

function countNonEmptyLines(output: string): number {
  if (output.trim() === "(no matches)") {
    return 0;
  }
  return output
    .split("\n")
    .filter((line) => line.trim() && line.trim() !== "(no matches)" && line.trim() !== "(empty)" && line.trim() !== "(results truncated)")
    .filter((line) => line.trim() !== "results truncated").length;
}
