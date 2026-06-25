"""PowerShell read-only command classification."""

from __future__ import annotations

import shlex


def classify_read_only_powershell_command(command: str) -> tuple[bool, str]:
    """判断 PowerShell 命令是否属于第一版可自动允许的只读命令。"""

    normalized = command.strip()
    if not normalized:
        return False, "empty_command"

    lower = normalized.lower()
    if "set-date" in lower:
        return False, "powershell_date_dangerous_command"
    if _contains_command_separator(lower):
        return False, "powershell_complex_command"

    try:
        parts = shlex.split(normalized, posix=False)
    except ValueError:
        return False, "parse_failed"
    if not parts:
        return False, "empty_command"

    command_name = parts[0].strip().lower()
    if command_name == "get-date":
        return _classify_get_date(parts[1:])
    return False, "not_readonly_allowlisted"


def _classify_get_date(args: list[str]) -> tuple[bool, str]:
    safe_flags_with_values = {
        "-format",
        "-uformat",
        "-date",
        "-displayhint",
    }
    safe_flags_without_values = {
        "-asutc",
    }
    i = 0
    while i < len(args):
        raw = args[i].strip()
        arg = raw.strip('"').strip("'")
        lower = arg.lower()
        if not arg:
            i += 1
            continue
        if lower in safe_flags_with_values:
            if i + 1 >= len(args):
                return False, "powershell_missing_flag_value"
            i += 2
            continue
        if any(lower.startswith(flag + ":") for flag in safe_flags_with_values):
            i += 1
            continue
        if lower in safe_flags_without_values:
            i += 1
            continue
        if lower.startswith("-"):
            return False, "powershell_unknown_flag"
        return False, "powershell_unexpected_argument"
    return True, "readonly_powershell_get_date"


def _contains_command_separator(command: str) -> bool:
    separators = (";", "&&", "||", "|", "`", "$(", ">", "<")
    return any(separator in command for separator in separators)
