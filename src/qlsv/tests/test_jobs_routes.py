"""Tests for GET /api/jobs/log + /api/jobs/live-tail (Plan 02-03 DASH-04, H-3/H-4).

Covers job_id validation (T-02-12), static + stream modes, the H-3 live
re-attach fragment, and the H-5 sidecar-driven end-of-stream frame.
"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qlsv.app import create_app
from qlsv.jobs import history, log_stream, runner

ADMIN_USER = "ngdat"
ADMIN_PW = "hunter2"


def _config() -> dict:
    return {
        "game": {"directory": "/home/jxser", "server_ip": "", "server_mac": ""},
        "web": {
            "bind_addr": "0.0.0.0",
            "port": 0,
            "idle_timeout_seconds": 2592000,
            "cookie_secure": False,
        },
        "dashboard": {"poll_interval_seconds": 5},
        "admin": {"username": ADMIN_USER, "password": ADMIN_PW},
        "session": {"secret_key": secrets.token_urlsafe(48)},
        "db": {
            "mysql": {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "p"},
            "mssql": {"host": "127.0.0.1", "port": 1433, "user": "SA", "password": "p"},
        },
    }


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    log_dir = tmp_path / "jobs_log"
    log_dir.mkdir()
    monkeypatch.setattr(runner, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(log_stream, "JOB_LOG_DIR", log_dir)
    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None
    yield {"log_dir": log_dir, "jobs_file": tmp_path / "jobs.json"}
    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None


@pytest.fixture
def client(isolated_paths) -> TestClient:
    return TestClient(create_app(_config()), follow_redirects=False)


def _login(client: TestClient) -> TestClient:
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302
    return client


# --------------------------------------------------------------------------- #
# Auth                                                                          #
# --------------------------------------------------------------------------- #


def test_log_unauth_redirects(client):
    r = client.get("/api/jobs/log?job_id=" + "a" * 32)
    assert r.status_code == 302


def test_live_tail_unauth_redirects(client):
    r = client.get("/api/jobs/live-tail")
    assert r.status_code == 302


# --------------------------------------------------------------------------- #
# job_id validation (T-02-12)                                                   #
# --------------------------------------------------------------------------- #


def test_log_rejects_invalid_job_id(client):
    _login(client)
    r = client.get("/api/jobs/log?job_id=not-a-uuid")
    assert r.status_code == 400


def test_log_rejects_path_traversal(client):
    _login(client)
    r = client.get("/api/jobs/log?job_id=../../etc/passwd")
    assert r.status_code == 400


def test_log_rejects_uppercase_hex(client):
    _login(client)
    r = client.get("/api/jobs/log?job_id=" + "A" * 32)
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Static mode                                                                   #
# --------------------------------------------------------------------------- #


def test_log_returns_404_for_missing_id(client, isolated_paths):
    _login(client)
    jid = "a" * 32
    r = client.get(f"/api/jobs/log?job_id={jid}")
    assert r.status_code == 404
    assert "đã bị xoá" in r.text or "xoá" in r.text  # pruned message


def test_log_returns_content_for_existing_id(client, isolated_paths):
    _login(client)
    jid = "b" * 32
    log_dir: Path = isolated_paths["log_dir"]
    (log_dir / f"{jid}.log").write_text("hello world\n", encoding="utf-8")
    # Append the job to history so the template gets metadata.
    history.append_job(
        {
            "id": jid,
            "action": "start_all",
            "service": None,
            "started_at": "2026-05-25T00:00:00+00:00",
            "ended_at": "2026-05-25T00:00:01+00:00",
            "exit_code": 0,
        }
    )
    r = client.get(f"/api/jobs/log?job_id={jid}")
    assert r.status_code == 200
    assert "hello world" in r.text
    assert 'id="tail-pane"' in r.text
    # static mode → no sse-connect attribute
    assert "sse-connect" not in r.text


def test_log_mode_stream_returns_sse_content_type(client, isolated_paths):
    _login(client)
    jid = "c" * 32
    log_dir: Path = isolated_paths["log_dir"]
    (log_dir / f"{jid}.log").write_text("frame1\n", encoding="utf-8")
    (log_dir / f"{jid}.exit").write_text("exit=0\n", encoding="utf-8")

    with client.stream(
        "GET", f"/api/jobs/log?job_id={jid}&mode=stream"
    ) as r:
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "text/event-stream" in ctype
        # Consume just enough to verify the first data frame.
        chunks: list[bytes] = []
        for chunk in r.iter_bytes():
            chunks.append(chunk)
            body = b"".join(chunks)
            if b"event: end" in body:
                break
        body = b"".join(chunks)
        assert b"data: frame1" in body
        assert b"event: end" in body


# --------------------------------------------------------------------------- #
# H-3: empty job_id + live-tail re-attach                                       #
# --------------------------------------------------------------------------- #


def test_log_empty_job_id_returns_empty_tail_pane(client):
    """H-3: ?job_id= with no current job → empty-state fragment."""
    _login(client)
    r = client.get("/api/jobs/log?job_id=")
    assert r.status_code == 200
    assert 'id="tail-pane"' in r.text
    assert "Chưa có lệnh nào được thực thi" in r.text
    assert "sse-connect" not in r.text


def test_log_empty_job_id_attaches_sse_when_current_job(client, monkeypatch, isolated_paths):
    """H-3: ?job_id= with a current running job → fragment carries sse-connect."""
    _login(client)
    jid = "d" * 32
    monkeypatch.setattr(
        runner,
        "current_job",
        lambda: {
            "id": jid,
            "action": "start_all",
            "service": None,
            "started_at": "2026-05-25T00:00:00+00:00",
            "ended_at": None,
            "exit_code": None,
        },
    )
    r = client.get("/api/jobs/log?job_id=")
    assert r.status_code == 200
    assert 'id="tail-pane"' in r.text
    assert "sse-connect" in r.text
    assert jid in r.text


def test_live_tail_returns_section_with_sse(client, monkeypatch):
    """H-3: GET /api/jobs/live-tail re-builds the section + sse-connect."""
    _login(client)
    jid = "e" * 32
    monkeypatch.setattr(
        runner,
        "current_job",
        lambda: {
            "id": jid,
            "action": "stop_all",
            "service": None,
            "started_at": "2026-05-25T00:00:00+00:00",
            "ended_at": None,
            "exit_code": None,
        },
    )
    r = client.get("/api/jobs/live-tail")
    assert r.status_code == 200
    body = r.text
    assert 'id="tail-pane"' in body
    assert "sse-connect" in body
    # The wired URL must match the H-4 query-string contract.
    assert f"/api/jobs/log?job_id={jid}" in body
    assert "mode=stream" in body


def test_live_tail_no_current_job_renders_empty(client):
    _login(client)
    r = client.get("/api/jobs/live-tail")
    assert r.status_code == 200
    assert 'id="tail-pane"' in r.text
    assert "sse-connect" not in r.text


# --------------------------------------------------------------------------- #
# H-5: log file does NOT contain the inline sentinel                            #
# --------------------------------------------------------------------------- #


def test_stream_emits_sse_event_for_existing_log_and_exit_sidecar(
    client, isolated_paths
):
    """H-5: a job with stdout + an .exit sidecar terminates the SSE stream."""
    _login(client)
    jid = "f" * 32
    log_dir: Path = isolated_paths["log_dir"]
    (log_dir / f"{jid}.log").write_text("line1\nline2\n", encoding="utf-8")
    (log_dir / f"{jid}.exit").write_text("exit=0\n", encoding="utf-8")

    with client.stream("GET", f"/api/jobs/log?job_id={jid}&mode=stream") as r:
        chunks: list[bytes] = []
        for chunk in r.iter_bytes():
            chunks.append(chunk)
            if b"event: end" in b"".join(chunks):
                break
        body = b"".join(chunks)

    assert b"data: line1" in body
    assert b"data: line2" in body
    assert b"event: end" in body
    assert b'"exit_code": 0' in body

    # Log file is pristine — no inline sentinel.
    log_bytes = (log_dir / f"{jid}.log").read_bytes()
    assert b"[__END__" not in log_bytes
