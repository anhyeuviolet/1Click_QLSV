"""Subprocess runner for ``scripts/jx.sh`` (D-12, D-13, D-17, S-5, OPS-02, H-2, H-5, M-3).

Responsibilities:

- ``run_job(action, service, config) -> job_id``: validate inputs against
  ``ALLOWED_SERVICES``, **atomically** acquire the module-level
  ``asyncio.Lock`` (``asyncio.wait_for(_lock.acquire(), timeout=0)``,
  H-2), spawn ``bash scripts/jx.sh ...`` via
  ``asyncio.create_subprocess_exec`` (argv-list, no ``shell=True``,
  OPS-02), and return the 32-hex job id immediately. A background task
  ``_run_and_track`` collects the exit code, writes the
  ``<job_id>.exit`` sidecar (H-5), updates state (mark_started /
  mark_stopped on zero exit), prunes history, and releases the lock.
- ``LockBusy``: raised by ``run_job`` when another job is already running.
- ``current_job()``: snapshot of the running job (or None).

Tests monkeypatch ``SCRIPT``, ``JOB_LOG_DIR``, ``history.JOBS_FILE`` and
``state.STATE_FILE`` to redirect to ``tmp_path``.

The asyncio.Lock is process-local: uvicorn MUST run ``--workers 1``
(Phase 4 systemd unit pins this).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qlsv import state
from qlsv.jobs import history
from qlsv.processes import ALLOWED_SERVICES

__all__ = [
    "SCRIPT",
    "JOB_LOG_DIR",
    "LockBusy",
    "run_job",
    "current_job",
]

# Repo root = parents[3] from src/qlsv/jobs/runner.py
# (runner.py -> jobs -> qlsv -> src -> <repo>).
SCRIPT: Path = Path(__file__).resolve().parents[3] / "scripts" / "jx.sh"
JOB_LOG_DIR: Path = Path("/var/log/qlsv/jobs")

_lock = asyncio.Lock()
_current_job: dict[str, Any] | None = None


class LockBusy(Exception):
    """Another job is already running."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_env(config: dict[str, Any]) -> dict[str, str]:
    """Inject GAMEPATH / SERVER_IP / SERVER_MAC over the parent env.

    No shell quoting needed — the subprocess is invoked via argv-list
    (``create_subprocess_exec``), bypassing shell parsing entirely.
    """
    cfg_game = config.get("game", {}) or {}
    env = {**os.environ}
    env["GAMEPATH"] = str(cfg_game.get("directory", "/home/jxser"))
    env["SERVER_IP"] = str(cfg_game.get("server_ip", ""))
    env["SERVER_MAC"] = str(cfg_game.get("server_mac", ""))
    return env


