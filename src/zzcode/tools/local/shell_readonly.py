"""Shell read-only command classification."""

from __future__ import annotations

import re
import shlex


READ_ONLY_SIMPLE_COMMANDS = {
    "pwd",
    "whoami",
    "hostname",
}


GIT_READ_ONLY_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "remote",
}


def classify_read_only_shell_command(command: str) -> tuple[bool, str]:
    """判断命令是否属于第一版可自动允许的只读命令。"""

    normalized = command.strip()
    if not normalized:
        return False, "empty_command"

    if _is_powershell_invocation(normalized):
        return False, "use_powershell_tool"

    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False, "parse_failed"
    if not parts:
        return False, "empty_command"

    base = _strip_executable_suffix(parts[0]).lower()
    if base in READ_ONLY_SIMPLE_COMMANDS and len(parts) == 1:
        return True, f"readonly_{base}"
    if base == "date":
        return _classify_date(parts[1:])
    if base == "git":
        return _classify_git(parts[1:])
    return False, "not_readonly_allowlisted"


def _classify_date(args: list[str]) -> tuple[bool, str]:
    dangerous = {"-s", "--set", "-f", "--file"}
    flags_with_values = {"-d", "--date", "-r", "--reference", "--iso-8601", "--rfc-3339"}
    safe_flags_without_values = {
        "-u",
        "--utc",
        "--universal",
        "-I",
        "-R",
        "--rfc-email",
        "--debug",
        "--help",
        "--version",
        "/T",
        "/t",
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in dangerous or any(arg.startswith(flag + "=") for flag in dangerous):
            return False, "date_dangerous_flag"
        if arg.startswith("+"):
            i += 1
            continue
        if arg in flags_with_values:
            if i + 1 >= len(args):
                return False, "date_missing_flag_value"
            i += 2
            continue
        if any(arg.startswith(flag + "=") for flag in flags_with_values):
            i += 1
            continue
        if arg in safe_flags_without_values:
            i += 1
            continue
        if arg.startswith("-"):
            return False, "date_unknown_flag"
        # GNU date positional values like MMDDhhmm can set system time.
        return False, "date_positional_arg"
    return True, "readonly_date"


def _classify_git(args: list[str]) -> tuple[bool, str]:
    if not args:
        return False, "git_missing_subcommand"
    subcommand = args[0].lower()
    if subcommand in GIT_READ_ONLY_SUBCOMMANDS:
        return True, f"readonly_git_{subcommand}"
    return False, "git_not_readonly_allowlisted"


def _is_powershell_invocation(command: str) -> bool:
    lower = command.lower()
    return bool(re.match(r"^(powershell|powershell\.exe|pwsh|pwsh\.exe)\b", lower))


def _strip_executable_suffix(value: str) -> str:
    lower = value.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if lower.endswith(suffix):
            return value[: -len(suffix)]
    return value
