"""系统子 Agent worker。"""

from __future__ import annotations

import os
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zzcode.llm.client import ChatClient
from zzcode.logging import log_debug
from zzcode.memory.auto import (
    ensure_auto_memory,
    format_auto_memory_manifest,
    get_auto_memory_dir,
    get_auto_memory_index_path,
    read_auto_memory_index,
    scan_auto_memory_files,
)
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.builtin import build_tool_registry

from .restricted_tool_registry import build_restricted_tool_registry
from .structured_runner import StructuredSubagentRunner, allow_system_tool


SESSION_MEMORY_STATE_FILE = "session-memory-state.json"
SESSION_MEMORY_AGENT_NAME = "session-memory-updater"
AUTO_MEMORY_STATE_FILE = "auto-memory-state.json"
AUTO_MEMORY_AGENT_NAME = "auto-memory-extraction"

SESSION_MEMORY_SYSTEM_PROMPT = """
你是 ZzCode 的系统 Session Memory Updater。

职责：
1. 根据主会话 transcript 增量维护当前 session 的 summary.md。
2. 只更新当前 session memory 文件，不写长期 memory。
3. 需要读写文件时必须使用结构化工具调用。
4. 不要输出 Thought/Action、ToolName[input] 或 Finish[...] 文本协议。
5. 完成后直接给出简短最终回答。
""".strip()

AUTO_MEMORY_SYSTEM_PROMPT = """
你是 ZzCode 的系统 Auto Memory Extraction Worker。

职责：
1. 从主会话 transcript 增量中提取值得长期保留的用户偏好、项目事实、反馈和参考信息。
2. 不保存短期执行步骤、临时调试输出、普通命令结果或只属于当前轮的计划。
3. 需要读写文件时必须使用结构化工具调用。
4. 不要输出 Thought/Action、ToolName[input] 或 Finish[...] 文本协议。
5. 如果没有值得保存的长期记忆，直接最终回答 no durable memory。
""".strip()


@dataclass(frozen=True)
class SessionMemoryUpdateResult:
    """Session memory 更新 worker 的执行结果。"""

    ran: bool
    updated: bool
    event_count: int
    last_summarized_event_id: str | None
    transcript_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AutoMemoryExtractionResult:
    """Auto memory 提取 worker 的执行结果。"""

    ran: bool
    updated: bool
    skipped: bool
    event_count: int
    last_processed_event_id: str | None
    transcript_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SystemAgentSchedulerResult:
    """系统子 Agent 调度结果。"""

    session_memory: SessionMemoryUpdateResult | None = None
    auto_memory: AutoMemoryExtractionResult | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SystemAgentScheduleResult:
    """后台系统子 Agent 调度结果。"""

    scheduled: bool
    pending: bool = False
    disabled: bool = False
    reason: str = ""


