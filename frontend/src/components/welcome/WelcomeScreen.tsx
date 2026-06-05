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
          <Text color={defaultTheme.muted}>AI coding assistant in your terminal</Text>
          <Box marginTop={1}>
            <Mascot />
          </Box>
          <Text color={defaultTheme.accent}>Welcome back.</Text>
          <Text color={defaultTheme.muted}>Start with /help or ask ZzCode to inspect your project.</Text>
        </Box>

        <Box borderStyle="round" borderColor={defaultTheme.border} paddingX={2} paddingY={1} flexDirection="column">
          <Text color={defaultTheme.accent}>Tips & updates</Text>
          <Box marginTop={1} flexDirection="column">
            <Tip title="Project context" body="Use /clear when you want a fresh short session." />
            <Tip title="Tooling" body="File writes show a diff before permission confirmation." />
            <Tip title="Modes" body="Try /mode readonly or /mode plan for UI mode switching." />
          </Box>
        </Box>
      </Box>

      <Box borderStyle="round" borderColor={defaultTheme.border} paddingX={2} paddingY={1} flexDirection="column">
        <Text color={defaultTheme.user}>Quick commands</Text>
        <Box marginTop={1} gap={4}>
          <Command name="/help" description="Show commands" />
          <Command name="/mock" description="Toggle backend" />
          <Command name="/mode" description="Switch mode" />
          <Command name="/clear" description="Clear session" />
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
