"""Tests for POST /api/services/start + /api/services/stop (Plan 02-03 DASH-03).

Includes the M-6 concurrency test using ``httpx.AsyncClient`` + ``asyncio.gather``
(not TestClient — TestClient serialises requests and cannot exercise the
asyncio.Lock contention path).
"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from qlsv import state
from qlsv.app import create_app
from qlsv.jobs import history, runner

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
    """Redirect runner / history / state into tmp_path; reset module-level state."""
    log_dir = tmp_path / "jobs_log"
    log_dir.mkdir()
    monkeypatch.setattr(runner, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "state.json"))
    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None
    yield
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


def test_post_start_all_unauth_redirects(client):
    r = client.post("/api/services/start")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


def test_post_stop_all_unauth_redirects(client):
    r = client.post("/api/services/stop")
    assert r.status_code == 302


# --------------------------------------------------------------------------- #
# Whitelist enforcement (T-02-11 / OPS-02)                                     #
# --------------------------------------------------------------------------- #


def test_post_start_rejects_unknown_service(client, monkeypatch):
    _login(client)
    r = client.post("/api/services/start?service=evil")
    assert r.status_code == 400
    assert "Service không hợp lệ" in r.text


def test_post_start_path_traversal_service_rejected(client):
    _login(client)
    r = client.post("/api/services/start?service=../../etc/passwd")
    assert r.status_code == 400


def test_post_stop_rejects_unknown_service(client):
    _login(client)
    r = client.post("/api/services/stop?service=bishop;%20rm%20-rf%20/")
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Successful dispatch — monkeypatch runner.run_job to capture args             #
# --------------------------------------------------------------------------- #


def _make_mock_run_job(capture: list[tuple[Any, ...]], result: str = "a" * 32):
    async def _mock(action, service, config):
        capture.append((action, service, config))
        return result
    return _mock


def test_post_start_all_authenticated_returns_job_id(client, monkeypatch):
    _login(client)
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner, "run_job", _make_mock_run_job(captured))
    r = client.post("/api/services/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == "a" * 32
    assert body["action"] == "start_all"
    assert body["service"] is None
    assert captured == [("start_all", None, captured[0][2])]


def test_post_stop_all_calls_run_job_stop_all(client, monkeypatch):
    _login(client)
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner, "run_job", _make_mock_run_job(captured, "b" * 32))
    r = client.post("/api/services/stop")
    assert r.status_code == 200
    assert r.json()["action"] == "stop_all"
    assert captured[0][0] == "stop_all"


def test_post_start_with_whitelisted_service_calls_run_job(client, monkeypatch):
    _login(client)
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner, "run_job", _make_mock_run_job(captured))
    r = client.post("/api/services/start?service=bishop")
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "start"
    assert body["service"] == "bishop"
    assert captured[0][0] == "start"
    assert captured[0][1] == "bishop"


def test_post_stop_with_whitelisted_service_calls_run_job(client, monkeypatch):
    _login(client)
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner, "run_job", _make_mock_run_job(captured, "c" * 32))
    r = client.post("/api/services/stop?service=goddess")
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "stop"
    assert body["service"] == "goddess"


# --------------------------------------------------------------------------- #
# LockBusy → 409 + HX-Trigger header (DASH-05)                                  #
# --------------------------------------------------------------------------- #


def test_post_start_returns_409_when_lock_busy(client, monkeypatch):
    _login(client)

    async def _busy(action, service, config):
        raise runner.LockBusy()

    monkeypatch.setattr(runner, "run_job", _busy)
    r = client.post("/api/services/start")
    assert r.status_code == 409
    body = r.json()
    assert "Đang có lệnh khác chạy" in body["error"]
    assert r.headers.get("hx-trigger") == "lock-busy"


# --------------------------------------------------------------------------- #
# M-6: real concurrency via httpx.AsyncClient + asyncio.gather                  #
# --------------------------------------------------------------------------- #


def test_post_start_concurrent_returns_409_via_asyncclient(
    isolated_paths, tmp_path, monkeypatch
):
    """Two concurrent POSTs hit the asyncio.Lock — exactly one wins.

    Uses a real-but-slow mock_script so the lock is held across the second
    request. POSIX only (needs bash).
    """
    import sys
    if sys.platform.startswith("win"):
        pytest.skip("needs bash subprocess for the slow mock script")

    s = tmp_path / "slow.sh"
    s.write_text("#!/bin/bash\nsleep 0.5\nexit 0\n", encoding="utf-8")
    s.chmod(0o755)
    monkeypatch.setattr(runner, "SCRIPT", s)

    app = create_app(_config())

    async def _do():
        # Pre-login with one transport, then re-use the cookies for both
        # concurrent requests on a separate gather.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            login = await client.post(
                "/login",
                data={"username": ADMIN_USER, "password": ADMIN_PW},
            )
            assert login.status_code == 302, login.text
            session_cookie = login.cookies.get("session")
            assert session_cookie

            cookies = {"session": session_cookie}
            r1, r2 = await asyncio.gather(
                client.post("/api/services/start", cookies=cookies),
                client.post("/api/services/start", cookies=cookies),
            )

            # Drain the running job before we exit so subsequent tests start clean.
            for _ in range(80):
                if not runner._lock.locked():
                    break
                await asyncio.sleep(0.05)
            return r1, r2

    r1, r2 = asyncio.run(_do())
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], f"expected [200, 409], got {statuses}"
    busy = r1 if r1.status_code == 409 else r2
    assert "Đang có lệnh khác chạy" in busy.text
    assert busy.headers.get("hx-trigger") == "lock-busy"
