import React, { Fragment } from "react";
import { Box, Text, useInput } from "ink";
import { usePasteHandler } from "./usePasteHandler.js";
import type { BaseInputState, BaseTextInputProps } from "./textInputTypes.js";

type Props = BaseTextInputProps & {
  inputState: BaseInputState;
};

/**
 * 参考 Claude 的 BaseTextInput：只渲染连续文本块，不自己做布局。
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

  return (
    <Box>
      <Text>
        {inputState.lines.map((line, index) => (
          <Fragment key={index}>
            {index > 0 ? "\n" : null}
            {line.before}
            {line.hasCursor && (props.showCursor ?? true) ? <Text inverse>{line.cursorChar}</Text> : line.hasCursor ? line.cursorChar : null}
            {line.after}
          </Fragment>
        ))}
      </Text>
    </Box>
  );
}