class SystemAgentScheduler:
    """按主 Agent 生命周期触发系统子 Agent worker。"""

    def __init__(
        self,
        *,
        project_root: Path,
        parent_scope: SessionScope,
        llm_client: ChatClient,
        max_steps: int = 5,
    ) -> None:
        self.project_root = project_root.resolve()
        self.parent_scope = parent_scope
        self.llm_client = llm_client
        self.max_steps = max_steps
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future[None] | None = None
        self._pending_turn = False
        self._closed = False

    def on_turn_finished(self) -> SystemAgentSchedulerResult:
        """主 Agent 成功回答后，同步执行系统维护任务。"""

        return self._run_turn_finished_once()

    def schedule_turn_finished(self) -> SystemAgentScheduleResult:
        """主 Agent 成功回答后，后台调度系统维护任务。

        若已有任务在运行，只记录 pending，等当前任务结束后合并执行一次。
        """

        if _system_agents_disabled():
            log_debug("background system agents skipped disabled=true", level="debug", component="system-agents")
            return SystemAgentScheduleResult(scheduled=False, disabled=True, reason="disabled")
        if _background_system_agents_disabled():
            result = self._run_turn_finished_once()
            self._log_background_result("synchronous fallback", result)
            return SystemAgentScheduleResult(scheduled=False, reason="background_disabled")

        with self._lock:
            if self._closed:
                return SystemAgentScheduleResult(scheduled=False, reason="closed")
            if self._future is not None and not self._future.done():
                self._pending_turn = True
                log_debug("background system agents coalesced pending=true", level="info", component="system-agents")
                return SystemAgentScheduleResult(scheduled=False, pending=True, reason="in_progress")
            self._ensure_executor_locked()
            self._future = self._executor.submit(self._background_loop) if self._executor is not None else None
            log_debug("background system agents scheduled", level="info", component="system-agents")
            return SystemAgentScheduleResult(scheduled=True, reason="scheduled")

    def drain_pending(self, timeout_seconds: float = 5.0) -> bool:
        """等待后台系统任务完成，超时返回 False。"""

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            with self._lock:
                future = self._future
            if future is None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log_debug("background system agents drain timed out", level="warn", component="system-agents")
                return False
            try:
                future.result(timeout=remaining)
            except TimeoutError:
                log_debug("background system agents drain timed out", level="warn", component="system-agents")
                return False
            except Exception as exc:
                log_debug(f"background system agents future failed during drain: {exc}", level="error", component="system-agents")
                return True

    def close(self, *, timeout_seconds: float = 5.0) -> None:
        """关闭后台调度器。"""

        self.drain_pending(timeout_seconds=timeout_seconds)
        with self._lock:
            self._closed = True
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    def _run_turn_finished_once(self) -> SystemAgentSchedulerResult:
        """执行一次系统维护任务。"""

        errors: list[str] = []
        session_result: SessionMemoryUpdateResult | None = None
        auto_result: AutoMemoryExtractionResult | None = None
        try:
            session_result = self._session_memory_worker().run()
        except Exception as exc:
            errors.append(f"session memory update failed: {exc}")
        try:
            auto_result = self._auto_memory_worker().run()
        except Exception as exc:
            errors.append(f"auto memory extraction failed: {exc}")
        return SystemAgentSchedulerResult(
            session_memory=session_result,
            auto_memory=auto_result,
            errors=tuple(errors),
        )

    def _background_loop(self) -> None:
        """后台串行执行系统维护任务，并合并运行期间产生的新 turn。"""

        while True:
            started_at = time.perf_counter()
            result = self._run_turn_finished_once()
            self._log_background_result("background finished", result, elapsed_ms=(time.perf_counter() - started_at) * 1000)
            with self._lock:
                if self._pending_turn and not self._closed:
                    self._pending_turn = False
                    log_debug("background system agents running trailing update", level="info", component="system-agents")
                    continue
                self._future = None
                return

    def _ensure_executor_locked(self) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zzcode-system-agents")

    def _log_background_result(
        self,
        label: str,
        result: SystemAgentSchedulerResult,
        *,
        elapsed_ms: float | None = None,
    ) -> None:
        parts = [label]
        if elapsed_ms is not None:
            parts.append(f"elapsed_ms={elapsed_ms:.1f}")
        if result.session_memory is not None:
            parts.append(
                "session_memory="
                f"ran:{result.session_memory.ran} "
                f"updated:{result.session_memory.updated} "
                f"events:{result.session_memory.event_count}"
            )
        if result.auto_memory is not None:
            parts.append(
                "auto_memory="
                f"ran:{result.auto_memory.ran} "
                f"updated:{result.auto_memory.updated} "
                f"skipped:{result.auto_memory.skipped} "
                f"events:{result.auto_memory.event_count}"
            )
        if result.errors:
            parts.append("errors=" + " | ".join(result.errors))
        log_debug(" ".join(parts), level="debug", component="system-agents")

    def before_compact(self) -> SystemAgentSchedulerResult:
        """compact 前强制刷新当前 session memory。"""

        try:
            session_result = self._session_memory_worker().run(force=True)
            return SystemAgentSchedulerResult(session_memory=session_result)
        except Exception as exc:
            return SystemAgentSchedulerResult(errors=(f"session memory compact update failed: {exc}",))

    def _session_memory_worker(self) -> "SessionMemoryUpdateWorker":
        return SessionMemoryUpdateWorker(
            project_root=self.project_root,
            parent_scope=self.parent_scope,
            llm_client=self.llm_client,
            max_steps=self.max_steps,
        )

    def _auto_memory_worker(self) -> "AutoMemoryExtractionWorker":
        return AutoMemoryExtractionWorker(
            project_root=self.project_root,
            parent_scope=self.parent_scope,
            llm_client=self.llm_client,
            max_steps=self.max_steps,
        )


