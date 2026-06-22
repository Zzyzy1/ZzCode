import stringWidth from "string-width";
import type { InputRenderLine } from "./textInputTypes.js";

const segmenter = new Intl.Segmenter("zh-CN", { granularity: "grapheme" });

type GraphemePart = {
  text: string;
  start: number;
  end: number;
  width: number;
};

type WrappedLine = {
  start: number;
  end: number;
  text: string;
  width: number;
};

type CursorPosition = {
  line: number;
  column: number;
};

/**
 * 按 Claude 的职责拆出文本测量与光标移动。
 * 负责 grapheme、终端列宽折行、上下左右和渲染切片。
 */
export class Cursor {
  readonly text: string;
  readonly columns: number;
  readonly offset: number;
  readonly lines: WrappedLine[];
  readonly graphemes: GraphemePart[];

  constructor(text: string, columns: number, offset = 0) {
    this.text = text;
    this.columns = Math.max(1, columns);
    this.offset = Math.max(0, Math.min(text.length, offset));
    this.graphemes = splitGraphemes(text);
    this.lines = wrapText(this.graphemes, this.columns);
  }

  static fromText(text: string, columns: number, offset = 0): Cursor {
    return new Cursor(text, columns, offset);
  }

  left(): Cursor {
    return new Cursor(this.text, this.columns, previousOffset(this.graphemes, this.offset));
  }

  right(): Cursor {
    return new Cursor(this.text, this.columns, nextOffset(this.graphemes, this.offset));
  }

  startOfLine(): Cursor {
    const line = this.getCurrentLine();
    return new Cursor(this.text, this.columns, line.start);
  }

  endOfLine(): Cursor {
    const line = this.getCurrentLine();
    return new Cursor(this.text, this.columns, line.end);
  }

  up(): Cursor {
    const currentIndex = this.getCurrentLineIndex();
    if (currentIndex <= 0) {
      return this;
    }
    const targetColumn = this.getPosition().column;
    return new Cursor(this.text, this.columns, offsetForColumn(this.lines[currentIndex - 1]!, this.graphemes, targetColumn));
  }

  down(): Cursor {
    const currentIndex = this.getCurrentLineIndex();
    if (currentIndex >= this.lines.length - 1) {
      return this;
    }
    const targetColumn = this.getPosition().column;
    return new Cursor(this.text, this.columns, offsetForColumn(this.lines[currentIndex + 1]!, this.graphemes, targetColumn));
  }

  insert(text: string): Cursor {
    return new Cursor(
      this.text.slice(0, this.offset) + text + this.text.slice(this.offset),
      this.columns,
      this.offset + text.length,
    );
  }

  backspace(): Cursor {
    if (this.offset <= 0) {
      return this;
    }
    const start = previousOffset(this.graphemes, this.offset);
    return new Cursor(this.text.slice(0, start) + this.text.slice(this.offset), this.columns, start);
  }

  del(): Cursor {
    if (this.offset >= this.text.length) {
      return this;
    }
    const end = nextOffset(this.graphemes, this.offset);
    return new Cursor(this.text.slice(0, this.offset) + this.text.slice(end), this.columns, this.offset);
  }

  deleteToLineStart(): { cursor: Cursor; killed: string } {
    const line = this.getCurrentLine();
    const killed = this.text.slice(line.start, this.offset);
    return {
      cursor: new Cursor(this.text.slice(0, line.start) + this.text.slice(this.offset), this.columns, line.start),
      killed,
    };
  }

  deleteToLineEnd(): { cursor: Cursor; killed: string } {
    const line = this.getCurrentLine();
    const killed = this.text.slice(this.offset, line.end);
    return {
      cursor: new Cursor(this.text.slice(0, this.offset) + this.text.slice(line.end), this.columns, this.offset),
      killed,
    };
  }

  getPosition(): CursorPosition {
    const lineIndex = this.getCurrentLineIndex();
    const line = this.lines[lineIndex]!;
    return {
      line: lineIndex,
      column: stringWidth(this.text.slice(line.start, this.offset)),
    };
  }

  getViewportStartLine(maxVisibleLines?: number): number {
    if (!maxVisibleLines || this.lines.length <= maxVisibleLines) {
      return 0;
    }
    const { line } = this.getPosition();
    const half = Math.floor(maxVisibleLines / 2);
    const start = Math.max(0, line - half);
    return Math.min(start, Math.max(0, this.lines.length - maxVisibleLines));
  }

