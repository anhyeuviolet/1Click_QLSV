"""End-to-end integration tests for Phase 2 (Plan 02-04).

Drives a real FastAPI app through:

  login → start service (mock jx.sh) → tail-pane streams stdout via SSE →
  state.json flips → stop service → history retains entry → IP/MAC save
  persists to tmp config → history dropdown swap returns SSE-vs-static
  fragments per H-3/H-4 → 25-job prune holds the ring buffer at 20 entries.

POSIX-only — the mock scripts use bash. The whole module is skipped on
Windows so the Windows dev box (where Phase 1 + 2 unit tests already pass)
isn't penalised.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from qlsv import state
from qlsv.app import create_app
from qlsv.jobs import history, log_stream, runner

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Phase 2 e2e needs bash + POSIX file modes",
)

ADMIN_USER = "ngdat"
ADMIN_PW = "hunter2"

MOCK_IFACE = "mock0"
MOCK_IP = "10.0.0.99"
MOCK_MAC = "00-11-22-33-44-55"


def _config_dict(tmp_config_path: Path) -> dict:
    return {
        "game": {
            "directory": "/tmp",
            "server_ip": MOCK_IP,
            "server_mac": MOCK_MAC,
        },
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
def mock_jx(tmp_path, monkeypatch):
    """Wire SCRIPT, JOB_LOG_DIR, JOBS_FILE, STATE_FILE, and the iface list."""
    script = tmp_path / "jx.sh"
    script.write_text(
        "#!/bin/bash\n"
        "echo \"Dang khoi dong $2\"\n"
        "sleep 0.1\n"
        "echo \"Da chay xong $2\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    log_dir = tmp_path / "jobs_log"
    log_dir.mkdir()
    jobs_file = tmp_path / "jobs.json"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.json"

    monkeypatch.setattr(runner, "SCRIPT", script)
    monkeypatch.setattr(runner, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(history, "JOBS_FILE", str(jobs_file))
    monkeypatch.setattr(log_stream, "JOB_LOG_DIR", log_dir)
    monkeypatch.setattr(state, "STATE_FILE", str(state_file))

    # Mock iface list visible to network.py + dashboard.py.
    ifaces = [{"interface": MOCK_IFACE, "ip": MOCK_IP, "mac": MOCK_MAC}]
    monkeypatch.setattr("qlsv.net.get_all_network_interfaces", lambda: ifaces)
    from qlsv.web import network as web_network
    monkeypatch.setattr(web_network, "get_all_network_interfaces", lambda: ifaces)
    from qlsv.web import dashboard as web_dashboard
    monkeypatch.setattr(web_dashboard, "get_all_network_interfaces", lambda: ifaces)

    # network.save_config writes to disk — point at tmp.
    from qlsv import config as config_module

    def _save_to_tmp(data, path=None):
        config_module.save_config.__wrapped__ = True  # marker (no real effect)
        from qlsv._atomic import write_json
        write_json(str(config_path), data, mode=0o600)

    monkeypatch.setattr(web_network.config_module, "save_config", _save_to_tmp)

    # Always-dead probe so probe_all doesn't hit pgrep / fail on the test host.
    from qlsv import processes
    monkeypatch.setattr(
        processes,
        "probe_all",
        lambda: {svc: False for svc in processes.SERVICE_PGREP_PATTERNS},
    )
    monkeypatch.setattr(web_network, "probe_all", lambda: {svc: False for svc in processes.SERVICE_PGREP_PATTERNS})

    # Reset module-level runner state — earlier tests in the suite may have
    # left the lock acquired / a stale _current_job behind.
    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None

    yield {
        "script": script,
        "log_dir": log_dir,
        "jobs_file": jobs_file,
        "state_file": state_file,
        "config_path": config_path,
    }

    if runner._lock.locked():
        runner._lock.release()
    runner._current_job = None


def _client(mock_jx) -> TestClient:
    return TestClient(
        create_app(_config_dict(mock_jx["config_path"])),
        follow_redirects=False,
    )


def _login(client: TestClient) -> None:
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302, r.text


def _wait_for_job_done(jobs_file: Path, job_id: str, timeout: float = 5.0) -> dict:
    """Poll the jobs.json file until the matching id has a non-null ``ended_at``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if jobs_file.exists():
            try:
                data = json.loads(jobs_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []
            for j in data:
                if j.get("id") == job_id and j.get("ended_at") is not None:
                    return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


def _wait_for_runner_idle(timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not runner._lock.locked() and runner._current_job is None:
            return
        time.sleep(0.05)
    raise AssertionError("runner stayed busy")


# --------------------------------------------------------------------------- #
# Happy path: login → start → stream → state flip → history                   #
# --------------------------------------------------------------------------- #


def test_happy_path_start_bishop_streams_and_marks_running(mock_jx):
    c = _client(mock_jx)
    _login(c)

    r = c.get("/")
    assert r.status_code == 200
    assert b'data-service="bishop"' in r.content
    assert b"badge badge-stopped" in r.content

    r = c.post("/api/services/start?service=bishop")
    assert r.status_code == 200, r.text
    body = r.json()
    job_id = body["job_id"]
    assert len(job_id) == 32
    assert body["action"] == "start"
    assert body["service"] == "bishop"

    _wait_for_job_done(mock_jx["jobs_file"], job_id)
    _wait_for_runner_idle()

    # Log file accumulated stdout from the mock script.
    log_path = mock_jx["log_dir"] / f"{job_id}.log"
    log_text = log_path.read_text(encoding="utf-8")
    assert "Dang khoi dong bishop" in log_text
    assert "Da chay xong bishop" in log_text
    # H-5: log file MUST NOT contain any `[__END__` sentinel.
    assert "[__END__" not in log_text

    # H-5: <job_id>.exit sidecar present + parseable.
    exit_path = mock_jx["log_dir"] / f"{job_id}.exit"
    assert exit_path.exists(), "exit sidecar missing"
    assert exit_path.read_text(encoding="utf-8").strip() == "exit=0"

    # state.json reflects mark_started(bishop).
    saved_state = json.loads(mock_jx["state_file"].read_text(encoding="utf-8"))
    assert saved_state["bishop"]["expected_running"] is True

    # jobs.json has the entry with exit_code=0.
    jobs = json.loads(mock_jx["jobs_file"].read_text(encoding="utf-8"))
    matches = [j for j in jobs if j["id"] == job_id]
    assert len(matches) == 1
    assert matches[0]["exit_code"] == 0
    assert matches[0]["ended_at"] is not None


def test_stop_after_start_clears_expected_running(mock_jx):
    c = _client(mock_jx)
    _login(c)

    r = c.post("/api/services/start?service=bishop")
    assert r.status_code == 200
    _wait_for_job_done(mock_jx["jobs_file"], r.json()["job_id"])
    _wait_for_runner_idle()

    r = c.post("/api/services/stop?service=bishop")
    assert r.status_code == 200
    _wait_for_job_done(mock_jx["jobs_file"], r.json()["job_id"])
    _wait_for_runner_idle()

    saved_state = json.loads(mock_jx["state_file"].read_text(encoding="utf-8"))
    assert saved_state["bishop"]["expected_running"] is False


# --------------------------------------------------------------------------- #
# Whitelist enforcement — bash injection / unknown service                    #
# --------------------------------------------------------------------------- #


def test_invalid_service_rejected_before_subprocess(mock_jx, tmp_path, monkeypatch):
    """The whitelist must trip BEFORE the runner ever spawns bash."""
    sentinel = tmp_path / "sentinel.txt"
    poisoned = tmp_path / "poisoned.sh"
    poisoned.write_text(
        f"#!/bin/bash\ntouch {sentinel}\nexit 0\n",
        encoding="utf-8",
    )
    poisoned.chmod(0o755)
    monkeypatch.setattr(runner, "SCRIPT", poisoned)

    c = _client(mock_jx)
    _login(c)
    r = c.post("/api/services/start?service=evil%3B+rm+-rf+%2F")
    assert r.status_code == 400
    # Critical: the subprocess was never spawned.
    assert not sentinel.exists(), "subprocess ran despite whitelist failure"


# --------------------------------------------------------------------------- #
# SSE stream — H-5 end frame from sidecar                                      #
# --------------------------------------------------------------------------- #


def test_sse_stream_emits_data_and_end_with_exit_sidecar(mock_jx):
    c = _client(mock_jx)
    _login(c)
    r = c.post("/api/services/start?service=bishop")
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    _wait_for_job_done(mock_jx["jobs_file"], job_id)
    _wait_for_runner_idle()

    # Stream after completion — generator drains the file then emits end frame.
    with c.stream("GET", f"/api/jobs/log?job_id={job_id}&mode=stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunks: list[str] = []
        deadline = time.monotonic() + 15.0
        for raw in resp.iter_lines():
            chunks.append(raw)
            if "event: end" in raw or (chunks and chunks[-1].startswith("event: end")):
                break
            if time.monotonic() > deadline:
                break
        text = "\n".join(chunks)
    assert "Dang khoi dong bishop" in text
    assert "event: end" in text
    assert '"exit_code": 0' in text


# --------------------------------------------------------------------------- #
# History prune — 25 → 20                                                      #
# --------------------------------------------------------------------------- #


def test_history_prune_after_25_jobs_keeps_20_and_deletes_logs(mock_jx):
    c = _client(mock_jx)
    _login(c)
    job_ids: list[str] = []
    for _ in range(25):
        r = c.post("/api/services/start?service=bishop")
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        job_ids.append(jid)
        _wait_for_job_done(mock_jx["jobs_file"], jid)
        _wait_for_runner_idle()

    jobs = json.loads(mock_jx["jobs_file"].read_text(encoding="utf-8"))
    assert len(jobs) == 20, f"expected ring-buffer at 20, got {len(jobs)}"

    log_files = [p for p in mock_jx["log_dir"].iterdir() if p.suffix == ".log"]
    exit_files = [p for p in mock_jx["log_dir"].iterdir() if p.suffix == ".exit"]
    assert len(log_files) <= 20
    assert len(exit_files) <= 20

    # Dashboard renders the trimmed list.
    r = c.get("/")
    assert r.status_code == 200
    option_count = r.text.count('<option value="')
    # 1 default option ("— live —") + N history rows; history is capped at 20.
    assert option_count <= 21


# --------------------------------------------------------------------------- #
# IP/MAC save persists to disk                                                 #
# --------------------------------------------------------------------------- #


def test_ip_mac_save_persists_to_tmp_config(mock_jx):
    c = _client(mock_jx)
    _login(c)
    r = c.post("/api/network/save", data={"iface": MOCK_IFACE})
    assert r.status_code == 200, r.text
    saved = json.loads(mock_jx["config_path"].read_text(encoding="utf-8"))
    assert saved["game"]["server_ip"] == MOCK_IP
    assert saved["game"]["server_mac"] == MOCK_MAC
    # Atomic write applies 0600 on POSIX.
    mode = os.stat(mock_jx["config_path"]).st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


# --------------------------------------------------------------------------- #
# History dropdown HTMX swap — H-3 / H-4 sanity                                #
# --------------------------------------------------------------------------- #


def test_history_dropdown_select_old_job_swaps_tail_pane_without_sse(mock_jx):
    c = _client(mock_jx)
    _login(c)
    r = c.post("/api/services/start?service=bishop")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    _wait_for_job_done(mock_jx["jobs_file"], job_id)
    _wait_for_runner_idle()

    r = c.get(f"/api/jobs/log?job_id={job_id}")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'id="tail-pane"' in body
    # Static mode = NO sse-connect attribute.
    assert "sse-connect" not in body


def test_history_dropdown_select_live_returns_sse_fragment(mock_jx):
    """Empty job_id → live fragment with sse-connect re-attached."""
    c = _client(mock_jx)
    _login(c)

    # Hit /api/jobs/log?job_id= (empty) — server picks current or most-recent.
    # We need a non-empty current_job to get sse-connect; queue a slower job.
    slow = mock_jx["script"].parent / "slow.sh"
    slow.write_text(
        "#!/bin/bash\nsleep 1\necho done\nexit 0\n",
        encoding="utf-8",
    )
    slow.chmod(0o755)

    # Swap SCRIPT mid-test
    runner.SCRIPT = slow
    try:
        r = c.post("/api/services/start?service=bishop")
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        # While the job is still running, hit the live endpoint.
        time.sleep(0.1)
        r = c.get("/api/jobs/log?job_id=")
        assert r.status_code == 200
        body = r.text
        assert 'id="tail-pane"' in body
        assert f"sse-connect" in body
        assert job_id in body
    finally:
        # Make sure the slow job finishes before the test exits.
        _wait_for_job_done(mock_jx["jobs_file"], job_id, timeout=10.0)
        _wait_for_runner_idle(timeout=10.0)
        runner.SCRIPT = mock_jx["script"]
