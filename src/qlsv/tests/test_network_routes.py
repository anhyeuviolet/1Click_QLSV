"""Tests for POST /api/network/save + GET /api/network/preview (Plan 02-04).

Covers:
  - Auth gating (302 → /login).
  - Strict ``iface`` whitelist (T-02-20 / T-02-21).
  - Atomic config write via ``save_config`` spy.
  - ``ip_mac_reconfig_banner`` rendered iff any service alive.
  - ``HX-Trigger: ip-mac-saved`` header on save.
  - M-7 drift banner appears on GET ``/`` when saved IP/MAC don't match any
    detected interface; absent when they do.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from qlsv import processes, state
from qlsv.app import create_app
from qlsv.processes import SERVICE_PGREP_PATTERNS
from qlsv.web import network as web_network

ADMIN_USER = "ngdat"
ADMIN_PW = "hunter2"


def _config(**overrides) -> dict:
    cfg = {
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
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


@pytest.fixture
def all_dead(monkeypatch):
    """No services alive — neutralises probe_all + state for dashboard render."""
    monkeypatch.setattr(processes, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    monkeypatch.setattr(state, "load_state", lambda path=None: {})


@pytest.fixture
def eth0_only(monkeypatch):
    """Single ``eth0`` interface visible to both the route and the dashboard."""
    ifaces = [{"interface": "eth0", "ip": "10.0.0.5", "mac": "AA-BB-CC-DD-EE-FF"}]
    # Patch at BOTH consumption sites — dashboard.py imports it directly,
    # web/network.py imports it directly. ``setattr`` on the qlsv.net source
    # only would miss the bound references.
    monkeypatch.setattr("qlsv.net.get_all_network_interfaces", lambda: ifaces)
    monkeypatch.setattr(web_network, "get_all_network_interfaces", lambda: ifaces)
    import qlsv.web.dashboard as web_dashboard
    monkeypatch.setattr(web_dashboard, "get_all_network_interfaces", lambda: ifaces)
    return ifaces


@pytest.fixture
def no_ifaces(monkeypatch):
    """get_all_network_interfaces → []."""
    monkeypatch.setattr("qlsv.net.get_all_network_interfaces", lambda: [])
    monkeypatch.setattr(web_network, "get_all_network_interfaces", lambda: [])
    import qlsv.web.dashboard as web_dashboard
    monkeypatch.setattr(web_dashboard, "get_all_network_interfaces", lambda: [])


def _client(cfg: dict | None = None) -> TestClient:
    return TestClient(create_app(cfg or _config()), follow_redirects=False)


def _login(client: TestClient) -> TestClient:
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302, r.text
    return client


# --------------------------------------------------------------------------- #
# Auth                                                                         #
# --------------------------------------------------------------------------- #


def test_get_preview_unauth_redirects(all_dead, no_ifaces):
    c = _client()
    r = c.get("/api/network/preview?iface=eth0")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


def test_post_save_unauth_redirects(all_dead, no_ifaces):
    c = _client()
    r = c.post("/api/network/save", data={"iface": "eth0"})
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


# --------------------------------------------------------------------------- #
# GET /api/network/preview                                                     #
# --------------------------------------------------------------------------- #


def test_get_preview_valid_iface_returns_card_fragment(all_dead, eth0_only):
    c = _login(_client())
    r = c.get("/api/network/preview?iface=eth0")
    assert r.status_code == 200, r.text
    body = r.text
    assert "10.0.0.5" in body
    assert "AA-BB-CC-DD-EE-FF" in body
    assert 'id="ip-mac-card"' in body
    # Preview never sets HX-Trigger
    assert "ip-mac-saved" not in (r.headers.get("hx-trigger") or "")


def test_get_preview_unknown_iface_returns_400(all_dead, no_ifaces):
    c = _login(_client())
    r = c.get("/api/network/preview?iface=eth99")
    assert r.status_code == 400
    assert "Giao diện mạng không tồn tại" in r.text


def test_get_preview_path_traversal_iface_rejected(all_dead, eth0_only):
    c = _login(_client())
    r = c.get("/api/network/preview?iface=../../etc/hostname")
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# POST /api/network/save                                                       #
# --------------------------------------------------------------------------- #


def test_post_save_writes_config_atomically(all_dead, eth0_only, monkeypatch):
    c = _login(_client())
    captured: list[dict] = []

    def _spy(data, path=None):
        captured.append({"data": data, "path": path})

    monkeypatch.setattr(web_network.config_module, "save_config", _spy)
    r = c.post("/api/network/save", data={"iface": "eth0"})
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    cfg = captured[0]["data"]
    assert cfg["game"]["server_ip"] == "10.0.0.5"
    assert cfg["game"]["server_mac"] == "AA-BB-CC-DD-EE-FF"


def test_post_save_returns_warning_banner_when_service_alive(
    monkeypatch, eth0_only
):
    monkeypatch.setattr(
        processes,
        "probe_all",
        lambda: {svc: (svc == "bishop") for svc in SERVICE_PGREP_PATTERNS},
    )
    monkeypatch.setattr(state, "load_state", lambda path=None: {})
    monkeypatch.setattr(web_network.config_module, "save_config", lambda d, path=None: None)
    # network.py imports probe_all by name — patch the bound reference.
    monkeypatch.setattr(
        web_network,
        "probe_all",
        lambda: {svc: (svc == "bishop") for svc in SERVICE_PGREP_PATTERNS},
    )
    c = _login(_client())
    r = c.post("/api/network/save", data={"iface": "eth0"})
    assert r.status_code == 200, r.text
    assert "Cấu hình IP / MAC đã đổi" in r.text


def test_post_save_no_warning_banner_when_all_stopped(
    all_dead, eth0_only, monkeypatch
):
    monkeypatch.setattr(web_network.config_module, "save_config", lambda d, path=None: None)
    monkeypatch.setattr(web_network, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    c = _login(_client())
    r = c.post("/api/network/save", data={"iface": "eth0"})
    assert r.status_code == 200
    assert "Cấu hình IP / MAC đã đổi" not in r.text


def test_post_save_unknown_iface_returns_400(all_dead, no_ifaces, monkeypatch):
    saves: list = []
    monkeypatch.setattr(
        web_network.config_module,
        "save_config",
        lambda d, path=None: saves.append(d),
    )
    c = _login(_client())
    r = c.post("/api/network/save", data={"iface": "doesnotexist"})
    assert r.status_code == 400
    assert saves == []  # never wrote


def test_post_save_sets_hx_trigger_header(all_dead, eth0_only, monkeypatch):
    monkeypatch.setattr(web_network.config_module, "save_config", lambda d, path=None: None)
    monkeypatch.setattr(web_network, "probe_all", lambda: {svc: False for svc in SERVICE_PGREP_PATTERNS})
    c = _login(_client())
    r = c.post("/api/network/save", data={"iface": "eth0"})
    assert r.status_code == 200
    assert r.headers.get("hx-trigger") == "ip-mac-saved"


# --------------------------------------------------------------------------- #
# M-7: dashboard drift banner                                                  #
# --------------------------------------------------------------------------- #


def test_dashboard_renders_drift_banner_when_saved_ip_not_match(
    all_dead, eth0_only
):
    cfg = _config()
    cfg["game"]["server_ip"] = "192.168.99.99"
    cfg["game"]["server_mac"] = "00-00-00-00-00-00"
    c = _login(_client(cfg))
    r = c.get("/")
    assert r.status_code == 200
    assert "IP/MAC đã lưu không khớp interface hiện tại" in r.text


def test_dashboard_no_drift_banner_when_saved_ip_matches(all_dead, eth0_only):
    cfg = _config()
    cfg["game"]["server_ip"] = "10.0.0.5"
    cfg["game"]["server_mac"] = "AA-BB-CC-DD-EE-FF"
    c = _login(_client(cfg))
    r = c.get("/")
    assert r.status_code == 200
    assert "IP/MAC đã lưu không khớp interface hiện tại" not in r.text


def test_dashboard_first_run_banner_when_saved_empty(all_dead, eth0_only):
    c = _login(_client())
    r = c.get("/")
    assert r.status_code == 200
    assert "Chưa cấu hình IP / MAC" in r.text


def test_dashboard_no_ifaces_renders_empty_state(all_dead, no_ifaces):
    c = _login(_client())
    r = c.get("/")
    assert r.status_code == 200
    assert "Không phát hiện giao diện mạng" in r.text


def test_dashboard_history_card_rendered_with_correct_htmx_attrs(
    all_dead, eth0_only, monkeypatch
):
    """H-3 / H-4: dropdown uses query-string endpoint + hx-include="this"."""
    # Seed a fake history entry so the <select> renders (empty list → <p>).
    fake_jobs = [
        {
            "id": "a" * 32,
            "action": "start",
            "service": "bishop",
            "started_at": "2026-05-25T12:00:00Z",
            "ended_at": "2026-05-25T12:00:05Z",
            "exit_code": 0,
        }
    ]
    from qlsv.jobs import history as history_mod
    monkeypatch.setattr(history_mod, "list_jobs", lambda path=None: list(fake_jobs))
    c = _login(_client())
    r = c.get("/")
    assert r.status_code == 200
    body = r.text
    assert 'id="history-card"' in body
    # H-4: hx-get="/api/jobs/log" (NOT /api/jobs/log/{this.value}).
    assert 'hx-get="/api/jobs/log"' in body
    assert 'hx-include="this"' in body
    assert 'hx-target="#tail-pane"' in body
    assert 'hx-swap="outerHTML"' in body
    # No leftover placeholder syntax (H-4 regression guard).
    assert "{this.value}" not in body


# --------------------------------------------------------------------------- #
# Phase-2 gap-closure: game directory picker                                   #
# --------------------------------------------------------------------------- #


def test_get_game_dir_unauth_redirects(all_dead, no_ifaces):
    c = _client()
    r = c.get("/api/game/directory")
    assert r.status_code == 302
    assert "/login" in r.headers.get("location", "")


def test_post_game_dir_unauth_redirects(all_dead, no_ifaces):
    c = _client()
    r = c.post("/api/game/directory", data={"directory": "/tmp"})
    assert r.status_code == 302


def test_post_game_dir_rejects_relative_path(all_dead, no_ifaces):
    c = _login(_client())
    r = c.post("/api/game/directory", data={"directory": "relative/path"})
    assert r.status_code == 200  # Card re-renders with error inline
    assert "tuyệt đối" in r.text


def test_post_game_dir_rejects_missing_path(all_dead, no_ifaces):
    c = _login(_client())
    r = c.post("/api/game/directory", data={"directory": "/nonexistent-jx-dir-xyz"})
    assert r.status_code == 200
    assert "không tồn tại" in r.text


_POSIX_PATH = pytest.mark.skipif(
    not __import__("sys").platform.startswith(("linux", "darwin")),
    reason="path-shape validation requires absolute POSIX paths",
)


@_POSIX_PATH
def test_post_game_dir_rejects_dir_without_jx_subtrees(all_dead, no_ifaces, tmp_path):
    c = _login(_client())
    r = c.post("/api/game/directory", data={"directory": str(tmp_path)})
    assert r.status_code == 200
    assert "JX1" in r.text


@_POSIX_PATH
def test_post_game_dir_accepts_valid_jx_tree_and_persists(
    all_dead, no_ifaces, tmp_path, monkeypatch
):
    # Build a valid skeleton: tmp_path/gateway/ + tmp_path/server1/
    (tmp_path / "gateway").mkdir()
    (tmp_path / "server1").mkdir()

    saved = {}
    from qlsv import config as config_module
    monkeypatch.setattr(config_module, "save_config", lambda cfg: saved.update(cfg))

    c = _login(_client())
    r = c.post("/api/game/directory", data={"directory": str(tmp_path)})
    assert r.status_code == 200
    assert "Đã lưu" in r.text
    assert saved["game"]["directory"] == str(tmp_path.resolve())
