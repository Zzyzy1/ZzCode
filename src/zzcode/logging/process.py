"""进程输出辅助。"""

from __future__ import annotations

import sys


def write_to_stderr(data: str) -> None:
    """安全写入 stderr。"""

    try:
        sys.stderr.write(data)
        sys.stderr.flush()
    except OSError:
        return
