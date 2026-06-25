import React from "react";
import type { Key } from "ink";
import { Cursor } from "./Cursor.js";
import type { BaseInputState, BaseTextInputProps } from "./textInputTypes.js";

/**
 * 参考 Claude 的 useTextInput，把按键语义集中在这里。
 */
export function useTextInput(props: BaseTextInputProps): BaseInputState {
  const cursor = React.useMemo(
    () => Cursor.fromText(props.value, Math.max(1, props.columns - 1), props.cursorOffset),
    [props.columns, props.cursorOffset, props.value],
  );

  const cursorChar = props.showCursor ? "|" : "";

  const commitCursor = React.useCallback((next: Cursor) => {
    if (next.text !== props.value) {
      props.onChange(next.text);
    }
    if (next.offset !== props.cursorOffset) {
      props.onChangeCursorOffset(next.offset);
    }
  }, [props]);

  const onInput = React.useCallback((input: string, key: Key) => {
    if (key.ctrl && input === "c") {
      if (props.value.length === 0) {
        props.onExit?.();
        return;
      }
      props.onClearInput?.();
      props.onChange("");
      props.onChangeCursorOffset(0);
      props.onHistoryReset?.();
      return;
    }

    if (key.return) {
      if (props.multiline && (key.shift || props.value[props.cursorOffset - 1] === "\\")) {
        const next = props.value[props.cursorOffset - 1] === "\\" ? cursor.backspace().insert("\n") : cursor.insert("\n");
        commitCursor(next);
        props.onHistoryReset?.();
        return;
      }
      props.onSubmit?.(props.value);
      return;
    }

    if (key.leftArrow) {
      commitCursor(cursor.left());
      return;
    }

    if (key.rightArrow) {
      commitCursor(cursor.right());
      return;
    }

    if (key.upArrow) {
      if (props.disableCursorMovementForUpDownKeys) {
        props.onHistoryUp?.();
        return;
      }
      const next = cursor.up();
      if (next.offset !== cursor.offset) {
        commitCursor(next);
      } else {
        props.onHistoryUp?.();
      }
      return;
    }

    if (key.downArrow) {
      if (props.disableCursorMovementForUpDownKeys) {
        props.onHistoryDown?.();
        return;
      }
      const next = cursor.down();
      if (next.offset !== cursor.offset) {
        commitCursor(next);
      } else {
        props.onHistoryDown?.();
      }
      return;
    }

    if (key.backspace) {
      commitCursor(cursor.backspace());
      props.onHistoryReset?.();
      return;
    }

    if (key.delete) {
      commitCursor(cursor.del());
      props.onHistoryReset?.();
      return;
    }

    if (key.ctrl && input === "a") {
      commitCursor(cursor.startOfLine());
      return;
    }

    if (key.ctrl && input === "e") {
      commitCursor(cursor.endOfLine());
      return;
    }

    if (key.ctrl && input === "u") {
      commitCursor(cursor.deleteToLineStart().cursor);
      props.onHistoryReset?.();
      return;
    }

    if (key.ctrl && input === "k") {
      commitCursor(cursor.deleteToLineEnd().cursor);
      props.onHistoryReset?.();
      return;
    }

    if (key.ctrl && input === "_") {
      props.onUndo?.();
      return;
    }

    if (input && !key.ctrl && !key.meta) {
      commitCursor(cursor.insert(input));
      props.onHistoryReset?.();
    }
  }, [commitCursor, cursor, props]);

  const position = cursor.getPosition();
  return {
    onInput,
    renderedLines: cursor.render(cursorChar, props.maxVisibleLines),
    cursorLine: position.line,
    cursorColumn: position.column,
    viewportCharOffset: cursor.getViewportCharOffset(),
    viewportCharEnd: cursor.getViewportCharEnd(),
  };
}
