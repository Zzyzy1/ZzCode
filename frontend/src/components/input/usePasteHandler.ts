import React from "react";
import type { Key } from "ink";

const PASTE_THRESHOLD = 24;
const PASTE_TIMEOUT_MS = 80;

type Props = {
  onInput: (input: string, key: Key) => void;
  onPaste?: (text: string) => void;
};

/**
 * 参考 Claude 的 paste handler 结构。
 * 当前 Ink 没有暴露 bracketed paste 事件，这里用多字符/多行输入合并成一次 paste。
 */
export function usePasteHandler({ onInput, onPaste }: Props) {
  const [isPasting, setIsPasting] = React.useState(false);
  const chunksRef = React.useRef<string[]>([]);
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushPaste = React.useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    const text = chunksRef.current.join("");
    chunksRef.current = [];
    setIsPasting(false);
    if (text.length > 0) {
      onPaste?.(text);
    }
  }, [onPaste]);

  const wrappedOnInput = React.useCallback((input: string, key: Key) => {
    const looksLikePaste = Boolean(onPaste) && (input.length >= PASTE_THRESHOLD || input.includes("\n"));
    if (!looksLikePaste) {
      onInput(input, key);
      return;
    }

    setIsPasting(true);
    chunksRef.current.push(input);
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(flushPaste, PASTE_TIMEOUT_MS);
  }, [flushPaste, onInput, onPaste]);

  React.useEffect(() => () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
  }, []);

  return { wrappedOnInput, isPasting };
}

