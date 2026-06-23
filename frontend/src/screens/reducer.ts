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
  assistant_delta: "thinking",
  assistant_thought: "thinking",
  tool_use: "running_tool",
  tool_result: "thinking",
  assistant_final: "done",
  system_notice: "idle",
  permission_request: "running_tool",
  request_done: "idle",
  subagent_start: "running_tool",
  subagent_tool_use: "running_tool",
  subagent_tool_result: "running_tool",
  subagent_done: "thinking"
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
  const status = statusByEvent[event.type];

  // assistant_delta 合并逻辑：连续 delta 拼接到同一条临时消息
  if (event.type === "assistant_delta") {
    const messages = state.messages;
    const last = messages[messages.length - 1];
    if (last && last.type === "assistant_delta") {
      // 追加到上一条 delta，不新增消息
      return {
        messages: [
          ...messages.slice(0, -1),
          {
            ...last,
            text: last.text + event.text,
            createdAt: Date.now()
          }
        ],
        status,
        lastToolName: state.lastToolName
      };
    }
    // 新建 delta 消息
    return {
      messages: [
        ...messages,
        {
          ...event,
          key: `${Date.now()}-${messages.length}-${event.type}`,
          createdAt: Date.now()
        }
      ],
      status,
      lastToolName: state.lastToolName
    };
  }

  // assistant_final 替换前置 delta：避免最终答案和 delta 重复显示
  if (event.type === "assistant_final") {
    let messages = state.messages;
    const last = messages[messages.length - 1];
    if (last && last.type === "assistant_delta") {
      // 移除最后一条 delta，用 assistant_final 替代
      messages = messages.slice(0, -1);
    }
    return {
      messages: [
        ...messages,
        {
          ...event,
          key: `${Date.now()}-${messages.length}-${event.type}`,
          createdAt: Date.now()
        }
      ],
      status,
      lastToolName: state.lastToolName
    };
  }

  // assistant_thought 替换前置 delta：工具调用前的文本流已经收口为 Thought
  if (event.type === "assistant_thought") {
    let messages = state.messages;
    const last = messages[messages.length - 1];
    if (last && last.type === "assistant_delta") {
      // 移除最后一条 delta，用 assistant_thought 替代
      messages = messages.slice(0, -1);
    }
    return {
      messages: [
        ...messages,
        {
          ...event,
          key: `${Date.now()}-${messages.length}-${event.type}`,
          createdAt: Date.now()
        }
      ],
      status,
      lastToolName: state.lastToolName
    };
  }

  // 默认：追加新消息
  return {
    messages: [
      ...state.messages,
      {
        ...event,
        key: `${Date.now()}-${state.messages.length}-${event.type}`,
        createdAt: Date.now()
      }
    ],
    status,
    lastToolName: event.type === "tool_use" ? event.name : state.lastToolName
  };
}
