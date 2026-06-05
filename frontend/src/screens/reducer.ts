import type { AgentEvent, AgentStatus, MessageNode } from "../protocol/events.js";

export type ReplState = {
  messages: MessageNode[];
  status: AgentStatus;
  lastToolName?: string;
};

export type ReplAction =
  | { type: "append_event"; event: AgentEvent }
  | { type: "set_status"; status: AgentStatus; lastToolName?: string }
  | { type: "clear" };

const statusByEvent: Record<AgentEvent["type"], AgentStatus> = {
  user_message: "thinking",
  assistant_thought: "thinking",
  tool_use: "running_tool",
  tool_result: "thinking",
  assistant_final: "done",
  system_notice: "idle",
  permission_request: "running_tool",
  request_done: "idle"
};

/**
 * 集中维护 REPL 状态。
 * state 是当前消息和运行状态；action 是 UI 或 Agent 事件；返回新的状态对象。
 */
export function replReducer(state: ReplState, action: ReplAction): ReplState {
  if (action.type === "clear") {
    return { messages: [], status: "idle" };
  }

  if (action.type === "set_status") {
    return { ...state, status: action.status, lastToolName: action.lastToolName };
  }

  const event = action.event;
  return {
    messages: [
      ...state.messages,
      {
        ...event,
        key: `${Date.now()}-${state.messages.length}-${event.type}`,
        createdAt: Date.now()
      }
    ],
    status: statusByEvent[event.type],
    lastToolName: event.type === "tool_use" ? event.name : state.lastToolName
  };
}
