"""Tests for qlsv.jobs.runner / history / log_stream (Plan 02-03).

Critical coverage:
  H-2: ``test_concurrent_run_job_only_one_succeeds`` — atomic non-blocking
       acquire prevents race window.
  H-5: ``test_run_job_writes_exit_sidecar`` — exit code lives in sibling
       ``.exit`` file, log file is pristine.
  T-02-11 / OPS-02: whitelist enforced before subprocess.
  T-02-12: ``validate_job_id`` rejects path traversal.

POSIX-only tests are guarded with ``skipif(sys.platform=='win32')``.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from qlsv import state
from qlsv.jobs import history, log_stream, runner

POSIX_ONLY = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="needs bash + 0o600 enforcement (POSIX only)",
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point runner / history / state at tmp_path; force-release the lock."""
    log_dir = tmp_path / "jobs_log"
    log_dir.mkdir()
    jobs_file = tmp_path / "jobs.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(runner, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOBS_FILE", str(jobs_file))
    monkeypatch.setattr(log_stream, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(state, "STATE_FILE", str(state_file))

    # Ensure the global asyncio.Lock is in a fresh state. Replacing the
    # whole object would shadow it; we just drain any held state.
    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None

    yield {
        "log_dir": log_dir,
        "jobs_file": jobs_file,
        "state_file": state_file,
    }

    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None


@pytest.fixture
def mock_script_exit_zero(tmp_path, monkeypatch):
    """Monkeypatch SCRIPT to a tiny shell that exits 0 quickly."""
    s = tmp_path / "mock_true.sh"
    s.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    s.chmod(0o755)
    monkeypatch.setattr(runner, "SCRIPT", s)
    return s


@pytest.fixture
def mock_script_exit_seven(tmp_path, monkeypatch):
    s = tmp_path / "mock_seven.sh"
    s.write_text("#!/bin/bash\necho hello\nexit 7\n", encoding="utf-8")
    s.chmod(0o755)
    monkeypatch.setattr(runner, "SCRIPT", s)
    return s


@pytest.fixture
def mock_script_slow(tmp_path, monkeypatch):
    s = tmp_path / "mock_slow.sh"
    s.write_text("#!/bin/bash\nsleep 0.5\nexit 0\n", encoding="utf-8")
    s.chmod(0o755)
    monkeypatch.setattr(runner, "SCRIPT", s)
    return s


# --------------------------------------------------------------------------- #
# Input validation (synchronous — coroutines raise before any await)           #
# --------------------------------------------------------------------------- #


def test_run_job_rejects_unknown_action(isolated_paths):
    async def _do():
        with pytest.raises(ValueError):
            await runner.run_job("delete", None, {})

    asyncio.run(_do())


def test_run_job_rejects_unknown_service(isolated_paths):
    async def _do():
        with pytest.raises(ValueError):
            await runner.run_job("start", "bishop; rm -rf /", {})

    asyncio.run(_do())


def test_run_job_rejects_service_for_start_all(isolated_paths):
    async def _do():
        with pytest.raises(ValueError):
            await runner.run_job("start_all", "bishop", {})

    asyncio.run(_do())


def test_run_job_rejects_none_service_for_start(isolated_paths):
    async def _do():
        with pytest.raises(ValueError):
            await runner.run_job("start", None, {})

    asyncio.run(_do())


def test_run_job_acquires_free_lock_without_raising_lockbusy(isolated_paths, tmp_path):
    """Regression for the asyncio.wait_for(coro, timeout=0) bug.

    On CPython 3.11+, ``asyncio.wait_for(lock.acquire(), timeout=0)`` raises
    TimeoutError even when the lock is FREE — the timeout callback fires
    before the acquire-task runs. The original Phase 2 implementation used
    that pattern as a non-blocking try-acquire, which made every Start/Stop
    action return 409 lock-busy. This test confirms the corrected pattern
    (``if locked(): raise; await acquire()``) actually acquires when free.
    Runs on every platform (no subprocess) — Windows CI would have caught
    the original bug had this test existed.
    """
    # Point SCRIPT at a non-executable path; we don't care if jx.sh runs —
    # we only assert that run_job() returns a job_id (lock acquired) rather
    # than raising LockBusy. The background _run_and_track will fail to
    # exec the script, but the lock acquire happens BEFORE that.
    mock = tmp_path / "noop.sh"
    mock.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    async def _do():
        assert not runner._lock.locked(), "precondition: lock must be free"
        job_id = await runner.run_job("start_all", None, {"game": {}})
        assert isinstance(job_id, str) and len(job_id) == 32
        # Drain the background task; whether the subprocess works is irrelevant.
        for _ in range(40):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)

    import qlsv.jobs.runner as r
    original_script = r.SCRIPT
    r.SCRIPT = mock
    try:
        asyncio.run(_do())
    finally:
        r.SCRIPT = original_script


