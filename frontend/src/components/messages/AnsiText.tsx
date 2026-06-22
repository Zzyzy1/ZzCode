import React from "react";
import { Text } from "ink";

type Props = {
  children: string;
  dimColor?: boolean;
};

type StyleState = {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  dimColor: boolean;
  color?: string;
};

type Segment = StyleState & {
  text: string;
};

const ANSI_PATTERN = /\x1b\[([0-9;]*)m/g;

/**
 * 渲染 ANSI SGR 样式字符串。
 * Markdown formatter 负责生成 ANSI；这里只把样式落到 Ink Text 上。
 */
export function AnsiText({ children, dimColor = false }: Props) {
  const segments = React.useMemo(() => parseAnsi(children, dimColor), [children, dimColor]);

  return (
    <Text>
      {segments.map((segment, index) => (
        <Text
          key={index}
          bold={segment.bold}
          italic={segment.italic}
          underline={segment.underline}
          dimColor={segment.dimColor}
          color={segment.color}
        >
          {segment.text}
        </Text>
      ))}
    </Text>
  );
}

function parseAnsi(value: string, baseDimColor: boolean): Segment[] {
  const segments: Segment[] = [];
  let style: StyleState = {
    bold: false,
    italic: false,
    underline: false,
    dimColor: baseDimColor,
  };
  let cursor = 0;

  for (const match of value.matchAll(ANSI_PATTERN)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ ...style, text: value.slice(cursor, start) });
    }
    style = applySgr(style, match[1] ?? "", baseDimColor);
    cursor = start + match[0].length;
  }

  if (cursor < value.length) {
    segments.push({ ...style, text: value.slice(cursor) });
  }

  return segments.length > 0 ? segments : [{ ...style, text: "" }];
}

function applySgr(current: StyleState, rawCodes: string, baseDimColor: boolean): StyleState {
  const codes = rawCodes === "" ? [0] : rawCodes.split(";").map((part) => Number(part || 0));
  let next = { ...current };

  for (let index = 0; index < codes.length; index += 1) {
    const code = codes[index] ?? 0;
    if (code === 0) {
      next = { bold: false, italic: false, underline: false, dimColor: baseDimColor };
    } else if (code === 1) {
      next.bold = true;
    } else if (code === 2) {
      next.dimColor = true;
    } else if (code === 3) {
      next.italic = true;
    } else if (code === 4) {
      next.underline = true;
    } else if (code === 22) {
      next.bold = false;
      next.dimColor = baseDimColor;
    } else if (code === 23) {
      next.italic = false;
    } else if (code === 24) {
      next.underline = false;
    } else if (code === 39) {
      next.color = undefined;
    } else if (code >= 30 && code <= 37) {
      next.color = ansiBasicColor(code);
    } else if (code >= 90 && code <= 97) {
      next.color = ansiBrightColor(code);
    }
  }

  return next;
}

function ansiBasicColor(code: number): string {
  return ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"][code - 30] ?? "white";
}

function ansiBrightColor(code: number): string {
  return ["gray", "redBright", "greenBright", "yellowBright", "blueBright", "magentaBright", "cyanBright", "whiteBright"][code - 90] ?? "white";
}

