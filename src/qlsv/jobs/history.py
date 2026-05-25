"""Job history ring buffer (D-07 / D-08 / S-1 / H-6).

Append-only JSON list at ``/var/lib/qlsv/jobs.json`` (file 0600, parent dir
0700 — handled by ``qlsv._atomic.write_json``). Each entry:

    {
      "id":          "<32-hex uuid4>",
      "action":      "start_all" | "stop_all" | "start" | "stop",
      "service":     "<name>" | None,
      "started_at":  "<iso8601 UTC>",
      "ended_at":    "<iso8601 UTC>" | None,
      "exit_code":   int | None
    }

``prune(keep=MAX_HISTORY)`` trims to the most-recent ``keep`` entries by
``started_at`` and removes the sibling ``<id>.log`` and ``<id>.exit`` files
of the entries that fall off — bounded disk usage (T-02-16).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from qlsv._atomic import write_json

__all__ = [
    "JOBS_DIR",
    "JOBS_FILE",
    "JOB_LOG_DIR",
    "MAX_HISTORY",
    "list_jobs",
    "append_job",
    "update_job_end",
    "prune",
    "get_job",
]

JOBS_DIR: str = "/var/lib/qlsv"
JOBS_FILE: str = "/var/lib/qlsv/jobs.json"
JOB_LOG_DIR: Path = Path("/var/log/qlsv/jobs")
MAX_HISTORY: int = 20


def _resolve_path(path: str | None) -> str:
    """Read ``JOBS_FILE`` at call time so monkeypatch on the module attribute works."""
    return path if path is not None else JOBS_FILE


def _resolve_log_dir(log_dir: Path | None) -> Path:
    return log_dir if log_dir is not None else JOB_LOG_DIR


def list_jobs(path: str | None = None) -> list[dict[str, Any]]:
    """Return jobs list. Missing file / bad JSON / non-list → ``[]``."""
    p = _resolve_path(path)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    # Defensive: keep only dict entries.
    return [j for j in data if isinstance(j, dict)]


def append_job(job: dict[str, Any], path: str | None = None) -> None:
    """Append ``job`` to the on-disk list, atomically (mode 0600)."""
    p = _resolve_path(path)
    jobs = list_jobs(p)
    jobs.append(job)
    write_json(p, jobs, mode=0o600)


def update_job_end(
    job_id: str,
    ended_at: str,
    exit_code: int,
    path: str | None = None,
) -> None:
    """Patch ``ended_at`` + ``exit_code`` on the matching id; no-op if absent."""
    p = _resolve_path(path)
    jobs = list_jobs(p)
    for j in jobs:
        if j.get("id") == job_id:
            j["ended_at"] = ended_at
            j["exit_code"] = exit_code
            break
    write_json(p, jobs, mode=0o600)


def prune(
    keep: int = MAX_HISTORY,
    path: str | None = None,
    log_dir: Path | None = None,
) -> None:
    """Trim history to the most recent ``keep`` jobs; delete log + exit sidecars."""
    p = _resolve_path(path)
    ld = _resolve_log_dir(log_dir)
    jobs = list_jobs(p)
    if len(jobs) <= keep:
        return
    # Sort desc by started_at; missing/blank started_at sorts last.
    jobs_sorted = sorted(
        jobs,
        key=lambda j: j.get("started_at") or "",
        reverse=True,
    )
    kept = jobs_sorted[:keep]
    dropped = jobs_sorted[keep:]
    for old in dropped:
        old_id = old.get("id")
        if not old_id:
            continue
        for suffix in (".log", ".exit"):
            try:
                (ld / f"{old_id}{suffix}").unlink()
            except OSError:
                # File may already be gone; ignore.
                pass
    # Preserve original chronological order in the file (oldest-first append-style).
    kept.sort(key=lambda j: j.get("started_at") or "")
    write_json(p, kept, mode=0o600)


def get_job(job_id: str, path: str | None = None) -> dict[str, Any] | None:
    """Return the job matching ``job_id`` or None."""
    for j in list_jobs(path):
        if j.get("id") == job_id:
            return j
    return None