# --------------------------------------------------------------------------- #
# Subprocess + state + exit sidecar (POSIX only — needs bash)                  #
# --------------------------------------------------------------------------- #


@POSIX_ONLY
def test_run_job_returns_job_id_and_appends_history(
    isolated_paths, mock_script_exit_zero
):
    async def _do():
        job_id = await runner.run_job("start_all", None, {"game": {}})
        assert isinstance(job_id, str)
        assert len(job_id) == 32
        assert all(c in "0123456789abcdef" for c in job_id)
        # History recorded immediately (before subprocess finishes).
        jobs = history.list_jobs(path=str(isolated_paths["jobs_file"]))
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_id
        assert jobs[0]["action"] == "start_all"
        # Let the background task finish.
        for _ in range(40):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)
        return job_id

    job_id = asyncio.run(_do())

    # After completion, ended_at + exit_code populated and lock released.
    jobs = history.list_jobs(path=str(isolated_paths["jobs_file"]))
    assert len(jobs) == 1
    assert jobs[0]["exit_code"] == 0
    assert jobs[0]["ended_at"] is not None
    assert not runner._lock.locked()


@POSIX_ONLY
def test_run_job_writes_exit_sidecar(isolated_paths, mock_script_exit_seven):
    """H-5: exit code lives in <id>.exit, NOT inline in <id>.log."""
    async def _do():
        job_id = await runner.run_job("start_all", None, {"game": {}})
        for _ in range(80):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)
        return job_id

    job_id = asyncio.run(_do())
    log_dir: Path = isolated_paths["log_dir"]

    exit_path = log_dir / f"{job_id}.exit"
    assert exit_path.exists(), "exit sidecar missing"
    assert exit_path.read_text(encoding="utf-8") == "exit=7\n"

    log_path = log_dir / f"{job_id}.log"
    log_bytes = log_path.read_bytes()
    assert b"hello" in log_bytes
    assert b"[__END__" not in log_bytes, "inline sentinel must NOT appear (H-5)"

    # CR-01: log file MUST be 0o600 regardless of umask (default 0022 would
    # otherwise produce 0644, world-readable — game stdout may leak IP/MAC/SQL).
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600, f"log file mode is {mode:o}, expected 600 (CR-01)"


@POSIX_ONLY
def test_run_job_marks_started_on_zero_exit(isolated_paths, mock_script_exit_zero):
    async def _do():
        await runner.run_job("start", "bishop", {"game": {}})
        for _ in range(60):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)

    asyncio.run(_do())
    s = state.load_state(path=str(isolated_paths["state_file"]))
    assert s.get("bishop", {}).get("expected_running") is True


@POSIX_ONLY
def test_run_job_does_not_mark_started_on_nonzero_exit(
    isolated_paths, mock_script_exit_seven
):
    async def _do():
        await runner.run_job("start", "bishop", {"game": {}})
        for _ in range(80):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)

    asyncio.run(_do())
    s = state.load_state(path=str(isolated_paths["state_file"]))
    # Either no entry or expected_running != True.
    assert s.get("bishop", {}).get("expected_running") is not True


@POSIX_ONLY
def test_concurrent_run_job_only_one_succeeds(isolated_paths, mock_script_slow):
    """H-2 critical: asyncio.gather(2x run_job) → exactly 1 success, 1 LockBusy."""
    async def _do():
        results = await asyncio.gather(
            runner.run_job("start_all", None, {"game": {}}),
            runner.run_job("start_all", None, {"game": {}}),
            return_exceptions=True,
        )
        # Drain the running job before the fixture cleanup tries to release.
        for _ in range(80):
            if not runner._lock.locked():
                break
            await asyncio.sleep(0.05)
        return results

    results = asyncio.run(_do())

    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, runner.LockBusy)]
    assert len(successes) == 1, f"expected exactly 1 success, got {results}"
    assert len(failures) == 1, f"expected exactly 1 LockBusy, got {results}"


# --------------------------------------------------------------------------- #
# History / prune (cross-platform — no subprocess)                             #
# --------------------------------------------------------------------------- #


