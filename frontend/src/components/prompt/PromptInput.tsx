import React, { useRef, useState } from "react";
import { Box, Text, useStdout } from "ink";
import { defaultTheme } from "../../app/theme.js";
import { TextInput } from "../input/TextInput.js";

type Props = {
  disabled: boolean;
  onSubmit: (value: string) => void;
  onExit: () => void;
};

type EditState = {
  value: string;
  cursor: number;
};

/**
 * Prompt 外壳只负责状态和接线，输入语义交给 TextInput 栈。
 */
export function PromptInput({ disabled, onSubmit, onExit }: Props) {
  const { stdout } = useStdout();
  const [value, setValue] = useState("");
  const [cursor, setCursor] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const undoStackRef = useRef<EditState[]>([]);
  const draftRef = useRef<EditState | null>(null);

  function handleChange(nextValue: string) {
    undoStackRef.current.push({ value, cursor });
    if (undoStackRef.current.length > 100) {
      undoStackRef.current.shift();
    }
    setValue(nextValue);
  }

  function handleSubmit(nextValue: string) {
    const trimmed = nextValue.trim();
    if (!trimmed) {
      return;
    }
    onSubmit(trimmed);
    setHistory((current) => [trimmed, ...current.filter((item) => item !== trimmed)].slice(0, 30));
    setValue("");
    setCursor(0);
    setHistoryIndex(null);
    draftRef.current = null;
    undoStackRef.current = [];
  }

  function handleUndo() {
    const previous = undoStackRef.current.pop();
    if (!previous) {
      return;
    }
    setValue(previous.value);
    setCursor(previous.cursor);
    setHistoryIndex(null);
  }

  function handleHistoryUp() {
    if (history.length === 0) {
      return;
    }
    if (historyIndex === null) {
      draftRef.current = { value, cursor };
      const nextValue = history[0] ?? value;
      setValue(nextValue);
      setCursor(nextValue.length);
      setHistoryIndex(0);
      return;
    }
    const nextIndex = Math.min(historyIndex + 1, history.length - 1);
    const nextValue = history[nextIndex] ?? value;
    setValue(nextValue);
    setCursor(nextValue.length);
    setHistoryIndex(nextIndex);
  }

  function handleHistoryDown() {
    if (historyIndex === null) {
      return;
    }
    const nextIndex = historyIndex - 1;
    if (nextIndex >= 0) {
      const nextValue = history[nextIndex] ?? "";
      setValue(nextValue);
      setCursor(nextValue.length);
      setHistoryIndex(nextIndex);
      return;
    }
    setValue(draftRef.current?.value ?? "");
    setCursor(draftRef.current?.cursor ?? 0);
    setHistoryIndex(null);
    draftRef.current = null;
  }

  function handleClear() {
    setValue("");
    setCursor(0);
    setHistoryIndex(null);
    draftRef.current = null;
  }

  const lineCount = Math.max(1, value.split("\n").length);
  const inputColumns = Math.max(8, (stdout.columns || 80) - 6);

  return (
    <Box borderStyle="round" borderColor={disabled ? defaultTheme.border : defaultTheme.accent} paddingX={1} marginTop={1} flexDirection="column">
      <Box>
        <Text color={disabled ? defaultTheme.muted : defaultTheme.accent}>zzcode</Text>
        <Text color={defaultTheme.muted}> › </Text>
        <Text color={defaultTheme.muted}>{disabled ? "agent is running" : "Enter send · Shift+Enter newline · \\ + Enter continue · Ctrl+_ undo"}</Text>
        <Text color={defaultTheme.muted}> · {lineCount} line{lineCount === 1 ? "" : "s"}</Text>
      </Box>
      {disabled ? (
        <Text color={defaultTheme.muted}>Waiting for agent events...</Text>
      ) : (
        <Box>
          <Text color={defaultTheme.muted}>{"> "}</Text>
          <TextInput
            value={value}
            onChange={handleChange}
            onSubmit={handleSubmit}
            onExit={onExit}
            onHistoryUp={handleHistoryUp}
            onHistoryDown={handleHistoryDown}
            onHistoryReset={() => setHistoryIndex(null)}
            onClearInput={handleClear}
            onUndo={handleUndo}
            columns={inputColumns}
            cursorOffset={cursor}
            onChangeCursorOffset={setCursor}
            multiline
            focus
            showCursor
          />
        </Box>
      )}
    </Box>
  );
}
