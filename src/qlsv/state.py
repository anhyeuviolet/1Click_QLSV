"""State file cho expected_running + last_started_at / last_stopped_at (D-10, S-1, M-3).

Persisted JSON tại ``/var/lib/qlsv/state.json``; directory mode 0700, file mode
0600 (M-3 — explicit chmod sau makedirs để umask không widen). Atomic write
qua ``qlsv._atomic.write_json`` (H-6 — KHÔNG duplicate logic của config.py).

Schema (Plan 03 job runner + Phase 4 monitor cùng đọc/ghi):
  {
    "bishop": {
      "expected_running": True,
      "last_started_at": "2026-05-25T12:34:56+00:00",
      "last_stopped_at": "2026-05-25T11:00:00+00:00" | None
    },
    ...
  }

Service không có entry trong state == "chưa bao giờ start" → ``expected_running``
defaults to False (xem ``get_expected_running``).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from qlsv._atomic import write_json

__all__ = [
    "STATE_DIR",
    "STATE_FILE",
    "load_state",
    "save_state",
    "mark_started",
    "mark_stopped",
    "get_expected_running",
]

STATE_DIR: str = "/var/lib/qlsv"
STATE_FILE: str = "/var/lib/qlsv/state.json"


def _ensure_dir_secure(path: str) -> None:
    """Best-effort: tạo parent dir mode 0700 và chmod lại để chặn umask widen.

    Bọc chmod trong ``try`` cho test mode trên Windows / non-owner.
    """
    parent = os.path.dirname(path)
    if not parent:
        return
    os.makedirs(parent, mode=0o700, exist_ok=True)
    if not sys.platform.startswith("win"):
        try:
            os.chmod(parent, 0o700)
        except PermissionError:
            # Owner mismatch (test mode) — leave it alone; the file mode
            # via _atomic.write_json still protects contents.
            pass


def load_state(path: str = STATE_FILE) -> dict[str, Any]:
    """Read ``path`` and return parsed dict. Missing file / bad JSON → ``{}``.

    State file is optional (first boot, fresh install) — callers must tolerate
    an empty dict without raising.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_state(state: dict[str, Any], path: str = STATE_FILE) -> None:
    """Persist ``state`` atomically; parent dir 0700, file 0600 (M-3, S-1)."""
    _ensure_dir_secure(path)
    write_json(path, state, mode=0o600)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_started(service: str, path: str = STATE_FILE) -> None:
    """Set ``expected_running=True`` and refresh ``last_started_at`` for ``service``.

    Preserves any prior ``last_stopped_at`` so the history pane (Plan 03) can
    still show the last stop time after a re-start.
    """
    state = load_state(path)
    prev = state.get(service, {}) if isinstance(state.get(service), dict) else {}
    state[service] = {
        "expected_running": True,
        "last_started_at": _now_iso(),
        "last_stopped_at": prev.get("last_stopped_at"),
    }
    save_state(state, path)


def mark_stopped(service: str, path: str = STATE_FILE) -> None:
    """Set ``expected_running=False`` and refresh ``last_stopped_at``.

    Preserves ``last_started_at`` so the dashboard can report uptime even
    after the user clicks Stop.
    """
    state = load_state(path)
    prev = state.get(service, {}) if isinstance(state.get(service), dict) else {}
    state[service] = {
        "expected_running": False,
        "last_started_at": prev.get("last_started_at"),
        "last_stopped_at": _now_iso(),
    }
    save_state(state, path)


def get_expected_running(state: dict[str, Any], service: str) -> bool:
    """Read-only helper. Returns ``False`` if service has no entry."""
    entry = state.get(service)
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("expected_running", False))
