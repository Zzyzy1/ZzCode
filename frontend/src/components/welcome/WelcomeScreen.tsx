import React from "react";
import { Box, Text } from "ink";
import { defaultTheme } from "../../app/theme.js";

/**
 * 渲染启动欢迎界面。
 * 无入参；返回卡通形象、快捷命令和轻量提示区。
 */
export function WelcomeScreen() {
  return (
    <Box flexDirection="column" gap={1}>
      <Box flexDirection="row" gap={2}>
        <Box borderStyle="round" borderColor={defaultTheme.border} paddingX={2} paddingY={1} flexDirection="column">
          <Text bold color={defaultTheme.accent}>Zz Code</Text>
          <Text color={defaultTheme.muted}>你的 AI 编程助手</Text>
          <Box marginTop={1}>
            <Mascot />
          </Box>
          <Text color={defaultTheme.accent}>欢迎回来。</Text>
          <Text color={defaultTheme.muted}>输入 /help 查看全部命令，也可让 ZzCode 先识别你的项目结构。</Text>
        </Box>

        <Box borderStyle="round" borderColor={defaultTheme.border} paddingX={2} paddingY={1} flexDirection="column">
          <Text color={defaultTheme.accent}>使用提示</Text>
          <Box marginTop={1} flexDirection="column">
            <Tip title="会话上下文" body="如需开启全新会话，可执行 /clear 重置上下文。" />
            <Tip title="文件写入" body="修改文件前会先展示 diff 差异，确认后才会执行写入。" />
            <Tip title="运行模式" body="可通过 /mode readonly（只读）、/mode plan（规划）切换界面模式。" />
          </Box>
        </Box>
      </Box>

      <Box borderStyle="round" borderColor={defaultTheme.border} paddingX={2} paddingY={1} flexDirection="column">
        <Text color={defaultTheme.user}>快捷命令</Text>
        <Box marginTop={1} gap={4}>
          <Command name="/help" description="查看全部命令" />
          <Command name="/mock" description="切换后端引擎" />
          <Command name="/mode" description="切换运行模式" />
          <Command name="/clear" description="清空会话上下文" />
        </Box>
      </Box>
    </Box>
  );
}

function Mascot() {
  return (
    <Box flexDirection="column">
      <Text color={defaultTheme.user}>          z z</Text>
      <Text color={defaultTheme.accent}>        /\___/\</Text>
      <Text color={defaultTheme.accent}>       /       \</Text>
      <Text color={defaultTheme.accent}>      (  - . -  )</Text>
      <Text color={defaultTheme.accent}>       \   ^   /</Text>
      <Text color={defaultTheme.user}>       /  &lt; / \ &gt;  \</Text>
      <Text color={defaultTheme.accent}>      /_________\</Text>
      <Text color={defaultTheme.muted}>          Zz</Text>
    </Box>
  );
}

function Tip({ title, body }: { title: string; body: string }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={defaultTheme.success}>* {title}</Text>
      <Text color={defaultTheme.muted}>  {body}</Text>
    </Box>
  );
}

function Command({ name, description }: { name: string; description: string }) {
  return (
    <Box flexDirection="column">
      <Text color={defaultTheme.accent}>{name}</Text>
      <Text color={defaultTheme.muted}>{description}</Text>
    </Box>
  );
}
