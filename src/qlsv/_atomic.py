"""Atomic JSON write helper dùng chung cho config / state / job history (Phase 2 H-6).

Trích xuất logic atomic-write từ ``config.save_config`` (Phase 1 WR-01) để
``config.py``, ``state.py`` và sau này ``history.py`` cùng dùng — không
duplicate code, không phân kỳ mode bits.

Hành vi:
  - Trên POSIX: tạo tmp file qua ``os.open`` với mode 0600 ngay từ đầu
    (T-01-01 / S-1) rồi ``os.replace`` về đích — không bao giờ tồn tại
    file đích world-readable, dù chỉ trong một khoảnh khắc.
  - Trên Windows (môi trường dev): fallback sang ``open(..., 'w')`` và
    bỏ qua chmod (mode bits không có ý nghĩa).
  - ``ensure_ascii=False`` + ``indent=2`` + trailing newline — đồng nhất
    với Phase 1.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

__all__ = ["write_json"]


def write_json(path: str | os.PathLike, data: Any, mode: int = 0o600) -> None:
    """Atomically write ``data`` as JSON to ``path``; chmod ``mode`` on POSIX.

    Writes to ``str(path) + ".tmp"`` first then ``os.replace`` so a crash
    never leaves a half-written file. Parent directory is created on demand.
    """
    target = str(path)
    tmp = target + ".tmp"
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    if not sys.platform.startswith("win"):
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp, flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # Belt + braces in case the process umask widened the mode bits.
        os.chmod(tmp, mode)
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    os.replace(tmp, target)
