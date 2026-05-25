"""Tests for qlsv.state — atomic state file + bind_addr loopback validation (WEB-02)."""
from __future__ import annotations

import json
import os
import sys

import pytest

from qlsv.config import ConfigError, load_config
from qlsv.state import (
    get_expected_running,
    load_state,
    mark_started,
    mark_stopped,
    save_state,
)


def _valid_config_base() -> dict:
    return {
        "game": {"directory": "/home/jxser", "server_ip": "", "server_mac": ""},
        "web": {"bind_addr": "0.0.0.0", "port": 8080, "idle_timeout_seconds": 2592000, "cookie_secure": False},
        "admin": {"username": "admin", "password": "supersecret"},
        "session": {"secret_key": "x" * 32},
        "db": {
            "mysql": {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "p1"},
            "mssql": {"host": "127.0.0.1", "port": 1433, "user": "SA", "password": "p2"},
        },
    }


def _write_cfg(tmp_path, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# save_state / load_state                                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 only enforced on POSIX")
def test_save_state_creates_file_mode_0600(tmp_path):
    target = tmp_path / "state.json"
    save_state({"bishop": {"expected_running": True}}, path=str(target))
    mode = os.stat(target).st_mode & 0o777
    assert oct(mode) == "0o600"


def test_load_state_missing_file_returns_empty(tmp_path):
    missing = str(tmp_path / "nonexistent.json")
    assert load_state(missing) == {}


def test_load_state_bad_json_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not json at all", encoding="utf-8")
    assert load_state(str(p)) == {}


def test_load_state_non_dict_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_state(str(p)) == {}


def test_mark_started_sets_expected_running_true(tmp_path):
    target = str(tmp_path / "state.json")
    mark_started("bishop", path=target)
    state = load_state(target)
    assert state["bishop"]["expected_running"] is True
    assert "last_started_at" in state["bishop"]
    assert state["bishop"]["last_started_at"]  # non-empty ISO timestamp


def test_mark_stopped_preserves_last_started_at(tmp_path):
    target = str(tmp_path / "state.json")
    # Seed with a previous start.
    mark_started("bishop", path=target)
    started_ts = load_state(target)["bishop"]["last_started_at"]
    mark_stopped("bishop", path=target)
    state = load_state(target)
    assert state["bishop"]["expected_running"] is False
    assert state["bishop"]["last_started_at"] == started_ts
    assert state["bishop"]["last_stopped_at"]


def test_mark_started_preserves_last_stopped_at(tmp_path):
    target = str(tmp_path / "state.json")
    mark_started("bishop", path=target)
    mark_stopped("bishop", path=target)
    stopped_ts = load_state(target)["bishop"]["last_stopped_at"]
    mark_started("bishop", path=target)
    state = load_state(target)
    assert state["bishop"]["expected_running"] is True
    assert state["bishop"]["last_stopped_at"] == stopped_ts


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX atomic-write assert")
def test_save_state_atomic_no_partial_write(tmp_path):
    target = tmp_path / "state.json"
    save_state({"bishop": {"expected_running": True}}, path=str(target))
    assert not os.path.exists(str(target) + ".tmp")


def test_get_expected_running_defaults_false_for_missing_service():
    assert get_expected_running({}, "bishop") is False
    assert get_expected_running({"bishop": {}}, "bishop") is False
    assert get_expected_running({"bishop": {"expected_running": True}}, "bishop") is True
    assert get_expected_running({"bishop": "garbage"}, "bishop") is False


# --------------------------------------------------------------------------- #
# WEB-02 / M-2 — loopback bind_addr rejection (IPv4 + IPv6)                    #
# --------------------------------------------------------------------------- #


def test_config_loopback_bind_addr_rejected_ipv4(tmp_path):
    cfg = _valid_config_base()
    cfg["web"]["bind_addr"] = "127.0.0.1"
    path = _write_cfg(tmp_path, cfg)
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "WEB-02" in str(ei.value)
    assert "loopback" in str(ei.value)


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.5", "127.255.255.254", "::1", "[::1]", "0:0:0:0:0:0:0:1", "localhost"],
)
def test_config_loopback_bind_addr_rejected_ipv6_and_class_a(tmp_path, addr):
    cfg = _valid_config_base()
    cfg["web"]["bind_addr"] = addr
    path = _write_cfg(tmp_path, cfg)
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "WEB-02" in str(ei.value)


@pytest.mark.parametrize(
    "addr",
    ["0.0.0.0", "10.0.0.5", "192.168.1.10", "::", "myserver.local"],
)
def test_config_non_loopback_bind_addr_accepted(tmp_path, addr):
    cfg = _valid_config_base()
    cfg["web"]["bind_addr"] = addr
    path = _write_cfg(tmp_path, cfg)
    # Should not raise.
    loaded = load_config(path)
    assert loaded["web"]["bind_addr"] == addr


def test_config_dashboard_defaults_applied(tmp_path):
    cfg = _valid_config_base()
    # No "dashboard" key in config.
    assert "dashboard" not in cfg
    path = _write_cfg(tmp_path, cfg)
    loaded = load_config(path)
    assert loaded["dashboard"]["poll_interval_seconds"] == 5


def test_config_dashboard_override_preserved(tmp_path):
    cfg = _valid_config_base()
    cfg["dashboard"] = {"poll_interval_seconds": 10}
    path = _write_cfg(tmp_path, cfg)
    loaded = load_config(path)
    assert loaded["dashboard"]["poll_interval_seconds"] == 10
