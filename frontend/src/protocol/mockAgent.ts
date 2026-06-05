import type { AgentEvent } from "./events.js";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 用 mock 事件模拟 Agent 回合。
 * text 表示用户输入；返回值是前端可直接渲染的事件序列。
 */
export async function* runMockAgent(text: string): AsyncGenerator<AgentEvent> {
  yield { type: "user_message", text };
  await wait(120);

  if (text.trim().startsWith("/")) {
    yield { type: "system_notice", level: "warning", text: "当前 Ink 壳子只处理普通任务，斜杠命令后续接入。" };
    return;
  }

  yield { type: "assistant_thought", text: "我会先判断是否需要调用工具，再汇总结果。" };
  await wait(180);

  yield {
    type: "tool_use",
    id: "mock-readme",
    name: "read_file",
    displayName: "Read",
    input: "README.md"
  };
  await wait(220);

  yield {
    type: "tool_result",
    id: "mock-readme",
    name: "read_file",
    ok: true,
    output: "# ZzCode\n当前展示来自 React + Ink UI 壳子的 mock 工具结果。"
  };
  await wait(160);

  yield {
    type: "assistant_final",
    text: "UI 壳子已经能展示用户输入、思考、工具调用、工具结果和最终回答。下一步可以把 mockAgent 换成 Python JSONL 后端。"
  };
}
