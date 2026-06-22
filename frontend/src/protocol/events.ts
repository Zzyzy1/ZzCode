export type AgentEvent =
  | UserMessageEvent
  | AssistantThoughtEvent
  | ToolUseEvent
  | ToolResultEvent
  | AssistantFinalEvent
  | SystemNoticeEvent
  | PermissionRequestEvent
  | RequestDoneEvent;

export type NoticeLevel = "info" | "warning" | "error";

export type UserMessageEvent = {
  type: "user_message";
  text: string;
};

export type AssistantThoughtEvent = {
  type: "assistant_thought";
  text: string;
};

export type ToolUseEvent = {
  type: "tool_use";
  id: string;
  name: string;
  input: unknown;
  displayName?: string;
  source?: string;
  mcpInfo?: McpInfo | null;
};

export type ToolResultEvent = {
  type: "tool_result";
  id: string;
  name: string;
  output: string;
  ok: boolean;
  source?: string;
  mcpInfo?: McpInfo | null;
};

export type AssistantFinalEvent = {
  type: "assistant_final";
  text: string;
};

export type SystemNoticeEvent = {
  type: "system_notice";
  level: NoticeLevel;
  text: string;
};

export type RequestDoneEvent = {
  type: "request_done";
  ok: boolean;
};

export type PermissionRisk = "low" | "medium" | "high";

export type PermissionRequestEvent = {
  type: "permission_request";
  id: string;
  toolCallId?: string;
  toolName: string;
  displayName?: string;
  input: unknown;
  summary?: string;
  isDestructive?: boolean;
  risk: PermissionRisk;
  preview?: PermissionPreview | null;
  source?: string;
  mcpInfo?: McpInfo | null;
};

export type McpInfo = {
  server_name?: string;
  tool_name?: string;
};

export type PermissionDecision = "allow_once" | "allow_session" | "deny";

export type PermissionPreview = WriteFileDiffPreview;

export type WriteFileDiffPreview = {
  type: "write_file_diff";
  path: string;
  fileExists: boolean;
  oldLineCount?: number;
  newLineCount?: number;
  lines?: DiffPreviewLine[];
  truncated?: boolean;
  error?: string;
};

export type DiffPreviewLine = {
  kind: "header" | "context" | "add" | "remove";
  text: string;
};

export type AgentStatus = "idle" | "thinking" | "running_tool" | "done";

export type MessageNode = AgentEvent & {
  key: string;
  createdAt: number;
};
