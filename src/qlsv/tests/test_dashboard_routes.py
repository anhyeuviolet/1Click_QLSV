"""Tests for Phase 2 dashboard: GET / + GET /api/services/status (HTMX partial).

Monkeypatches ``qlsv.processes.probe_all`` and ``qlsv.state.load_state`` so
the tests are platform-independent (don't touch real pgrep / /var/lib/qlsv).
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from qlsv import processes, state
from qlsv.app import create_app
from qlsv.processes import ALLOWED_SERVICES, SERVICE_PGREP_PATTERNS

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
def all_dead(monkeypatch):
    monkeypatch.setattr(processes, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    monkeypatch.setattr(state, "load_state", lambda path=None: {})


@pytest.fixture
def client(all_dead) -> TestClient:
    return TestClient(create_app(_config()), follow_redirects=False)


def _login(client: TestClient) -> TestClient:
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302
    return client


# --------------------------------------------------------------------------- #
# GET /                                                                        #
# --------------------------------------------------------------------------- #


def test_dashboard_unauth_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


def test_dashboard_authenticated_renders_six_service_rows(client):
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    body = r.content
    for svc in ALLOWED_SERVICES:
        marker = f'data-service="{svc}"'.encode("utf-8")
        assert marker in body, f"missing row for {svc}"
    # All probes False + state empty → every badge is stopped.
    assert body.count(b"badge badge-stopped") == 6
    # Header and table heading present.
    assert "Trạng thái dịch vụ".encode("utf-8") in body
    # HTMX self-poll attrs on the <tbody>.
    assert b'hx-get="/api/services/status"' in body
    assert b'hx-trigger="every 5s"' in body


def test_dashboard_crashed_badge_when_expected_running_but_dead(monkeypatch):
    monkeypatch.setattr(processes, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    monkeypatch.setattr(
        state, "load_state",
        lambda path=None: {"bishop": {"expected_running": True}},
    )
    c = TestClient(create_app(_config()), follow_redirects=False)
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    r = c.get("/")
    assert r.status_code == 200
    body = r.content
    # bishop row must carry the crashed badge.
    assert b'data-service="bishop"' in body
    # The other five must still be stopped.
    assert body.count(b"badge badge-stopped") == 5
    assert body.count(b"badge badge-crashed") == 1


def test_dashboard_running_badge_when_process_alive(monkeypatch):
    alive_map = {svc: False for svc in SERVICE_PGREP_PATTERNS}
    alive_map["goddess"] = True
    monkeypatch.setattr(processes, "probe_all", lambda: alive_map)
    monkeypatch.setattr(state, "load_state", lambda path=None: {})
    c = TestClient(create_app(_config()), follow_redirects=False)
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    r = c.get("/")
    assert r.status_code == 200
    assert r.content.count(b"badge badge-running") == 1
    assert r.content.count(b"badge badge-stopped") == 5


# --------------------------------------------------------------------------- #
# GET /api/services/status                                                     #
# --------------------------------------------------------------------------- #


def test_api_status_returns_tbody_partial(client):
    _login(client)
    r = client.get("/api/services/status")
    assert r.status_code == 200
    body = r.content
    # Partial: starts with <tbody, no <html / <body wrapper.
    assert b"<tbody" in body
    assert b"<html" not in body
    assert b"<body" not in body.lower() or body.lower().count(b"<body") == 0
    # Self-perpetuate hx-trigger present on the partial.
    assert b'hx-trigger="every 5s"' in body
    # All 6 services rendered.
    for svc in ALLOWED_SERVICES:
        assert f'data-service="{svc}"'.encode("utf-8") in body


def test_api_status_unauth_redirects(client):
    # Fresh client without login
    r = client.get("/api/services/status")
    # Accept 302 (current implementation) or 401 — both are acceptable per plan.
    assert r.status_code in (302, 401), r.status_code


def test_api_status_respects_custom_poll_interval(monkeypatch):
    cfg = _config()
    cfg["dashboard"]["poll_interval_seconds"] = 10
    monkeypatch.setattr(processes, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    monkeypatch.setattr(state, "load_state", lambda path=None: {})
    c = TestClient(create_app(cfg), follow_redirects=False)
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    r = c.get("/api/services/status")
    assert r.status_code == 200
    assert b'hx-trigger="every 10s"' in r.content


# --------------------------------------------------------------------------- #
# Render-order guarantee                                                       #
# --------------------------------------------------------------------------- #


def test_dashboard_rows_render_in_canonical_order(client):
    _login(client)
    r = client.get("/")
    body = r.content.decode("utf-8")
    # Find indices of each data-service= marker and check monotonic order.
    indices = [body.index(f'data-service="{svc}"') for svc in SERVICE_PGREP_PATTERNS]
    assert indices == sorted(indices), "rows out of canonical order"
