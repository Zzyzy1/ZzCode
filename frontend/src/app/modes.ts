export type AppMode = "default" | "readonly" | "plan";

export const appModes: AppMode[] = ["default", "readonly", "plan"];

export function isAppMode(value: string): value is AppMode {
  return appModes.includes(value as AppMode);
}

export function describeMode(mode: AppMode): string {
  if (mode === "readonly") {
    return "只读观察";
  }
  if (mode === "plan") {
    return "计划模式";
  }
  return "默认模式";
}
