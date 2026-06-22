import React from "react";
import { renderToolResultSummary } from "./toolUiRegistry.js";

type Props = {
  toolName: string;
  output: string;
  ok: boolean;
};

/**
 * 通过工具 renderer 注册表渲染结果。
 * toolName 用于查找专属 renderer；output/ok 来自 tool_result 事件。
 */
export function ToolResultView({ toolName, output, ok }: Props) {
  return renderToolResultSummary(toolName, output, { ok });
}
