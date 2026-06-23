export type InputRenderLine = {
  before: string;
  cursorChar: string;
  after: string;
  hasCursor: boolean;
};

export type BaseTextInputProps = {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly onSubmit?: (value: string) => void;
  readonly onExit?: () => void;
  readonly onHistoryUp?: () => void;
  readonly onHistoryDown?: () => void;
  readonly onHistoryReset?: () => void;
  readonly onClearInput?: () => void;
  readonly onUndo?: () => void;
  readonly columns: number;
  readonly cursorOffset: number;
  readonly onChangeCursorOffset: (offset: number) => void;
  readonly focus?: boolean;
  readonly multiline?: boolean;
  readonly showCursor?: boolean;
  readonly maxVisibleLines?: number;
  readonly onPaste?: (text: string) => void;
  readonly onIsPastingChange?: (isPasting: boolean) => void;
  readonly disableCursorMovementForUpDownKeys?: boolean;
};

export type BaseInputState = {
  onInput: (input: string, key: import("ink").Key) => void;
  renderedLines: InputRenderLine[];
  cursorLine: number;
  cursorColumn: number;
  viewportCharOffset: number;
  viewportCharEnd: number;
};