def _write_exit_sidecar(job_id: str, exit_code: int) -> None:
    """Atomically write ``exit=<n>\\n`` to ``<job_id>.exit`` (H-5).

    Sibling to ``<job_id>.log`` — keeps the log file pristine so binary
    output (or any string the game emits) cannot be misread as an
    end-of-stream sentinel by the SSE tail loop.
    """
    exit_path = JOB_LOG_DIR / f"{job_id}.exit"
    tmp = exit_path.with_suffix(".exit.tmp")
    payload = f"exit={exit_code}\n"
    if not sys.platform.startswith("win"):
        fd = os.open(
            str(tmp),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        tmp.write_text(payload, encoding="utf-8")
    os.replace(str(tmp), str(exit_path))


async def run_job(
    action: str,
    service: str | None,
    config: dict[str, Any],
) -> str:
    """Spawn ``scripts/jx.sh`` for ``action`` / ``service``; return the job id.

    Raises:
        ValueError — action or service does not pass whitelist (T-02-11).
        LockBusy   — another job is currently running (H-2).
    """
    if action not in {"start_all", "stop_all", "start", "stop"}:
        raise ValueError("action không hợp lệ")
    if action in {"start", "stop"}:
        if service is None or service not in ALLOWED_SERVICES:
            raise ValueError("Service không hợp lệ")
    else:
        if service is not None:
            raise ValueError("Service không hợp lệ")

    # H-2: atomic non-blocking acquire — no `if locked(): raise; await acquire()`
    # race window between the check and the acquire.
    try:
        await asyncio.wait_for(_lock.acquire(), timeout=0)
    except asyncio.TimeoutError:
        raise LockBusy()

    # From here on we OWN the lock; on any error path BEFORE _run_and_track
    # is scheduled we must release it.
    try:
        job_id = uuid.uuid4().hex

        # M-3: explicit chmod 0o750 after makedirs to defeat umask widening.
        try:
            JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
            if not sys.platform.startswith("win"):
                try:
                    os.chmod(str(JOB_LOG_DIR), 0o750)
                except PermissionError:
                    # Non-owner test mode; the log file open below uses inherited mode.
                    pass
        except OSError:
            # makedirs failed (e.g. /var/log not writable in some envs); surface
            # the error to the caller, but release the lock first.
            raise

        argv: list[str] = ["bash", str(SCRIPT)]
        if action == "start_all":
            argv.append("start")
        elif action == "stop_all":
            argv.append("stop")
        elif action == "start":
            argv += ["start", service]  # type: ignore[list-item]
        elif action == "stop":
            argv += ["stop", service]  # type: ignore[list-item]

        env = _build_env(config)
        log_path = JOB_LOG_DIR / f"{job_id}.log"

        global _current_job
        job_record = {
            "id": job_id,
            "action": action,
            "service": service,
            "started_at": _now_iso(),
            "ended_at": None,
            "exit_code": None,
        }
        history.append_job(dict(job_record))
        _current_job = dict(job_record)

        # Fire-and-forget tracker; lock released in _run_and_track.
        asyncio.create_task(
            _run_and_track(job_id, action, service, argv, env, log_path)
        )
        return job_id
    except Exception:
        # Ensure the lock is released if we failed before scheduling.
        if _lock.locked():
            _lock.release()
        raise


async def _run_and_track(
    job_id: str,
    action: str,
    service: str | None,
    argv: list[str],
    env: dict[str, str],
    log_path: Path,
) -> None:
    """Background coroutine: run subprocess, update state + history, write sidecar."""
    global _current_job
    exit_code = -1
    try:
        # CR-01: open with explicit 0o600 so default umask 0022 can't leave the
        # log world-readable (game stdout may contain IP/MAC/SQL output).
        log_fd = os.open(
            str(log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        with os.fdopen(log_fd, "ab") as logf:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=logf,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            exit_code = await proc.wait()

        # Only mark state on success — a failed start should NOT flip
        # expected_running=True (avoids spurious "crashed" badges on the
        # next poll).
        if exit_code == 0:
            try:
                if action == "start_all":
                    for svc in ALLOWED_SERVICES:
                        state.mark_started(svc)
                elif action == "stop_all":
                    for svc in ALLOWED_SERVICES:
                        state.mark_stopped(svc)
                elif action == "start" and service is not None:
                    state.mark_started(service)
                elif action == "stop" and service is not None:
                    state.mark_stopped(service)
            except OSError:
                # State write failed (e.g. /var/lib/qlsv not writable in test);
                # don't propagate — the job already ran.
                pass

        try:
            history.update_job_end(job_id, _now_iso(), exit_code)
        except OSError:
            pass

        try:
            _write_exit_sidecar(job_id, exit_code)
        except OSError:
            pass

        try:
            history.prune(keep=20)
        except OSError:
            pass
    finally:
        _current_job = None
        if _lock.locked():
            _lock.release()


def current_job() -> dict[str, Any] | None:
    """Return a shallow copy of the running job, or None."""
    if _current_job is None:
        return None
    return dict(_current_job)