class SessionMemoryUpdateWorker:
    """用系统子 Agent 增量更新当前 session summary.md。"""

    def __init__(
        self,
        *,
        project_root: Path,
        parent_scope: SessionScope,
        llm_client: ChatClient,
        max_steps: int = 5,
    ) -> None:
        self.project_root = project_root.resolve()
        self.parent_scope = parent_scope
        self.llm_client = llm_client
        self.max_steps = max_steps
        self.system_dir = parent_scope.session_dir / "system"
        self.state_path = self.system_dir / SESSION_MEMORY_STATE_FILE

    def run(self, *, force: bool = False) -> SessionMemoryUpdateResult:
        """处理 transcript 增量，必要时更新当前 session summary.md。"""

        events = _read_transcript_events(self.parent_scope.transcript_path)
        state = _read_json_object(self.state_path)
        last_event_id = _as_optional_str(state.get("last_summarized_event_id"))
        new_events = _events_after(events, last_event_id)
        if not new_events and not force:
            return SessionMemoryUpdateResult(
                ran=False,
                updated=False,
                event_count=0,
                last_summarized_event_id=last_event_id,
            )

        prompt = self._build_prompt(new_events, force=force)
        runner = StructuredSubagentRunner(
            llm_client=self.llm_client,
            parent_scope=self.parent_scope,
            project_root=self.project_root,
        )
        result = runner.run(
            name=SESSION_MEMORY_AGENT_NAME,
            prompt=prompt,
            description="Update current session memory summary.",
            system_prompt=SESSION_MEMORY_SYSTEM_PROMPT,
            tool_registry=self._build_tool_registry(),
            max_turns=self.max_steps,
            permission_checker=allow_system_tool,
        )
        if not result.ok:
            return SessionMemoryUpdateResult(
                ran=True,
                updated=False,
                event_count=len(new_events),
                last_summarized_event_id=last_event_id,
                transcript_path=result.transcript_path,
                error=result.error,
            )

        summarized_event_id = _last_event_id(new_events) or last_event_id
        self._write_state(summarized_event_id, turn_count=len(new_events))
        return SessionMemoryUpdateResult(
            ran=True,
            updated=True,
            event_count=len(new_events),
            last_summarized_event_id=summarized_event_id,
            transcript_path=result.transcript_path,
        )

    def _build_tool_registry(self):
        return build_restricted_tool_registry(
            build_tool_registry(self.project_root),
            project_root=self.project_root,
            allow_tools={"read_file", "write_file", "edit_file", "append_file"},
            allow_read_paths=[
                self.parent_scope.transcript_path,
                self.parent_scope.session_memory_path,
            ],
            allow_write_paths=[
                self.parent_scope.session_memory_path,
            ],
        )

    def _build_prompt(self, new_events: list[dict[str, Any]], *, force: bool) -> str:
        current_summary = _read_text_or_empty(self.parent_scope.session_memory_path)
        transcript_excerpt = _format_events_for_prompt(new_events)
        force_text = "true" if force else "false"
        return "\n".join(
            [
                "你是 ZzCode 的系统 Session Memory Updater。",
                "目标：根据主会话 transcript 增量，维护当前 session 的 summary.md。",
                "只允许更新当前 session-memory/summary.md，不要写长期 memory。",
                "优先使用 read_file 查看 summary.md，再用 edit_file 或 write_file 更新它。",
                "summary.md 应保持结构化、简洁，保留当前任务、关键文件、下一步和已完成事项。",
                "必须使用结构化工具调用，不要输出 Thought/Action 或 Finish[...] 文本协议。",
                "如果无需修改，直接给出最终回答说明 skipped。",
                "",
                f"Force update: {force_text}",
                f"Summary path: {self._relative_path(self.parent_scope.session_memory_path)}",
                f"Transcript path: {self._relative_path(self.parent_scope.transcript_path)}",
                "",
                "Current summary:",
                current_summary.strip() or "(empty)",
                "",
                "New transcript events:",
                transcript_excerpt or "(no new events)",
                "",
                "完成更新后，直接用最终回答简短说明更新结果。",
            ]
        )

    def _write_state(self, last_event_id: str | None, *, turn_count: int) -> None:
        self.system_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "last_summarized_event_id": last_event_id,
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
            "turn_count": turn_count,
        }
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root))
        except ValueError:
            return str(path)


