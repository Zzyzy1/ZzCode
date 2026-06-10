import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export type MemoryTarget = "user" | "project" | "local" | "session";

const sessionNotesTemplate = `# Session Title
_A short and distinctive 5-10 word descriptive title for the session._

# Current State
_What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps._

# Task Specification
_What did the user ask to build? Any design decisions or other explanatory context._

# Files and Functions
_What are the important files? In short, what do they contain and why are they relevant?_

# Workflow
_What commands are usually run and in what order? How to interpret their output if not obvious?_

# Errors & Corrections
_Errors encountered and how they were fixed. What did the user correct? What approaches failed?_

# Learnings
_What has worked well? What has not? What to avoid?_

# Worklog
_Step by step, what was attempted and completed? Keep this terse._
`;

type MemoryFileStatus = {
  label: string;
  path: string;
  exists: boolean;
  description: string;
};

export async function formatMemoryList(): Promise<string> {
  const statuses = await Promise.all(memoryFileStatuses().map(async (entry) => ({
    ...entry,
    exists: await pathExists(entry.path)
  })));

  const lines = ["Memory files:"];
  for (const status of statuses) {
    const marker = status.exists ? "exists" : "missing";
    lines.push(`${status.label.padEnd(16)} ${marker.padEnd(7)} ${status.path}`);
    if (status.description) {
      lines.push(`${"".padEnd(25)} ${status.description}`);
    }
  }
  return lines.join("\n");
}

export async function openMemoryFile(target: MemoryTarget): Promise<string> {
  const memoryPath = memoryPathForTarget(target);
  await mkdir(path.dirname(memoryPath), { recursive: true });

  try {
    await writeFile(memoryPath, initialContentForTarget(target), { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if (!isAlreadyExistsError(error)) {
      throw error;
    }
  }

  const editor = resolveEditor();
  await runEditor(editor.command, editor.args, memoryPath);
  return [
    `已打开记忆文件：${memoryPath}`,
    editor.source === "default"
      ? "未设置 $VISUAL 或 $EDITOR，已使用默认编辑器。"
      : `使用 ${editor.source}="${editor.commandLine}"。`
  ].join("\n");
}

export function memoryCommandHelp(): string {
  return [
    "Memory commands:",
    "  /memory list      查看记忆文件状态",
    "  /memory user      编辑用户记忆",
    "  /memory project   编辑项目记忆",
    "  /memory local     编辑本地私有项目记忆",
    "  /memory session   编辑当前项目 session notes"
  ].join("\n");
}

function memoryFileStatuses(): Array<Omit<MemoryFileStatus, "exists">> {
  const projectRoot = resolveProjectRoot();
  return [
    {
      label: "User memory",
      path: path.join(os.homedir(), ".zzcode", "ZZCODE.md"),
      description: "跨项目用户偏好和长期说明"
    },
    {
      label: "Project memory",
      path: path.join(projectRoot, "ZZCODE.md"),
      description: "项目共享说明，适合提交仓库"
    },
    {
      label: "Project memory",
      path: path.join(projectRoot, ".zzcode", "ZZCODE.md"),
      description: ".zzcode 下的项目共享说明"
    },
    {
      label: "Project rules",
      path: path.join(projectRoot, ".zzcode", "rules", "*.md"),
      description: "规则文件目录，后续可由 @include 引用"
    },
    {
      label: "Local memory",
      path: path.join(projectRoot, "ZZCODE.local.md"),
      description: "本地私有项目说明，不适合提交仓库"
    },
    {
      label: "Session notes",
      path: path.join(projectRoot, ".zzcode", "session", "notes.md"),
      description: "当前项目的会话记忆 Markdown，暂时手动维护"
    }
  ];
}

function memoryPathForTarget(target: MemoryTarget): string {
  const projectRoot = resolveProjectRoot();
  if (target === "user") {
    return path.join(os.homedir(), ".zzcode", "ZZCODE.md");
  }
  if (target === "project") {
    return path.join(projectRoot, "ZZCODE.md");
  }
  if (target === "session") {
    return path.join(projectRoot, ".zzcode", "session", "notes.md");
  }
  return path.join(projectRoot, "ZZCODE.local.md");
}

function initialContentForTarget(target: MemoryTarget): string {
  return target === "session" ? sessionNotesTemplate : "";
}

function resolveProjectRoot(): string {
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.resolve(cwd, "..") : cwd;
}

async function pathExists(value: string): Promise<boolean> {
  const normalized = value.endsWith("*.md") ? path.dirname(value) : value;
  try {
    await access(normalized, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function resolveEditor(): { command: string; args: string[]; commandLine: string; source: string } {
  const configured = process.env.VISUAL || process.env.EDITOR;
  if (configured) {
    const [command, ...args] = splitCommand(configured);
    return {
      command,
      args,
      commandLine: configured,
      source: process.env.VISUAL ? "$VISUAL" : "$EDITOR"
    };
  }
  const command = process.platform === "win32" ? "notepad" : "nano";
  return {
    command,
    args: [],
    commandLine: command,
    source: "default"
  };
}

function splitCommand(commandLine: string): string[] {
  const matches = commandLine.match(/(?:[^\s"]+|"[^"]*")+/g) ?? [];
  return matches.map((part) => part.replace(/^"|"$/g, ""));
}

function runEditor(command: string, args: string[], memoryPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...args, memoryPath], {
      stdio: "inherit",
      shell: process.platform === "win32"
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`editor exited with code ${code}`));
    });
  });
}

function isAlreadyExistsError(error: unknown): boolean {
  return error instanceof Error && "code" in error && error.code === "EEXIST";
}
