from pathlib import Path

from zzcode.memory import (
    DEFAULT_SESSION_NOTES_TEMPLATE,
    ShortTermSessionMemory,
    build_memory_context,
    ensure_session_notes_file,
    format_compact_summary,
    format_instruction_memories,
    format_session_notes,
    get_instruction_memory_files,
    get_session_notes_path,
    load_instruction_memories,
    read_session_notes,
)


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

    assert "Session memory notes:" in context.text
    assert "记住当前正在实现 Compact。" in context.text
    assert "Compacted session summary:" in context.text
    assert "旧会话摘要" in context.text
    assert context.compact_summary_chars == len("旧会话摘要")
    assert context.session_notes_chars > 0


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
    assert "Session memory notes:" in format_session_notes("notes")
