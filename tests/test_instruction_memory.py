import json
import os
from pathlib import Path

from zzcode.memory import (
    DEFAULT_AUTO_MEMORY_INDEX,
    DEFAULT_SESSION_MEMORY_TEMPLATE,
    DEFAULT_SESSION_NOTES_TEMPLATE,
    ShortTermSessionMemory,
    TranscriptRecorder,
    analyze_session_memory_sections,
    build_memory_context,
    build_session_memory_size_reminders,
    create_session_scope,
    ensure_auto_memory,
    ensure_session_notes_file,
    format_auto_memory_manifest,
    format_compact_summary,
    format_current_session_memory,
    format_instruction_memories,
    format_session_notes,
    get_auto_memory_dir,
    get_auto_memory_index_path,
    get_instruction_memory_files,
    get_session_dir,
    get_session_notes_path,
    get_sessions_dir,
    load_instruction_memories,
    read_auto_memory_file,
    read_auto_memory_index,
    read_current_session_memory,
    read_session_notes,
    scan_auto_memory_files,
    is_session_memory_empty,
    truncate_session_memory_for_compact,
)
from zzcode.agent.react_text import REACT_PROMPT_TEMPLATE
from zzcode.cli.main import build_tools
from zzcode.protocol.server import _is_auto_allowed_memory_tool
from zzcode.tools.builtin import append_file, edit_file, read_file, write_file