class AutoMemoryExtractionWorker:
    """用系统子 Agent 从 transcript 增量提取长期记忆。"""

    def __init__(
        self,
        *,
        project_root: Path,
        parent_scope: SessionScope,
        llm_client: ChatClient,
        max_steps: int = 5,
    ) -> None:
        self.project_root = project_root.resolve()
        self.parent_scope = parent_scope
        self.llm_client = llm_client
        self.max_steps = max_steps
        self.system_dir = parent_scope.session_dir / "system"
        self.state_path = self.system_dir / AUTO_MEMORY_STATE_FILE

    def run(self) -> AutoMemoryExtractionResult:
        """处理 transcript 增量，必要时更新长期 auto memory。"""

        ensure_auto_memory(self.project_root)
        events = _read_transcript_events(self.parent_scope.transcript_path)
        state = _read_json_object(self.state_path)
        last_event_id = _as_optional_str(state.get("last_processed_event_id"))
        new_events = _events_after(events, last_event_id)
        if not new_events:
            return AutoMemoryExtractionResult(
                ran=False,
                updated=False,
                skipped=False,
                event_count=0,
                last_processed_event_id=last_event_id,
            )

        if _events_include_auto_memory_write(self.project_root, new_events):
            processed_event_id = _last_event_id(new_events) or last_event_id
            self._write_state(
                processed_event_id,
                last_memory_write_event_id=_last_memory_write_event_id(self.project_root, new_events),
            )
            return AutoMemoryExtractionResult(
                ran=False,
                updated=False,
                skipped=True,
                event_count=len(new_events),
                last_processed_event_id=processed_event_id,
            )

        prompt = self._build_prompt(new_events)
        runner = StructuredSubagentRunner(
            llm_client=self.llm_client,
            parent_scope=self.parent_scope,
            project_root=self.project_root,
        )
        result = runner.run(
            name=AUTO_MEMORY_AGENT_NAME,
            prompt=prompt,
            description="Extract durable auto memory from transcript.",
            system_prompt=AUTO_MEMORY_SYSTEM_PROMPT,
            tool_registry=self._build_tool_registry(),
            max_turns=self.max_steps,
            permission_checker=allow_system_tool,
        )
        if not result.ok:
            return AutoMemoryExtractionResult(
                ran=True,
                updated=False,
                skipped=False,
                event_count=len(new_events),
                last_processed_event_id=last_event_id,
                transcript_path=result.transcript_path,
                error=result.error,
            )

        processed_event_id = _last_event_id(new_events) or last_event_id
        self._write_state(processed_event_id, last_memory_write_event_id=None)
        return AutoMemoryExtractionResult(
            ran=True,
            updated=True,
            skipped=False,
            event_count=len(new_events),
            last_processed_event_id=processed_event_id,
            transcript_path=result.transcript_path,
        )

    def _build_tool_registry(self):
        memory_dir = get_auto_memory_dir(self.project_root)
        return build_restricted_tool_registry(
            build_tool_registry(self.project_root),
            project_root=self.project_root,
            allow_tools={"list_files", "glob", "grep", "read_file", "write_file", "edit_file", "append_file"},
            allow_read_paths=None,
            allow_write_paths=[memory_dir],
        )

    def _build_prompt(self, new_events: list[dict[str, Any]]) -> str:
        memory_index = read_auto_memory_index(self.project_root)
        manifest = format_auto_memory_manifest(scan_auto_memory_files(self.project_root))
        transcript_excerpt = _format_events_for_prompt(new_events)
        return "\n".join(
            [
                "你是 ZzCode 的系统 Auto Memory Extraction Worker。",
                "目标：从主会话 transcript 增量中提取值得长期保留的用户偏好、项目事实、反馈和参考信息。",
                "不要保存短期执行步骤、临时调试输出、普通命令结果或只属于当前轮的计划。",
                "详细记忆必须写入 `.zzcode/memory/user/`、`.zzcode/memory/project/`、`.zzcode/memory/feedback/` 或 `.zzcode/memory/reference/` 下的 Markdown 文件。",
                "每个详细文件建议带 frontmatter：type 和 description。",
                "写入详细文件后，必须更新 `.zzcode/memory/MEMORY.md` 索引；如果没有值得保存的长期记忆，直接最终回答 no durable memory。",
                "优先根据 manifest 更新已有文件，避免重复创建同义记忆。",
                "必须使用结构化工具调用，不要输出 Thought/Action 或 Finish[...] 文本协议。",
                "如果没有值得保存的长期记忆，直接给出最终回答 no durable memory。",
                "",
                f"Memory index path: {self._relative_path(get_auto_memory_index_path(self.project_root))}",
                "",
                "Current MEMORY.md:",
                memory_index.strip() or "(empty)",
                "",
                "Existing memory manifest:",
                manifest or "(none)",
                "",
                "New transcript events:",
                transcript_excerpt or "(no new events)",
                "",
                "完成后直接用最终回答简短说明写入或跳过结果。",
            ]
        )

    def _write_state(self, last_event_id: str | None, *, last_memory_write_event_id: str | None) -> None:
        self.system_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "last_processed_event_id": last_event_id,
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
            "last_memory_write_event_id": last_memory_write_event_id,
        }
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root))
        except ValueError:
            return str(path)


