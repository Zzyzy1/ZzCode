import React from "react";
import { Box, Text, useInput } from "ink";
import { defaultTheme } from "../../app/theme.js";
import { usePasteHandler } from "./usePasteHandler.js";
import type { BaseInputState, BaseTextInputProps } from "./textInputTypes.js";

type Props = BaseTextInputProps & {
  inputState: BaseInputState;
};

/**
 * 参考 Claude 的 BaseTextInput：每行独立 `<Text>` 渲染，避免 \n 拼接导致
 * Ink 二次折行。避免用定时器刷新光标，否则会在用户滚动时强制重绘整屏。
 */
export function BaseTextInput({ inputState, ...props }: Props) {
  const { wrappedOnInput, isPasting } = usePasteHandler({
    onInput: inputState.onInput,
    onPaste: props.onPaste ? (text) => {
      props.onPaste?.(text);
      props.onChange(
        props.value.slice(0, props.cursorOffset) + text + props.value.slice(props.cursorOffset),
      );
      props.onChangeCursorOffset(props.cursorOffset + text.length);
      props.onHistoryReset?.();
    } : undefined,
  });

  React.useEffect(() => {
    props.onIsPastingChange?.(isPasting);
  }, [isPasting, props]);

  useInput(wrappedOnInput, { isActive: props.focus ?? true });

  const showCursor = props.showCursor ?? true;

  return (
    <Box flexDirection="column">
      {inputState.renderedLines.map((line, index) => (
        <Text key={index}>
          {line.before}
          {line.hasCursor && showCursor ? (
            <Text color={defaultTheme.accent}>{line.cursorChar}</Text>
          ) : (
            line.cursorChar
          )}
          {line.after}
        </Text>
      ))}
    </Box>
  );
}
