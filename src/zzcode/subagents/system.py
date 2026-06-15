"""系统子 Agent worker。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zzcode.llm.client import ThinkClient
from zzcode.memory.auto import (
    ensure_auto_memory,
    format_auto_memory_manifest,
    get_auto_memory_dir,
    get_auto_memory_index_path,
    read_auto_memory_index,
    scan_auto_memory_files,
)
from zzcode.memory.session_scope import SessionScope
from zzcode.tools.builtin import register_builtin_tools
from zzcode.tools.executor import ToolExecutor

from .forked_runner import ForkedAgentRunner, ForkedAgentResult
from .restricted_tool_executor import RestrictedToolExecutor


SESSION_MEMORY_STATE_FILE = "session-memory-state.json"
SESSION_MEMORY_AGENT_NAME = "session-memory-updater"
AUTO_MEMORY_STATE_FILE = "auto-memory-state.json"
AUTO_MEMORY_AGENT_NAME = "auto-memory-extraction"


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


class SystemAgentScheduler:
    """按主 Agent 生命周期触发系统子 Agent worker。"""

    def __init__(
        self,
        *,
        project_root: Path,
        parent_scope: SessionScope,
        llm_client: ThinkClient,
        max_steps: int = 5,
    ) -> None:
        self.project_root = project_root.resolve()
        self.parent_scope = parent_scope
        self.llm_client = llm_client
        self.max_steps = max_steps

    def on_turn_finished(self) -> SystemAgentSchedulerResult:
        """主 Agent 成功回答后，同步执行系统维护任务。"""

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
        llm_client: ThinkClient,
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
        runner = ForkedAgentRunner(
            llm_client=self.llm_client,
            parent_scope=self.parent_scope,
            tool_executor=self._build_tool_executor(),
        )
        result = runner.run(
            name=SESSION_MEMORY_AGENT_NAME,
            prompt=prompt,
            description="Update current session memory summary.",
            max_steps=self.max_steps,
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

    def _build_tool_executor(self) -> RestrictedToolExecutor:
        base_tools = ToolExecutor()
        register_builtin_tools(base_tools, self.project_root)
        return RestrictedToolExecutor(
            base_tools,
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
                "完成更新后，用 Finish[...] 简短说明更新结果。",
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
        llm_client: ThinkClient,
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
        runner = ForkedAgentRunner(
            llm_client=self.llm_client,
            parent_scope=self.parent_scope,
            tool_executor=self._build_tool_executor(),
        )
        result = runner.run(
            name=AUTO_MEMORY_AGENT_NAME,
            prompt=prompt,
            description="Extract durable auto memory from transcript.",
            max_steps=self.max_steps,
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

    def _build_tool_executor(self) -> RestrictedToolExecutor:
        base_tools = ToolExecutor()
        register_builtin_tools(base_tools, self.project_root)
        memory_dir = get_auto_memory_dir(self.project_root)
        return RestrictedToolExecutor(
            base_tools,
            project_root=self.project_root,
            allow_tools={"list_files", "read_file", "write_file", "edit_file", "append_file"},
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
                "写入详细文件后，必须更新 `.zzcode/memory/MEMORY.md` 索引；如果没有值得保存的长期记忆，直接 Finish[no durable memory]。",
                "优先根据 manifest 更新已有文件，避免重复创建同义记忆。",
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
                "完成后用 Finish[...] 简短说明写入或跳过结果。",
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
