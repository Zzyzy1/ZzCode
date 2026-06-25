import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";

type ToolUseOptions = {
  source?: string;
};

type ToolResultOptions = {
  ok: boolean;
  data?: unknown;
  metadata?: unknown;
  verbose?: boolean;
};

type ToolUiDefinition = {
  formatToolUse?: (input: unknown, options: ToolUseOptions) => React.ReactNode | string | null;
  formatToolResult?: (output: string, options: ToolResultOptions) => React.ReactNode | null;
  /** 如果为 true，verbose 模式下展开完整结果时不额外包装 */
  verboseExpandsInline?: boolean;
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
  web_search: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const query = asString(value?.query);
      return query ? compactMultiline(query, MAX_INPUT_CHARS) : null;
    },
    formatToolResult: (output, { ok, data, verbose }) =>
      renderWebSearchResult(output, { ok, data, verbose }),
    verboseExpandsInline: true
  },
  web_fetch: {
    formatToolUse: (input) => {
      const value = asRecord(input);
      const url = asString(value?.url);
      return url ? compactMultiline(url, MAX_INPUT_CHARS) : null;
    },
    formatToolResult: (output, { ok, data, verbose }) =>
      renderWebFetchResult(output, { ok, data, verbose }),
    verboseExpandsInline: true
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
  const def = TOOL_UI[name];
  const renderer = def?.formatToolResult;
  if (renderer) {
    const rendered = renderer(output, options);
    // verbose 对于未自定义 verbose 展开的 renderer：在折叠摘要后追加原始 output
    if (options.verbose && rendered !== null && !def?.verboseExpandsInline) {
      return (
        <Box flexDirection="column">
          {rendered}
          <Box paddingLeft={1} marginTop={0}>
            <Text color={defaultTheme.muted}>
              ── verbose ─────────────────────────────────────────
            </Text>
          </Box>
          <Box paddingLeft={1}>
            <Text color={defaultTheme.muted}>{output.slice(0, 8000)}</Text>
          </Box>
          <Box paddingLeft={1}>
            <Text color={defaultTheme.muted}>
              ────────────────────────────────────────────────────
            </Text>
          </Box>
        </Box>
      );
    }
    return rendered;
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

function renderWebSearchResult(output: string, { ok, data, verbose }: ToolResultOptions) {
  if (!ok) {
    return renderErrorResult(output);
  }
  const value = asRecord(data);
  if (!value) {
    return renderFallbackResult(output);
  }

  // 预算耗尽时展示明确提示，避免 "Did 0 searches" 误导用户
  if (asNumber(value?.budget_used) !== null && asNumber(value?.budget_max) !== null) {
    const used = asNumber(value.budget_used)!;
    const max = asNumber(value.budget_max)!;
    return (
      <Box flexDirection="column">
        <Text color={defaultTheme.warning}>
          ⎿ ⚠ Web tool budget exhausted ({used}/{max} used)
        </Text>
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>
            Stop searching and answer based on available sources.
          </Text>
        </Box>
        {verbose && value?.attempted ? (
          <Box paddingLeft={2}>
            <Text color={defaultTheme.muted}>
              attempted: {asString(asRecord(value.attempted)?.tool) ?? "?"}
              {" "}({compact(asString(asRecord(value.attempted)?.query) ?? asString(asRecord(value.attempted)?.url) ?? "", 80)})
            </Text>
          </Box>
        ) : null}
      </Box>
    );
  }

  const searchCount = asNumber(value.searchCount) ?? countSearchResultBlocks(output);
  const durationSeconds = asNumber(value.durationSeconds);
  const sourceCount = Array.isArray(value.sources) ? value.sources.length : countMarkdownLinks(output);
  const duration = durationSeconds === null ? "" : ` in ${formatDuration(durationSeconds)}`;
  const summary = (
    <Text color={defaultTheme.muted}>
      ⎿ Did {searchCount} search{searchCount === 1 ? "" : "es"}{duration}; found {sourceCount} source
      {sourceCount === 1 ? "" : "s"}
    </Text>
  );
  if (!verbose) {
    return summary;
  }
  // verbose: 展示折叠摘要 + sources 列表 + 原始 output 摘要
  const sources = Array.isArray(value.sources) ? value.sources : [];
  return (
    <Box flexDirection="column">
      {summary}
      {sources.length > 0 ? (
        <Box flexDirection="column" paddingLeft={2} marginTop={0}>
          {sources.slice(0, 20).map((s: unknown, i: number) => {
            const src = asRecord(s);
            const title = asString(src?.title) ?? `Source ${i + 1}`;
            const srcUrl = asString(src?.url) ?? "";
            return (
              <Text key={i} color={defaultTheme.muted}>
                {i + 1}. {title} {srcUrl ? `(${compact(srcUrl, 80)})` : ""}
              </Text>
            );
          })}
          {sources.length > 20 ? (
            <Text color={defaultTheme.muted}>... and {sources.length - 20} more sources</Text>
          ) : null}
        </Box>
      ) : (
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>{compact(output, 500)}</Text>
        </Box>
      )}
    </Box>
  );
}

function renderFallbackResult(output: string) {
  return <Text color={defaultTheme.muted}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>;
}

function renderErrorResult(output: string) {
  return <Text color={defaultTheme.danger}>⎿ {compact(output, MAX_OUTPUT_CHARS)}</Text>;
}

function renderWebFetchResult(output: string, { ok, data, verbose }: ToolResultOptions) {
  if (!ok) {
    return renderErrorResult(output);
  }
  const value = asRecord(data);

  // 预算耗尽时展示明确提示
  if (asNumber(value?.budget_used) !== null && asNumber(value?.budget_max) !== null) {
    const used = asNumber(value!.budget_used)!;
    const max = asNumber(value!.budget_max)!;
    return (
      <Box flexDirection="column">
        <Text color={defaultTheme.warning}>
          ⎿ ⚠ Web tool budget exhausted ({used}/{max} used)
        </Text>
        <Box paddingLeft={2}>
          <Text color={defaultTheme.muted}>
            Stop fetching and answer based on available sources.
          </Text>
        </Box>
        {verbose && value?.attempted ? (
          <Box paddingLeft={2}>
            <Text color={defaultTheme.muted}>
              attempted: {asString(asRecord(value.attempted)?.tool) ?? "?"}
              {" "}({compact(asString(asRecord(value.attempted)?.query) ?? asString(asRecord(value.attempted)?.url) ?? "", 80)})
            </Text>
          </Box>
        ) : null}
      </Box>
    );
  }

  const bytes = asNumber(value?.bytes);
  const url = asString(value?.url);
  const code = asNumber(value?.code);
  const codeText = asString(value?.codeText);
  const cacheHit = value?.cacheHit === true;
  const redirect = value?.redirect === true;
  const summarySource = asString(value?.summarySource);
  const summaryChars = asNumber(value?.summaryChars);

  // 非 verbose：Claude 风格 "Received <size> (<status>)" + URL 摘要
  if (!verbose) {
    const sizeLabel = bytes !== null ? formatBytes(bytes) : "?B";
    let statusLabel = "";
    if (redirect) {
      statusLabel = code ? `${code} redirect` : "redirect";
    } else if (code) {
      statusLabel = `${code}${codeText ? ` ${codeText}` : ""}`;
    } else {
      statusLabel = "OK";
    }
    const cacheNote = cacheHit ? " (cached)" : "";
    const urlSummary = url ? ` ${compact(url, 60)}` : "";
    return (
      <Box flexDirection="column">
        <Text color={defaultTheme.muted}>
          ⎿ Received <Text bold>{sizeLabel}</Text> ({statusLabel}){cacheNote}{urlSummary}
        </Text>
        {summarySource && summaryChars !== null ? (
          <Text color={defaultTheme.muted}>
            {"  "}summary: {summaryChars} chars via {summarySource}
          </Text>
        ) : null}
      </Box>
    );
  }

  // verbose：展示摘要 + 完整提取内容
  const sizeLabel = bytes !== null ? formatBytes(bytes) : "?B";
  const statusLabel = redirect ? `redirect ${code ?? ""}` : `${code ?? "OK"}${codeText ? ` ${codeText}` : ""}`;
  return (
    <Box flexDirection="column">
      <Text color={defaultTheme.muted}>
        ⎿ Received <Text bold>{sizeLabel}</Text> ({statusLabel}){cacheHit ? " (cached)" : ""}
        {url ? ` ${url}` : ""}
      </Text>
      {summarySource ? (
        <Text color={defaultTheme.muted}>  summary: {summaryChars ?? "?"} chars via {summarySource}</Text>
      ) : null}
      <Box paddingLeft={2} marginTop={0}>
        <Text color={defaultTheme.muted}>{compact(output, 5000)}</Text>
      </Box>
    </Box>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
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

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatDuration(seconds: number): string {
  return seconds >= 1 ? `${Math.round(seconds)}s` : `${Math.round(seconds * 1000)}ms`;
}

function countSearchResultBlocks(output: string): number {
  return output.includes("Search results for") ? 1 : 0;
}

function countMarkdownLinks(output: string): number {
  const matches = output.match(/\[[^\]]+\]\(https?:\/\/[^)]+\)/g);
  return matches?.length ?? 0;
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
