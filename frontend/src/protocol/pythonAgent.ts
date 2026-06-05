import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import type { AgentEvent, PermissionDecision, PermissionRequestEvent } from "./events.js";

type ProtocolRequest =
  | { type: "user_message"; text: string }
  | { type: "clear_history" }
  | { type: "shutdown" }
  | { type: "permission_response"; id: string; decision: PermissionDecision };

type RequestOptions = {
  onPermission?: (event: PermissionRequestEvent) => Promise<PermissionDecision>;
};

let sharedSession: PythonAgentSession | null = null;

/**
 * 运行一次 Python Agent 请求。
 * text 是用户输入；返回常驻 Python JSONL 后端产生的事件流。
 */
export async function* runPythonAgent(text: string, options: RequestOptions = {}): AsyncGenerator<AgentEvent> {
  yield* getPythonSession().request({ type: "user_message", text }, options);
}

/**
 * 清空 Python 后端会话历史。
 * 返回后端确认事件，供前端显示状态。
 */
export async function* clearPythonSession(): AsyncGenerator<AgentEvent> {
  yield* getPythonSession().request({ type: "clear_history" });
}

export function shutdownPythonSession(): void {
  sharedSession?.shutdown();
  sharedSession = null;
}

function getPythonSession(): PythonAgentSession {
  if (!sharedSession || sharedSession.closed) {
    sharedSession = new PythonAgentSession();
  }
  return sharedSession;
}

class PythonAgentSession {
  private child: ChildProcessWithoutNullStreams;
  private queue = new EventQueue();
  private stderr = "";
  closed = false;

  constructor() {
    this.child = this.spawnBackend();
    this.bindOutput();
  }

  /**
   * 向常驻后端发送一个请求。
   * request 是 JSONL 协议请求；返回直到 request_done 为止的事件流。
   */
  async *request(request: ProtocolRequest, options: RequestOptions = {}): AsyncGenerator<AgentEvent> {
    if (this.closed) {
      yield { type: "system_notice", level: "error", text: "Python 后端已经关闭。" };
      return;
    }

    this.child.stdin.write(`${JSON.stringify(request)}\n`, "utf8");

    while (true) {
      const event = await this.queue.next();
      if (event.type === "request_done") {
        return;
      }
      if (event.type === "permission_request") {
        yield event;
        const decision = await requestPermission(event, options);
        this.child.stdin.write(`${JSON.stringify({ type: "permission_response", id: event.id, decision })}\n`, "utf8");
        continue;
      }
      yield event;
    }
  }

  shutdown(): void {
    if (this.closed) {
      return;
    }
    this.child.stdin.write(`${JSON.stringify({ type: "shutdown" })}\n`, "utf8");
    this.child.kill();
    this.closed = true;
  }

  private spawnBackend(): ChildProcessWithoutNullStreams {
    const projectRoot = resolveProjectRoot();
    const pythonPath = process.env.ZZCODE_PYTHON ?? "python";

    return spawn(pythonPath, ["-m", "zzcode.protocol.server"], {
      cwd: projectRoot,
      env: {
        ...process.env,
        ZZCODE_PROJECT_ROOT: projectRoot,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
        PYTHONPATH: joinPythonPath(path.join(projectRoot, "src"), process.env.PYTHONPATH)
      },
      stdio: ["pipe", "pipe", "pipe"]
    });
  }

  private bindOutput(): void {
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (chunk) => {
      this.stderr += chunk;
    });

    const lines = createInterface({
      input: this.child.stdout,
      crlfDelay: Infinity
    });

    // stdout 只承载 JSON Lines；stderr 保留模型日志和 Python 异常，便于协议稳定解析。
    lines.on("line", (line) => {
      const event = parseAgentEvent(line);
      if (event) {
        this.queue.push(event);
      }
    });

    this.child.on("close", (code) => {
      this.closed = true;
      this.queue.push({
        type: "system_notice",
        level: code === 0 ? "info" : "error",
        text: code === 0 ? "Python 后端已退出。" : compactError(this.stderr) || `Python 后端退出码: ${code}`
      });
      this.queue.push({ type: "request_done", ok: code === 0 });
    });

    this.child.on("error", (error) => {
      this.closed = true;
      this.queue.push({ type: "system_notice", level: "error", text: `无法启动 Python 后端: ${error.message}` });
      this.queue.push({ type: "request_done", ok: false });
    });
  }
}

async function requestPermission(event: PermissionRequestEvent, options: RequestOptions): Promise<PermissionDecision> {
  if (!options.onPermission) {
    return event.risk === "low" ? "allow_once" : "deny";
  }
  return options.onPermission(event);
}

class EventQueue {
  private events: AgentEvent[] = [];
  private waiters: Array<(event: AgentEvent) => void> = [];

  /**
   * 推入后端事件。
   * event 是解析后的 AgentEvent；无返回值。
   */
  push(event: AgentEvent): void {
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter(event);
      return;
    }
    this.events.push(event);
  }

  /**
   * 读取下一个事件。
   * 没有事件时挂起等待；返回队列中的下一条 AgentEvent。
   */
  next(): Promise<AgentEvent> {
    const event = this.events.shift();
    if (event) {
      return Promise.resolve(event);
    }
    return new Promise((resolve) => {
      this.waiters.push(resolve);
    });
  }
}

function parseAgentEvent(line: string): AgentEvent | null {
  const text = line.trim();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as AgentEvent;
  } catch {
    return { type: "system_notice", level: "warning", text: `忽略非 JSONL 输出: ${text}` };
  }
}

function resolveProjectRoot(): string {
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.resolve(cwd, "..") : cwd;
}

function joinPythonPath(projectSrc: string, current?: string): string {
  return current ? `${projectSrc}${path.delimiter}${current}` : projectSrc;
}

function compactError(value: string): string {
  const text = value.trim();
  return text.length > 600 ? `${text.slice(0, 597)}...` : text;
}
