import { Chalk } from "chalk";
import { marked, type Token, type Tokens } from "marked";
import stringWidth from "string-width";

const EOL = "\n";
const TOKEN_CACHE_MAX = 500;
const tokenCache = new Map<string, Token[]>();
const MD_SYNTAX_RE = /[#*`|[>\-_~]|\n\n|^\d+\. |\n\d+\. /;
const chalk = new Chalk({ level: 1 });

let markedConfigured = false;

/**
 * 配置 marked 行为，与 Claude 一样避免把近似值里的 ~ 误判为删除线。
 */
export function configureMarked(): void {
  if (markedConfigured) {
    return;
  }
  markedConfigured = true;
  marked.use({
    tokenizer: {
      del() {
        return undefined;
      },
    },
  });
}

export function formatMarkdown(content: string): string {
  configureMarked();
  return cachedLexer(content.replace(/\r\n/g, "\n"))
    .map((token) => formatToken(token, 0, null, null))
    .join("")
    .trim();
}

function cachedLexer(content: string): Token[] {
  if (!hasMarkdownSyntax(content)) {
    return [{
      type: "paragraph",
      raw: content,
      text: content,
      tokens: [{ type: "text", raw: content, text: content }],
    } as Token];
  }

  const key = hashContent(content);
  const hit = tokenCache.get(key);
  if (hit) {
    tokenCache.delete(key);
    tokenCache.set(key, hit);
    return hit;
  }

  const tokens = marked.lexer(content);
  if (tokenCache.size >= TOKEN_CACHE_MAX) {
    const firstKey = tokenCache.keys().next().value;
    if (firstKey !== undefined) {
      tokenCache.delete(firstKey);
    }
  }
  tokenCache.set(key, tokens);
  return tokens;
}

function hasMarkdownSyntax(content: string): boolean {
  return MD_SYNTAX_RE.test(content.length > 500 ? content.slice(0, 500) : content);
}

function formatToken(token: Token, listDepth: number, orderedListNumber: number | null, parent: Token | null): string {
  switch (token.type) {
    case "blockquote":
      return formatBlockquote(token as Tokens.Blockquote);
    case "code":
      return `${(token as Tokens.Code).text}${EOL}`;
    case "codespan":
      return chalk.cyan((token as Tokens.Codespan).text);
    case "em":
      return chalk.italic(formatChildren((token as Tokens.Em).tokens ?? [], listDepth, orderedListNumber, token));
    case "strong":
      return chalk.bold(formatChildren((token as Tokens.Strong).tokens ?? [], listDepth, orderedListNumber, token));
    case "heading":
      return formatHeading(token as Tokens.Heading);
    case "hr":
      return `---${EOL}`;
    case "image":
      return (token as Tokens.Image).href;
    case "link":
      return chalk.cyan(formatChildren((token as Tokens.Link).tokens ?? [], listDepth, orderedListNumber, token));
    case "list":
      return formatList(token as Tokens.List, listDepth);
    case "list_item":
      return formatListItem(token as Tokens.ListItem, listDepth, orderedListNumber);
    case "paragraph":
      return `${formatChildren((token as Tokens.Paragraph).tokens ?? [], listDepth, orderedListNumber, token)}${EOL}`;
    case "space":
    case "br":
      return EOL;
    case "text":
      return formatTextToken(token, listDepth, orderedListNumber, parent);
    case "table":
      return formatTable(token as Tokens.Table);
    case "escape":
      return (token as Tokens.Escape).text;
    default:
      return "text" in token ? String(token.text) : "";
  }
}

function formatChildren(tokens: Token[], listDepth: number, orderedListNumber: number | null, parent: Token | null): string {
  return tokens.map((token) => formatToken(token, listDepth, orderedListNumber, parent)).join("");
}

function formatBlockquote(token: Tokens.Blockquote): string {
  const inner = formatChildren(token.tokens ?? [], 0, null, token);
  return inner
    .split(EOL)
    .map((line) => (line.trim() ? `${chalk.dim("|")} ${chalk.italic(line)}` : line))
    .join(EOL);
}

function formatHeading(token: Tokens.Heading): string {
  const content = formatChildren(token.tokens ?? [], 0, null, token);
  if (token.depth === 1) {
    return `${chalk.bold.italic.underline(content)}${EOL}${EOL}`;
  }
  return `${chalk.bold(content)}${EOL}${EOL}`;
}

function formatList(token: Tokens.List, listDepth: number): string {
  const start = typeof token.start === "number" ? token.start : Number(token.start ?? 1);
  return token.items
    .map((item, index) => formatToken(item, listDepth, token.ordered ? start + index : null, token))
    .join("");
}

function formatListItem(token: Tokens.ListItem, listDepth: number, orderedListNumber: number | null): string {
  const marker = orderedListNumber === null ? "-" : `${orderedListNumber}.`;
  const indent = "  ".repeat(listDepth);
  const body = formatChildren(token.tokens ?? [], listDepth + 1, orderedListNumber, token).trimEnd();
  const lines = body.split(EOL);
  const firstLine = lines.shift() ?? "";
  const markerText = `${indent}${marker} `;
  const continuationIndent = " ".repeat(stringWidth(markerText));
  return [
    `${markerText}${firstLine}`,
    ...lines.map((line) => (line.trim() ? `${continuationIndent}${line}` : line)),
  ].join(EOL) + EOL;
}

function formatTextToken(token: Token, listDepth: number, orderedListNumber: number | null, parent: Token | null): string {
  const maybeNested = token as Token & { tokens?: Token[]; text?: string };
  if (maybeNested.tokens && maybeNested.tokens.length > 0) {
    return formatChildren(maybeNested.tokens, listDepth, orderedListNumber, token);
  }
  return maybeNested.text ?? "";
}

function formatTable(token: Tokens.Table): string {
  const headers = token.header.map((cell) => formatTableCell(cell));
  const rows = token.rows.map((row) => row.map((cell) => formatTableCell(cell)));
  const widths = headers.map((header, index) => {
    const rowWidths = rows.map((row) => stringWidth(row[index] ?? ""));
    return Math.max(3, stringWidth(header), ...rowWidths);
  });

  const renderRow = (cells: string[]) => `| ${cells.map((cell, index) => padEnd(cell, widths[index] ?? 3)).join(" | ")} |`;
  const separator = `|${widths.map((width) => "-".repeat(width + 2)).join("|")}|`;

  return [renderRow(headers), separator, ...rows.map(renderRow)].join(EOL) + EOL;
}

function formatTableCell(cell: Tokens.TableCell): string {
  return formatChildren(cell.tokens ?? [], 0, null, null).trim();
}

function padEnd(value: string, width: number): string {
  return value + " ".repeat(Math.max(0, width - stringWidth(value)));
}

function hashContent(content: string): string {
  let hash = 5381;
  for (let index = 0; index < content.length; index += 1) {
    hash = ((hash << 5) + hash) ^ content.charCodeAt(index);
  }
  return String(hash >>> 0);
}
