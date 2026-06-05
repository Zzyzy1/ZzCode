import React from "react";
import { Box } from "ink";

type Props = {
  children: React.ReactNode;
};

/**
 * 顶层全屏布局。
 * children 是 REPL 的主要区域；返回稳定的纵向终端布局。
 */
export function FullscreenLayout({ children }: Props) {
  return (
    <Box flexDirection="column" paddingX={1}>
      {children}
    </Box>
  );
}