def _read_transcript_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _events_after(events: list[dict[str, Any]], last_event_id: str | None) -> list[dict[str, Any]]:
    if not last_event_id:
        return events
    for index, event in enumerate(events):
        if event.get("eventId") == last_event_id:
            return events[index + 1 :]
    return events


def _last_event_id(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        event_id = event.get("eventId")
        if isinstance(event_id, str) and event_id:
            return event_id
    return None


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _format_events_for_prompt(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        event_type = event.get("type", "unknown")
        sequence = event.get("sequence", "?")
        event_id = event.get("eventId", "")
        payload = _event_payload_text(event)
        lines.append(f"- sequence={sequence} eventId={event_id} type={event_type}: {payload}")
    return "\n".join(lines)


def _event_payload_text(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    if event_type in {"user", "assistant"}:
        return str(event.get("text", "")).strip()
    if event_type == "tool_use":
        return f"{event.get('toolName', '')}[{event.get('input', '')}]"
    if event_type == "tool_result":
        return f"{event.get('toolName', '')} ok={event.get('ok', '')}: {event.get('output', '')}"
    if event_type == "compact_summary":
        return str(event.get("summary", "")).strip()
    return json.dumps(event, ensure_ascii=False, sort_keys=True)


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _events_include_auto_memory_write(project_root: Path, events: list[dict[str, Any]]) -> bool:
    return _last_memory_write_event_id(project_root, events) is not None


def _last_memory_write_event_id(project_root: Path, events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "tool_use":
            continue
        tool_name = event.get("toolName")
        if tool_name not in {"write_file", "edit_file", "append_file"}:
            continue
        tool_input = event.get("input")
        if not isinstance(tool_input, str):
            continue
        path_text = _tool_input_path(tool_name, tool_input)
        if path_text and _path_is_auto_memory_path(project_root, path_text):
            event_id = event.get("eventId")
            return event_id if isinstance(event_id, str) else None
    return None


def _tool_input_path(tool_name: object, tool_input: str) -> str | None:
    if tool_name == "edit_file":
        parts = tool_input.split("|||", 2)
        return parts[0] if len(parts) == 3 else None
    if "|||" not in tool_input:
        return None
    return tool_input.split("|||", 1)[0]


def _path_is_auto_memory_path(project_root: Path, path_text: str) -> bool:
    memory_dir = get_auto_memory_dir(project_root).resolve()
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        candidate.resolve().relative_to(memory_dir)
    except ValueError:
        return False
    return True


def _system_agents_disabled() -> bool:
    raw = os.getenv("ZZCODE_SYSTEM_AGENTS", "1").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _background_system_agents_disabled() -> bool:
    raw = os.getenv("ZZCODE_SYSTEM_AGENTS_BACKGROUND", "1").strip().lower()
    return raw in {"0", "false", "no", "off"}