  getViewportCharOffset(maxVisibleLines?: number): number {
    return this.lines[this.getViewportStartLine(maxVisibleLines)]?.start ?? 0;
  }

  getViewportCharEnd(maxVisibleLines?: number): number {
    if (!maxVisibleLines || this.lines.length <= maxVisibleLines) {
      return this.text.length;
    }
    const startLine = this.getViewportStartLine(maxVisibleLines);
    const endLine = Math.min(this.lines.length, startLine + maxVisibleLines);
    return endLine >= this.lines.length ? this.text.length : (this.lines[endLine]?.start ?? this.text.length);
  }

  renderLines(maxVisibleLines?: number): InputRenderLine[] {
    const currentIndex = this.getCurrentLineIndex();
    const start = this.getViewportStartLine(maxVisibleLines);
    const end = maxVisibleLines ? Math.min(this.lines.length, start + maxVisibleLines) : this.lines.length;
    return this.lines.slice(start, end).map((line, index) => {
      const lineIndex = start + index;
      const hasCursor = lineIndex === currentIndex;
      const before = hasCursor ? this.text.slice(line.start, this.offset) : line.text;
      const cursorChar = hasCursor ? (this.text.slice(this.offset, nextOffset(this.graphemes, this.offset)) || " ") : "";
      const after = hasCursor
        ? this.text.slice(cursorChar === " " ? this.offset : this.offset + cursorChar.length, line.end)
        : "";
      return {
        before: before || (!hasCursor && line.text.length === 0 ? " " : before),
        cursorChar,
        after,
        hasCursor,
      };
    });
  }

  private getCurrentLineIndex(): number {
    for (let index = 0; index < this.lines.length; index += 1) {
      const line = this.lines[index]!;
      const nextLine = this.lines[index + 1];
      if (this.offset < line.start || this.offset > line.end) {
        continue;
      }
      if (this.offset === line.end && nextLine && nextLine.start === this.offset) {
        continue;
      }
      return index;
    }
    return Math.max(0, this.lines.length - 1);
  }

  private getCurrentLine(): WrappedLine {
    return this.lines[this.getCurrentLineIndex()]!;
  }
}

function splitGraphemes(text: string): GraphemePart[] {
  return Array.from(segmenter.segment(text)).map((part) => ({
    text: part.segment,
    start: part.index,
    end: part.index + part.segment.length,
    width: part.segment === "\n" ? 0 : Math.max(1, stringWidth(part.segment)),
  }));
}

function wrapText(graphemes: GraphemePart[], columns: number): WrappedLine[] {
  const lines: WrappedLine[] = [];
  let lineStart = 0;
  let lineText = "";
  let lineWidth = 0;

  for (const part of graphemes) {
    if (part.text === "\n") {
      lines.push({ start: lineStart, end: part.start, text: lineText, width: lineWidth });
      lineStart = part.end;
      lineText = "";
      lineWidth = 0;
      continue;
    }

    if (lineWidth > 0 && lineWidth + part.width > columns) {
      lines.push({ start: lineStart, end: part.start, text: lineText, width: lineWidth });
      lineStart = part.start;
      lineText = "";
      lineWidth = 0;
    }

    lineText += part.text;
    lineWidth += part.width;
  }

  const text = graphemes.length > 0 ? graphemes.map((part) => part.text).join("") : "";
  lines.push({ start: lineStart, end: text.length, text: lineText, width: lineWidth });
  if (text.endsWith("\n")) {
    lines.push({ start: text.length, end: text.length, text: "", width: 0 });
  }
  return lines.length > 0 ? lines : [{ start: 0, end: 0, text: "", width: 0 }];
}

function previousOffset(graphemes: GraphemePart[], offset: number): number {
  let previous = 0;
  for (const part of graphemes) {
    if (part.start >= offset) {
      break;
    }
    previous = part.start;
  }
  return previous;
}

function nextOffset(graphemes: GraphemePart[], offset: number): number {
  for (const part of graphemes) {
    if (part.start > offset) {
      return part.start;
    }
    if (part.start === offset) {
      return part.end;
    }
  }
  return graphemes.at(-1)?.end ?? 0;
}

function offsetForColumn(line: WrappedLine, graphemes: GraphemePart[], targetColumn: number): number {
  if (line.text.length === 0 || targetColumn <= 0) {
    return line.start;
  }
  let width = 0;
  for (const part of graphemes) {
    if (part.start < line.start || part.end > line.end) {
      continue;
    }
    if (width + part.width > targetColumn) {
      return part.start;
    }
    width += part.width;
  }
  return line.end;
}

