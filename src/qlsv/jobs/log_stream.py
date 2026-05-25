"""SSE tail-file generator for ``/api/jobs/log?mode=stream`` (D-05, D-06, H-5).

``tail_file(job_id)`` yields ``b"data: ...\\n\\n"`` frames for each line
appended to ``/var/log/qlsv/jobs/<job_id>.log``; when the sibling
``<job_id>.exit`` file appears it yields one ``event: end`` frame and
returns. A 30-minute safety timeout caps the SSE lifetime so a stuck
client cannot pin a connection forever (T-02-17).

``validate_job_id`` rejects anything outside the lowercase-32-hex
``uuid4().hex`` alphabet — used at every route boundary to defend
``log_path = JOB_LOG_DIR / job_id`` against ``../`` traversal (T-02-12).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator

__all__ = [
    "JOB_LOG_DIR",
    "validate_job_id",
    "tail_file",
]

JOB_LOG_DIR: Path = Path("/var/log/qlsv/jobs")

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# SSE limits
_MAX_LIFETIME_SECONDS = 30 * 60  # 30 minutes (T-02-17)
_INITIAL_WAIT_SECONDS = 10
_INITIAL_WAIT_TICK = 0.2
_TAIL_TICK = 0.5


def validate_job_id(job_id: str) -> bool:
    """True iff ``job_id`` is a 32-lowercase-hex string (uuid4 hex shape)."""
    if not isinstance(job_id, str):
        return False
    return bool(_JOB_ID_RE.fullmatch(job_id))


def _read_exit(job_id: str, log_dir: Path = JOB_LOG_DIR) -> int | None:
    """Read ``<job_id>.exit`` if present; parse ``exit=<n>``. Bad parse → -1."""
    exit_path = log_dir / f"{job_id}.exit"
    if not exit_path.exists():
        return None
    try:
        content = exit_path.read_text(encoding="utf-8").strip()
    except OSError:
        return -1
    if content.startswith("exit="):
        try:
            return int(content[5:])
        except ValueError:
            return -1
    return -1


def _frame_data(line_bytes: bytes) -> bytes:
    """Split a line on internal newlines and emit one ``data:`` per sub-line.

    Per the SSE spec a ``data:`` field is one line; multi-line payloads
    must repeat the prefix. The final empty newline terminates the frame.
    """
    stripped = line_bytes.rstrip(b"\n")
    out = bytearray()
    if not stripped:
        out.extend(b"data: \n")
    else:
        for sub in stripped.split(b"\n"):
            out.extend(b"data: ")
            out.extend(sub)
            out.extend(b"\n")
    out.extend(b"\n")
    return bytes(out)


async def tail_file(
    job_id: str,
    log_dir: Path = JOB_LOG_DIR,
) -> AsyncIterator[bytes]:
    """Async generator yielding SSE frames for ``<job_id>.log``.

    Raises ``ValueError`` if ``job_id`` fails the alphabet check.
    """
    if not validate_job_id(job_id):
        raise ValueError("job_id không hợp lệ")

    log_path = log_dir / f"{job_id}.log"

    start_time = time.monotonic()

    # Wait-for-create loop (up to _INITIAL_WAIT_SECONDS).
    waited = 0.0
    while not log_path.exists():
        # Heartbeat so the client knows we're alive while the runner spins up.
        yield b"data: (chua co output)\n\n"
        await asyncio.sleep(_INITIAL_WAIT_TICK)
        waited += _INITIAL_WAIT_TICK
        if waited >= _INITIAL_WAIT_SECONDS:
            # Surface exit if already known; otherwise -1.
            exit_code = _read_exit(job_id, log_dir)
            if exit_code is None:
                exit_code = -1
            yield (
                b"event: end\ndata: "
                + json.dumps({"exit_code": exit_code}).encode("utf-8")
                + b"\n\n"
            )
            return

    # Main tail loop.
    with open(log_path, "rb") as f:
        while True:
            line = f.readline()
            if line:
                yield _frame_data(line)
                continue

            # EOF — check sidecar.
            exit_code = _read_exit(job_id, log_dir)
            if exit_code is not None:
                # Drain any final bytes that landed between readline() and the
                # sidecar check.
                tail = f.read()
                if tail:
                    for part in tail.split(b"\n"):
                        if part:
                            yield _frame_data(part + b"\n")
                yield (
                    b"event: end\ndata: "
                    + json.dumps({"exit_code": exit_code}).encode("utf-8")
                    + b"\n\n"
                )
                return

            # Safety timeout.
            if (time.monotonic() - start_time) > _MAX_LIFETIME_SECONDS:
                yield (
                    b"event: end\ndata: "
                    + json.dumps({"exit_code": -1, "reason": "timeout"}).encode("utf-8")
                    + b"\n\n"
                )
                return

            await asyncio.sleep(_TAIL_TICK)