def test_history_prune_keeps_20_and_deletes_log_and_exit(isolated_paths):
    log_dir: Path = isolated_paths["log_dir"]
    jobs_file = isolated_paths["jobs_file"]

    # Seed 25 jobs (oldest first).
    for i in range(25):
        jid = f"{i:032x}"
        history.append_job(
            {
                "id": jid,
                "action": "start_all",
                "service": None,
                "started_at": f"2026-05-25T00:00:{i:02d}+00:00",
                "ended_at": f"2026-05-25T00:00:{i:02d}+00:00",
                "exit_code": 0,
            },
            path=str(jobs_file),
        )
        (log_dir / f"{jid}.log").write_bytes(b"x")
        (log_dir / f"{jid}.exit").write_text("exit=0\n", encoding="utf-8")

    assert len(history.list_jobs(path=str(jobs_file))) == 25
    history.prune(keep=20, path=str(jobs_file), log_dir=log_dir)
    kept = history.list_jobs(path=str(jobs_file))
    assert len(kept) == 20

    # The 5 oldest (i=0..4) should be gone; ids 5..24 retained.
    kept_ids = {j["id"] for j in kept}
    for i in range(5):
        jid = f"{i:032x}"
        assert jid not in kept_ids
        assert not (log_dir / f"{jid}.log").exists(), f"{jid}.log not pruned"
        assert not (log_dir / f"{jid}.exit").exists(), f"{jid}.exit not pruned"
    for i in range(5, 25):
        jid = f"{i:032x}"
        assert jid in kept_ids
        assert (log_dir / f"{jid}.log").exists()
        assert (log_dir / f"{jid}.exit").exists()


def test_history_prune_noop_when_under_threshold(isolated_paths):
    jobs_file = isolated_paths["jobs_file"]
    for i in range(5):
        history.append_job(
            {"id": f"{i:032x}", "action": "start_all", "service": None,
             "started_at": f"2026-05-25T00:00:{i:02d}+00:00",
             "ended_at": None, "exit_code": None},
            path=str(jobs_file),
        )
    history.prune(keep=20, path=str(jobs_file), log_dir=isolated_paths["log_dir"])
    assert len(history.list_jobs(path=str(jobs_file))) == 5


def test_history_list_jobs_missing_returns_empty(tmp_path):
    assert history.list_jobs(path=str(tmp_path / "nope.json")) == []


def test_history_list_jobs_bad_json_returns_empty(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("not-json", encoding="utf-8")
    assert history.list_jobs(path=str(p)) == []


def test_history_list_jobs_non_list_returns_empty(tmp_path):
    p = tmp_path / "obj.json"
    p.write_text('{"not": "a list"}', encoding="utf-8")
    assert history.list_jobs(path=str(p)) == []


def test_history_get_job_returns_match(isolated_paths):
    jobs_file = isolated_paths["jobs_file"]
    history.append_job(
        {"id": "a" * 32, "action": "stop_all", "service": None,
         "started_at": "x", "ended_at": None, "exit_code": None},
        path=str(jobs_file),
    )
    found = history.get_job("a" * 32, path=str(jobs_file))
    assert found is not None
    assert found["action"] == "stop_all"
    assert history.get_job("b" * 32, path=str(jobs_file)) is None


# --------------------------------------------------------------------------- #
# log_stream.validate_job_id                                                   #
# --------------------------------------------------------------------------- #


def test_validate_job_id_accepts_32_lower_hex():
    assert log_stream.validate_job_id("a" * 32) is True
    assert log_stream.validate_job_id("0123456789abcdef" * 2) is True


def test_validate_job_id_rejects_uppercase():
    assert log_stream.validate_job_id("A" * 32) is False


def test_validate_job_id_rejects_wrong_length():
    assert log_stream.validate_job_id("a" * 31) is False
    assert log_stream.validate_job_id("a" * 33) is False
    assert log_stream.validate_job_id("") is False


def test_validate_job_id_rejects_path_traversal():
    assert log_stream.validate_job_id("../etc/passwd") is False
    assert log_stream.validate_job_id("../../../var/log") is False
    assert log_stream.validate_job_id("a" * 31 + "/") is False


def test_validate_job_id_rejects_non_hex_chars():
    assert log_stream.validate_job_id("g" * 32) is False
    assert log_stream.validate_job_id("a" * 31 + "z") is False


def test_validate_job_id_rejects_non_str():
    assert log_stream.validate_job_id(None) is False  # type: ignore[arg-type]
    assert log_stream.validate_job_id(123) is False  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# tail_file basic frames                                                       #
# --------------------------------------------------------------------------- #


def test_tail_file_rejects_bad_id():
    async def _do():
        gen = log_stream.tail_file("../etc/passwd")
        with pytest.raises(ValueError):
            await gen.__anext__()

    asyncio.run(_do())


def test_tail_file_emits_end_event_with_sidecar(isolated_paths):
    """H-5 check: sidecar presence triggers `event: end` frame."""
    log_dir: Path = isolated_paths["log_dir"]
    jid = "c" * 32
    (log_dir / f"{jid}.log").write_bytes(b"line1\nline2\n")
    (log_dir / f"{jid}.exit").write_text("exit=0\n", encoding="utf-8")

    async def _collect():
        chunks: list[bytes] = []
        async for chunk in log_stream.tail_file(jid, log_dir=log_dir):
            chunks.append(chunk)
            if b"event: end" in chunk:
                break
        return chunks

    chunks = asyncio.run(_collect())
    body = b"".join(chunks)
    assert b"data: line1" in body
    assert b"data: line2" in body
    assert b"event: end" in body
    assert b'"exit_code": 0' in body