def test_instruction_memory_candidates_are_ordered(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    project_root.mkdir()
    home.mkdir()

    files = get_instruction_memory_files(project_root, home=home)

    assert [item.priority for item in files] == [10, 20, 30, 40, 50]
    assert [item.memory_type for item in files] == [
        "user",
        "project",
        "project",
        "rule",
        "local",
    ]
    assert files[0].path == home / ".zzcode" / "ZZCODE.md"
    assert files[1].path == project_root / "ZZCODE.md"
    assert files[2].path == project_root / ".zzcode" / "ZZCODE.md"
    assert files[3].path == project_root / ".zzcode" / "rules" / "*.md"
    assert files[3].is_pattern is True
    assert files[4].path == project_root / "ZZCODE.local.md"


def test_instruction_memory_candidates_track_existence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    (home / ".zzcode").mkdir(parents=True)
    (project_root / ".zzcode" / "rules").mkdir(parents=True)
    (home / ".zzcode" / "ZZCODE.md").write_text("user memory", encoding="utf-8")
    (project_root / "ZZCODE.local.md").write_text("local memory", encoding="utf-8")

    files = get_instruction_memory_files(project_root, home=home)

    assert files[0].exists is True
    assert files[1].exists is False
    assert files[2].exists is False
    assert files[3].exists is True
    assert files[4].exists is True


def test_load_instruction_memories_skips_missing_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    project_root.mkdir()
    home.mkdir()

    memories = load_instruction_memories(project_root, home=home)

    assert memories == []


def test_load_instruction_memories_reads_existing_files_in_priority_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    (home / ".zzcode").mkdir(parents=True)
    (project_root / ".zzcode").mkdir(parents=True)
    home_memory = home / ".zzcode" / "ZZCODE.md"
    project_memory = project_root / "ZZCODE.md"
    dot_project_memory = project_root / ".zzcode" / "ZZCODE.md"
    local_memory = project_root / "ZZCODE.local.md"
    home_memory.write_text("user memory", encoding="utf-8")
    project_memory.write_text("project memory", encoding="utf-8")
    dot_project_memory.write_text("dot project memory", encoding="utf-8")
    local_memory.write_text("local memory", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path for memory in memories] == [
        home_memory,
        project_memory,
        dot_project_memory,
        local_memory,
    ]
    assert [memory.content for memory in memories] == [
        "user memory",
        "project memory",
        "dot project memory",
        "local memory",
    ]


def test_load_instruction_memories_expands_rules_in_name_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    rules_dir = project_root / ".zzcode" / "rules"
    home.mkdir()
    rules_dir.mkdir(parents=True)
    (rules_dir / "02-frontend.md").write_text("frontend", encoding="utf-8")
    (rules_dir / "01-python.md").write_text("python", encoding="utf-8")
    (rules_dir / "note.txt").write_text("ignored", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path.name for memory in memories] == ["01-python.md", "02-frontend.md"]
    assert [memory.memory_type for memory in memories] == ["rule", "rule"]
    assert [memory.content for memory in memories] == ["python", "frontend"]


def test_load_instruction_memories_truncates_large_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    memory_path = project_root / "ZZCODE.md"
    memory_path.write_text("abcdef", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home, max_file_chars=3)

    assert len(memories) == 1
    assert memories[0].content == "abc"
    assert memories[0].char_count == 3
    assert memories[0].truncated is True


def test_load_instruction_memories_expands_relative_includes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    rules_dir = project_root / ".zzcode" / "rules"
    home.mkdir()
    rules_dir.mkdir(parents=True)
    main_memory = project_root / "ZZCODE.md"
    included_memory = rules_dir / "python.md"
    main_memory.write_text("main\n@./.zzcode/rules/python.md", encoding="utf-8")
    included_memory.write_text("included", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path for memory in memories] == [main_memory.resolve(), included_memory.resolve()]
    assert memories[1].parent == main_memory.resolve()
    assert memories[1].content == "included"


def test_load_instruction_memories_ignores_includes_in_code(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    main_memory = project_root / "ZZCODE.md"
    hidden_memory = project_root / "hidden.md"
    main_memory.write_text(
        "\n".join(
            [
                "```",
                "@./hidden.md",
                "```",
                "inline `@./hidden.md`",
            ]
        ),
        encoding="utf-8",
    )
    hidden_memory.write_text("hidden", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path for memory in memories] == [main_memory.resolve()]


def test_load_instruction_memories_prevents_include_cycles(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    first = project_root / "ZZCODE.md"
    second = project_root / "second.md"
    first.write_text("first\n@./second.md", encoding="utf-8")
    second.write_text("second\n@./ZZCODE.md", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path for memory in memories] == [first.resolve(), second.resolve()]


def test_load_instruction_memories_rejects_external_and_non_text_includes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    outside = tmp_path / "outside.md"
    image = project_root / "image.png"
    home.mkdir()
    project_root.mkdir()
    main_memory = project_root / "ZZCODE.md"
    main_memory.write_text("main\n@./../outside.md\n@./image.png", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    image.write_text("not text", encoding="utf-8")

    memories = load_instruction_memories(project_root, home=home)

    assert [memory.path for memory in memories] == [main_memory.resolve()]


def test_format_instruction_memories_uses_claude_style_sections(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    memory_path = project_root / "ZZCODE.md"
    memory_path.write_text("请使用简洁中文回答。", encoding="utf-8")
    memories = load_instruction_memories(project_root, home=home)

    text = format_instruction_memories(memories)

    assert "Codebase and user instructions are shown below." in text
    assert f"Contents of {memory_path.resolve()}" in text
    assert "project instructions checked into the codebase" in text
    assert "请使用简洁中文回答。" in text


def test_build_memory_context_merges_instruction_memory_and_recent_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    (project_root / "ZZCODE.md").write_text("项目规则", encoding="utf-8")

    context = build_memory_context(
        project_root,
        ["User: 张三是 Python 开发者", "Assistant: 已记录"],
        home=home,
    )

    assert context.instruction_count == 1
    assert context.session_items == 2
    assert "项目规则" in context.text
    assert "Recent session:" in context.text
    assert "User: 张三是 Python 开发者" in context.text


def test_build_memory_context_includes_compact_summary_and_session_notes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    notes_path = ensure_session_notes_file(project_root)
    notes_path.write_text("# Session Title\n记住当前正在实现 Compact。", encoding="utf-8")

    context = build_memory_context(
        project_root,
        ["User: 当前问题"],
        compact_summary="旧会话摘要",
        home=home,
    )

    assert "Session notes:" in context.text
    assert "记住当前正在实现 Compact。" in context.text
    assert "Compacted session summary:" in context.text
    assert "旧会话摘要" in context.text
    assert context.compact_summary_chars == len("旧会话摘要")
    assert context.session_notes_chars > 0


def test_build_memory_context_with_current_session_skips_global_session_notes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    notes_path = ensure_session_notes_file(project_root)
    notes_path.write_text("旧全局 session notes 不应进入新会话", encoding="utf-8")
    session_scope = create_session_scope(project_root, "session-a")
    session_scope.session_memory_path.write_text("当前会话状态", encoding="utf-8")

    context = build_memory_context(project_root, [], home=home, current_session=session_scope)

    assert "Current session memory:" in context.text
    assert "Session ID: session-a" in context.text
    assert str(session_scope.session_memory_path) in context.text
    assert "当前会话状态" in context.text
    assert "旧全局 session notes 不应进入新会话" not in context.text
    assert "Session notes:" not in context.text
    assert context.current_session_memory_chars > 0


def test_build_memory_context_includes_auto_memory_index(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()
    memory_dir = ensure_auto_memory(project_root)
    (memory_dir / "project" / "测试信息.md").write_text("第一条测试信息：苹果", encoding="utf-8")
    get_auto_memory_index_path(project_root).write_text(
        DEFAULT_AUTO_MEMORY_INDEX.replace(
            "## Project",
            "## Project\n- [测试信息](project/测试信息.md) - 第一条测试信息：苹果",
        ),
        encoding="utf-8",
    )

    context = build_memory_context(project_root, [], home=home)

    assert "Auto memory index:" in context.text
    assert "[测试信息](project/测试信息.md)" in context.text
    assert context.auto_memory_chars > 0


def test_short_term_session_memory_records_and_trims_turns() -> None:
    memory = ShortTermSessionMemory(limit=4)

    assert memory.record_turn("one", "answer one") == 0
    assert memory.record_turn("two", "answer two") == 0
    assert memory.record_turn("three", "answer three") == 2

    assert memory.as_list() == [
        "User: two",
        "Assistant: answer two",
        "User: three",
        "Assistant: answer three",
    ]


def test_short_term_session_memory_clear() -> None:
    memory = ShortTermSessionMemory()
    memory.record_turn("hello", "world")

    memory.clear()

    assert memory.as_list() == []


def test_short_term_session_memory_manual_compact_keeps_recent_items() -> None:
    memory = ShortTermSessionMemory(limit=20, compact_keep_items=2)
    memory.record_turn("one", "answer one")
    memory.record_turn("two", "answer two")
    memory.record_turn("three", "answer three")

    result = memory.compact()

    assert result.compacted is True
    assert result.removed_items == 4
    assert result.kept_items == 2
    assert "User: one" in memory.compact_summary()
    assert memory.as_list() == ["User: three", "Assistant: answer three"]


def test_short_term_session_memory_auto_compact_uses_char_threshold() -> None:
    memory = ShortTermSessionMemory(limit=20, compact_char_threshold=40, compact_keep_items=2)
    memory.record_turn("long user text", "long assistant text")
    memory.record_turn("next user text", "next assistant text")

    result = memory.compact_if_needed()

    assert result.compacted is True
    assert memory.as_list() == ["User: next user text", "Assistant: next assistant text"]
    assert "long user text" in memory.compact_summary()


def test_session_notes_path_uses_project_dot_zzcode_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"

    assert get_session_notes_path(project_root) == project_root / ".zzcode" / "session" / "notes.md"


def test_ensure_session_notes_file_creates_template_once(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    notes_path = ensure_session_notes_file(project_root)

    assert notes_path.read_text(encoding="utf-8") == DEFAULT_SESSION_NOTES_TEMPLATE

    notes_path.write_text("custom notes", encoding="utf-8")
    assert ensure_session_notes_file(project_root) == notes_path
    assert notes_path.read_text(encoding="utf-8") == "custom notes"


def test_read_session_notes_ignores_default_template(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    ensure_session_notes_file(project_root)

    assert read_session_notes(project_root) == ""


def test_read_session_notes_reads_custom_notes_and_truncates(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    notes_path = ensure_session_notes_file(project_root)
    notes_path.write_text("abcdef", encoding="utf-8")

    assert read_session_notes(project_root, max_chars=3) == "abc\n\n[session notes truncated]"


def test_format_compact_summary_and_session_notes_skip_empty_text() -> None:
    assert format_compact_summary("") == ""
    assert format_session_notes("") == ""
    assert "Compacted session summary:" in format_compact_summary("summary")
    assert "Session notes:" in format_session_notes("notes")


def test_auto_memory_ensure_creates_index_and_type_dirs(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    memory_dir = ensure_auto_memory(project_root)

    assert memory_dir == project_root / ".zzcode" / "memory"
    assert get_auto_memory_index_path(project_root).read_text(encoding="utf-8") == DEFAULT_AUTO_MEMORY_INDEX
    assert (memory_dir / "user").is_dir()
    assert (memory_dir / "project").is_dir()
    assert (memory_dir / "feedback").is_dir()
    assert (memory_dir / "reference").is_dir()
    assert read_auto_memory_index(project_root) == DEFAULT_AUTO_MEMORY_INDEX.strip()


def test_scan_auto_memory_files_reads_frontmatter_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    memory_dir = ensure_auto_memory(project_root)
    project_file = memory_dir / "project" / "api.md"
    user_file = memory_dir / "user" / "prefs.md"
    project_file.write_text(
        "---\nname: API\n"
        "description: Use service layer for API changes\n"
        "type: project\n---\n\nBody",
        encoding="utf-8",
    )
    user_file.write_text(
        "---\ndescription: Prefers concise Chinese answers\n"
        "type: user\n---\n\nBody",
        encoding="utf-8",
    )
    os.utime(project_file, (1000, 1000))
    os.utime(user_file, (2000, 2000))

    headers = scan_auto_memory_files(project_root)
    manifest = format_auto_memory_manifest(headers)

    assert [header.filename for header in headers] == ["user/prefs.md", "project/api.md"]
    assert headers[0].memory_type == "user"
    assert headers[0].description == "Prefers concise Chinese answers"
    assert "MEMORY.md" not in manifest
    assert "- [user] user/prefs.md" in manifest
    assert "Prefers concise Chinese answers" in manifest


def test_scan_auto_memory_files_caps_and_ignores_invalid_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    memory_dir = ensure_auto_memory(project_root)
    for index in range(205):
        memory_file = memory_dir / "project" / f"{index:03d}.md"
        memory_file.write_text(f"---\ntype: unknown\n---\n\n{index}", encoding="utf-8")
    (memory_dir / "project" / "notes.txt").write_text("skip", encoding="utf-8")

    headers = scan_auto_memory_files(project_root)

    assert len(headers) == 200
    assert all(header.filename.endswith(".md") for header in headers)
    assert all(header.memory_type is None for header in headers)


def test_create_session_scope_creates_isolated_session_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    first = create_session_scope(project_root, "first-session")
    second = create_session_scope(project_root, "second-session")

    assert get_sessions_dir(project_root) == project_root / ".zzcode" / "sessions"
    assert get_session_dir(project_root, "first-session") == first.session_dir
    assert first.session_dir != second.session_dir
    assert first.transcript_path.exists()
    assert second.transcript_path.exists()
    assert first.session_memory_path.read_text(encoding="utf-8") == DEFAULT_SESSION_MEMORY_TEMPLATE
    assert second.session_memory_path.read_text(encoding="utf-8") == DEFAULT_SESSION_MEMORY_TEMPLATE


def test_current_session_memory_reads_only_current_scope(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    old_scope = create_session_scope(project_root, "old-session")
    current_scope = create_session_scope(project_root, "current-session")
    old_scope.session_memory_path.write_text("旧会话记忆", encoding="utf-8")
    current_scope.session_memory_path.write_text("当前会话记忆", encoding="utf-8")

    assert read_current_session_memory(current_scope) == "当前会话记忆"
    assert "当前会话记忆" in format_current_session_memory(current_scope, read_current_session_memory(current_scope))
    context = build_memory_context(project_root, [], current_session=current_scope)

    assert "当前会话记忆" in context.text
    assert "旧会话记忆" not in context.text


def test_current_session_memory_default_template_is_empty_content(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    scope = create_session_scope(project_root, "empty-session")

    assert read_current_session_memory(scope) == ""
    context = build_memory_context(project_root, [], current_session=scope)

    assert "Current session memory:" in context.text
    assert "Session ID: empty-session" in context.text
    assert "(empty)" in context.text


def test_session_memory_empty_detection_uses_default_template() -> None:
    assert is_session_memory_empty(DEFAULT_SESSION_MEMORY_TEMPLATE) is True
    assert is_session_memory_empty(DEFAULT_SESSION_MEMORY_TEMPLATE + "\n") is True
    assert is_session_memory_empty(DEFAULT_SESSION_MEMORY_TEMPLATE + "\nextra") is False


def test_session_memory_section_analysis_and_reminders() -> None:
    content = (
        "# Current State\n"
        "_What is active._\n\n"
        f"{'x' * 9000}\n\n"
        "# Worklog\n"
        "_Steps._\n\n"
        "done"
    )

    sections = analyze_session_memory_sections(content)
    reminders = build_session_memory_size_reminders(content)

    assert sections["# Current State"] > 2000
    assert sections["# Worklog"] > 0
    assert "Current State" in reminders
    assert "limit: 2000" in reminders


def test_truncate_session_memory_for_compact_preserves_sections() -> None:
    content = (
        "# Current State\n"
        "_What is active._\n\n"
        + "\n".join(["x" * 100 for _ in range(100)])
        + "\n# Worklog\n"
        "_Steps._\n\n"
        "done"
    )

    result = truncate_session_memory_for_compact(content, max_section_tokens=100)

    assert result.was_truncated is True
    assert "# Current State" in result.content
    assert "# Worklog" in result.content
    assert "[section truncated for compact]" in result.content
    assert len(result.content) < len(content)


def test_transcript_recorder_appends_jsonl_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    scope = create_session_scope(project_root, "transcript-session")
    recorder = TranscriptRecorder(scope)

    turn_id = recorder.begin_turn()
    recorder.record_user("你好")
    recorder.record_tool_use("read_file", "README.md")
    recorder.record_tool_result("read_file", "内容", ok=True)
    recorder.record_assistant("完成")
    recorder.end_turn()

    events = [json.loads(line) for line in scope.transcript_path.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in events] == ["user", "tool_use", "tool_result", "assistant"]
    assert {event["sessionId"] for event in events} == {"transcript-session"}
    assert [event["sequence"] for event in events] == [0, 1, 2, 3]
    assert {event["turnId"] for event in events} == {turn_id}
    assert events[0]["parentEventId"] is None
    assert events[1]["parentEventId"] == events[0]["eventId"]
    assert events[2]["parentEventId"] == events[1]["eventId"]
    assert events[3]["parentEventId"] == events[2]["eventId"]
    assert events[0]["text"] == "你好"
    assert events[1]["toolName"] == "read_file"
    assert events[2]["ok"] is True
    assert events[3]["text"] == "完成"


def test_transcript_recorder_records_compact_boundary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    scope = create_session_scope(project_root, "compact-transcript-session")
    recorder = TranscriptRecorder(scope)

    recorder.begin_turn()
    recorder.record_user("one")
    recorder.record_assistant("two")
    recorder.end_turn()
    recorder.record_compact(trigger="manual", removed_items=2, kept_items=0, summary="old summary")

    events = [json.loads(line) for line in scope.transcript_path.read_text(encoding="utf-8").splitlines()]
    boundary = events[2]
    summary = events[3]

    assert boundary["type"] == "compact_boundary"
    assert boundary["parentEventId"] is None
    assert boundary["logicalParentEventId"] == events[1]["eventId"]
    assert boundary["trigger"] == "manual"
    assert boundary["removedItems"] == 2
    assert summary["type"] == "compact_summary"
    assert summary["parentEventId"] == boundary["eventId"]
    assert summary["compactBoundaryEventId"] == boundary["eventId"]
    assert summary["summary"] == "old summary"


def test_build_memory_context_injects_default_auto_memory_index(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    project_root.mkdir()

    context = build_memory_context(project_root, [], home=home)

    assert "Auto memory index:" in context.text
    assert "# ZzCode Auto Memory" in context.text
    assert context.auto_memory_chars > 0


def test_auto_memory_index_can_be_maintained_by_regular_file_tools(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    ensure_auto_memory(project_root)

    memory_output = write_file(
        project_root,
        ".zzcode/memory/project/测试信息.md|||---\ntype: project\ntitle: 测试信息\n---\n\n第一条测试信息：苹果\n",
    )
    index_output = append_file(
        project_root,
        ".zzcode/memory/MEMORY.md|||- [测试信息](project/测试信息.md) - 第一条测试信息：苹果\n",
    )

    assert "Wrote .zzcode/memory/project/测试信息.md" in memory_output
    assert "Appended .zzcode/memory/MEMORY.md" in index_output
    assert "第一条测试信息：苹果" in read_file(project_root, ".zzcode/memory/project/测试信息.md")
    index_text = get_auto_memory_index_path(project_root).read_text(encoding="utf-8")
    assert "- [测试信息](project/测试信息.md) - 第一条测试信息：苹果" in index_text
    assert "测试信息" in read_auto_memory_index(project_root)


def test_edit_and_append_file_update_existing_memory_without_overwrite(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    memory_dir = ensure_auto_memory(project_root)
    memory_path = memory_dir / "project" / "测试信息.md"
    memory_path.write_text("第一条测试信息：苹果\n", encoding="utf-8")

    append_result = append_file(project_root, ".zzcode/memory/project/测试信息.md|||第二条测试信息：香蕉\n")
    edit_result = edit_file(
        project_root,
        ".zzcode/memory/project/测试信息.md|||第二条测试信息：香蕉|||第二条测试信息：香蕉，来自后续对话",
    )

    assert "Appended .zzcode/memory/project/测试信息.md" in append_result
    assert "Edited .zzcode/memory/project/测试信息.md" in edit_result
    content = memory_path.read_text(encoding="utf-8")
    assert "第一条测试信息：苹果" in content
    assert "第二条测试信息：香蕉，来自后续对话" in content


def test_edit_file_rejects_ambiguous_replacement(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    path = project_root / "notes.md"
    path.write_text("same\nsame\n", encoding="utf-8")

    output = edit_file(project_root, "notes.md|||same|||changed")

    assert "出现 2 次" in output


def test_read_auto_memory_file_rejects_path_escape(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    try:
        read_auto_memory_file(project_root, "../outside.md")
    except ValueError as exc:
        assert "memory 路径越界" in str(exc)
    else:
        raise AssertionError("path escape should fail")


def test_build_tools_hides_dedicated_memory_tools(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    tools = build_tools(project_root)

    assert "memory_save" not in tools.tool_names_text()
    assert "memory_read" not in tools.tool_names_text()
    assert "edit_file" in tools.tool_names_text()
    assert "append_file" in tools.tool_names_text()


def test_react_prompt_uses_memory_mechanics_not_memory_save() -> None:
    assert "Memory mechanics:" in REACT_PROMPT_TEMPLATE
    assert ".zzcode/memory/MEMORY.md" in REACT_PROMPT_TEMPLATE
    assert "Current session memory" in REACT_PROMPT_TEMPLATE
    assert "不要依赖固定关键词判断" in REACT_PROMPT_TEMPLATE
    assert "memory_save" not in REACT_PROMPT_TEMPLATE


def test_memory_markdown_file_tools_are_auto_allowed(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("ZZCODE_PROJECT_ROOT", str(project_root))
    session_scope = create_session_scope(project_root, "current-session")
    old_scope = create_session_scope(project_root, "old-session")

    assert _is_auto_allowed_memory_tool("read_file", ".zzcode/memory/MEMORY.md") is True
    assert _is_auto_allowed_memory_tool("write_file", ".zzcode/memory/project/a.md|||content") is True
    assert _is_auto_allowed_memory_tool("edit_file", ".zzcode/memory/project/a.md|||old|||new") is True
    assert _is_auto_allowed_memory_tool("append_file", ".zzcode/memory/MEMORY.md|||entry") is True
    assert _is_auto_allowed_memory_tool("read_file", str(session_scope.session_memory_path), "current-session") is True
    assert _is_auto_allowed_memory_tool("append_file", f"{session_scope.session_memory_path}|||entry", "current-session") is True
    assert _is_auto_allowed_memory_tool("append_file", f"{session_scope.transcript_path}|||entry", "current-session") is True
    assert _is_auto_allowed_memory_tool("read_file", str(old_scope.session_memory_path), "current-session") is False
    assert _is_auto_allowed_memory_tool("write_file", "memory.txt|||content") is False
    assert _is_auto_allowed_memory_tool("write_file", ".zzcode/memory/project/a.txt|||content") is False
    assert _is_auto_allowed_memory_tool("run_shell", "echo hi") is False
