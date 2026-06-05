import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { defaultTheme } from "../../app/theme.js";

type Props = {
  disabled: boolean;
  onSubmit: (value: string) => void;
  onExit: () => void;
};

/**
 * 处理多行终端输入。
 * disabled 表示 Agent 正在运行；onSubmit 接收用户完整输入；返回稳定的 prompt 面板。
 */
export function PromptInput({ disabled, onSubmit, onExit }: Props) {
  const [value, setValue] = useState("");
  const [cursor, setCursor] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);

  useInput((input, key) => {
    if (key.ctrl && input === "c") {
      if (value.length === 0) {
        onExit();
        return;
      }
      resetInput();
      return;
    }

    if (disabled) {
      return;
    }

    if (key.return) {
      if (key.shift || value[cursor - 1] === "\\") {
        insertText(value[cursor - 1] === "\\" ? "\n" : "\n", value[cursor - 1] === "\\" ? 1 : 0);
        return;
      }
      submit();
      return;
    }

    if (key.upArrow) {
      moveCursorUp();
      return;
    }

    if (key.downArrow) {
      moveCursorDown();
      return;
    }

    if (key.leftArrow) {
      setCursor((current) => Math.max(0, current - 1));
      return;
    }

    if (key.rightArrow) {
      setCursor((current) => Math.min(value.length, current + 1));
      return;
    }

    if (key.ctrl && input === "a") {
      setCursor(lineStartOffset(value, cursor));
      return;
    }

    if (key.ctrl && input === "e") {
      setCursor(lineEndOffset(value, cursor));
      return;
    }

    if (key.ctrl && input === "u") {
      const start = lineStartOffset(value, cursor);
      setValue((current) => current.slice(0, start) + current.slice(cursor));
      setCursor(start);
      setHistoryIndex(null);
      return;
    }

    if (key.backspace || key.delete) {
      removeText(key.backspace);
      return;
    }

    // Ink 会把粘贴内容也放进 input；按光标位置插入可以同时支持普通输入和多行粘贴。
    if (input && !key.ctrl && !key.meta) {
      insertText(input);
    }
  });

  function submit() {
    const nextValue = value.trim();
    if (nextValue.length === 0) {
      return;
    }
    onSubmit(nextValue);
    setHistory((current) => [nextValue, ...current.filter((item) => item !== nextValue)].slice(0, 30));
    resetInput();
  }

  function resetInput() {
    setValue("");
    setCursor(0);
    setHistoryIndex(null);
  }

  function insertText(text: string, removeBeforeCursor = 0) {
    const start = Math.max(0, cursor - removeBeforeCursor);
    setValue((current) => current.slice(0, start) + text + current.slice(cursor));
    setCursor(start + text.length);
    setHistoryIndex(null);
  }

  function removeText(backspace: boolean) {
    if (backspace && cursor > 0) {
      setValue((current) => current.slice(0, cursor - 1) + current.slice(cursor));
      setCursor((current) => Math.max(0, current - 1));
    } else if (!backspace && cursor < value.length) {
      setValue((current) => current.slice(0, cursor) + current.slice(cursor + 1));
    }
    setHistoryIndex(null);
  }

  function moveCursorUp() {
    const nextCursor = offsetAbove(value, cursor);
    if (nextCursor !== cursor) {
      setCursor(nextCursor);
      return;
    }
    setHistoryIndex((current) => {
      const nextIndex = current === null ? 0 : Math.min(current + 1, history.length - 1);
      const nextValue = history[nextIndex] ?? value;
      setValue(nextValue);
      setCursor(nextValue.length);
      return history.length > 0 ? nextIndex : null;
    });
  }

  function moveCursorDown() {
    const nextCursor = offsetBelow(value, cursor);
    if (nextCursor !== cursor) {
      setCursor(nextCursor);
      return;
    }
    setHistoryIndex((current) => {
      if (current === null) {
        return null;
      }
      const nextIndex = current - 1;
      const nextValue = nextIndex >= 0 ? history[nextIndex] : "";
      setValue(nextValue);
      setCursor(nextValue.length);
      return nextIndex >= 0 ? nextIndex : null;
    });
  }

  const lines = splitLinesForCursor(value, cursor);
  const lineCount = Math.max(1, value.split("\n").length);

  return (
    <Box borderStyle="round" borderColor={disabled ? defaultTheme.border : defaultTheme.accent} paddingX={1} marginTop={1} flexDirection="column">
      <Box>
        <Text color={disabled ? defaultTheme.muted : defaultTheme.accent}>zzcode</Text>
        <Text color={defaultTheme.muted}> › </Text>
        <Text color={defaultTheme.muted}>{disabled ? "agent is running" : "Enter send · Shift+Enter newline · \\ + Enter continue"}</Text>
        <Text color={defaultTheme.muted}> · {lineCount} line{lineCount === 1 ? "" : "s"}</Text>
      </Box>
      {disabled ? (
        <Text color={defaultTheme.muted}>Waiting for agent events...</Text>
      ) : (
        <Box flexDirection="column">
          {lines.map((line, index) => (
            <InputLine key={index} line={line} showPrompt={index === 0} />
          ))}
        </Box>
      )}
    </Box>
  );
}

function InputLine({ line, showPrompt }: { line: RenderLine; showPrompt: boolean }) {
  return (
    <Box>
      <Text color={defaultTheme.muted}>{showPrompt ? ">" : "·"} </Text>
      <Text>{line.before}</Text>
      {line.hasCursor ? <Text inverse>{line.cursorChar}</Text> : null}
      <Text>{line.after}</Text>
    </Box>
  );
}

type RenderLine = {
  before: string;
  cursorChar: string;
  after: string;
  hasCursor: boolean;
};

function splitLinesForCursor(value: string, cursor: number): RenderLine[] {
  const safeValue = value.length === 0 ? " " : value;
  const lines = safeValue.split("\n");
  let offset = 0;

  return lines.map((line) => {
    const lineStart = offset;
    const lineEnd = lineStart + line.length;
    const hasCursor = cursor >= lineStart && cursor <= lineEnd;
    offset = lineEnd + 1;

    if (!hasCursor) {
      return { before: line || " ", cursorChar: "", after: "", hasCursor: false };
    }

    const localCursor = cursor - lineStart;
    return {
      before: line.slice(0, localCursor),
      cursorChar: line[localCursor] ?? " ",
      after: line.slice(localCursor + 1),
      hasCursor: true
    };
  });
}

function lineStartOffset(value: string, cursor: number): number {
  return value.lastIndexOf("\n", Math.max(0, cursor - 1)) + 1;
}

function lineEndOffset(value: string, cursor: number): number {
  const nextBreak = value.indexOf("\n", cursor);
  return nextBreak === -1 ? value.length : nextBreak;
}

function offsetAbove(value: string, cursor: number): number {
  const currentStart = lineStartOffset(value, cursor);
  if (currentStart === 0) {
    return cursor;
  }
  const column = cursor - currentStart;
  const previousEnd = currentStart - 1;
  const previousStart = lineStartOffset(value, previousEnd);
  return Math.min(previousStart + column, previousEnd);
}

function offsetBelow(value: string, cursor: number): number {
  const currentEnd = lineEndOffset(value, cursor);
  if (currentEnd >= value.length) {
    return cursor;
  }
  const currentStart = lineStartOffset(value, cursor);
  const column = cursor - currentStart;
  const nextStart = currentEnd + 1;
  const nextEnd = lineEndOffset(value, nextStart);
  return Math.min(nextStart + column, nextEnd);
}
