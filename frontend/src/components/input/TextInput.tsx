import React from "react";
import { BaseTextInput } from "./BaseTextInput.js";
import { useTextInput } from "./useTextInput.js";
import type { BaseTextInputProps } from "./textInputTypes.js";

/**
 * 参考 Claude 的 TextInput：负责把 props 交给输入 hook 和基类渲染。
 */
export function TextInput(props: BaseTextInputProps) {
  const inputState = useTextInput(props);
  return <BaseTextInput {...props} inputState={inputState} />;
}

