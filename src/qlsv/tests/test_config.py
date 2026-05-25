"""Tests for qlsv.config — fail-fast validation, atomic write, legacy migration."""
from __future__ import annotations

import json
import os
import sys

import pytest

from qlsv.config import (
    ConfigError,
    load_config,
    save_config,
    migrate_if_needed,
    CONFIGFILE,
    BACKUP_SUFFIX,
)


def _valid_config() -> dict:
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


def _write(tmp_path, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_load_valid_config(tmp_path):
    cfg = _valid_config()
    path = _write(tmp_path, cfg)
    loaded = load_config(path)
    assert loaded["admin"]["username"] == "admin"
    assert loaded["admin"]["password"] == "supersecret"
    assert loaded["session"]["secret_key"] == "x" * 32


def test_load_missing_admin_username_raises(tmp_path):
    cfg = _valid_config()
    del cfg["admin"]["username"]
    path = _write(tmp_path, cfg)
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "Chưa cấu hình admin" in str(ei.value)
    assert path in str(ei.value)


def test_load_missing_admin_password_raises(tmp_path):
    cfg = _valid_config()
    cfg["admin"]["password"] = ""
    path = _write(tmp_path, cfg)
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    # Vietnamese message
    msg = str(ei.value)
    assert "Chưa cấu hình admin" in msg or "admin.password" in msg


def test_load_missing_session_secret_raises(tmp_path):
    cfg = _valid_config()
    del cfg["session"]["secret_key"]
    path = _write(tmp_path, cfg)
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "session.secret_key" in str(ei.value)


def test_load_file_not_found_raises(tmp_path):
    missing = str(tmp_path / "does_not_exist.json")
    with pytest.raises(ConfigError) as ei:
        load_config(missing)
    msg = str(ei.value)
    assert "Không tìm thấy" in msg
    assert missing in msg


def test_load_invalid_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(str(p))
    assert "Không đọc được" in str(ei.value)


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 only enforced on POSIX")
def test_save_creates_file_mode_0600(tmp_path):
    cfg = _valid_config()
    path = str(tmp_path / "out.json")
    save_config(cfg, path)
    mode = os.stat(path).st_mode & 0o777
    assert oct(mode) == "0o600"


def test_save_atomic_does_not_leave_partial(tmp_path):
    cfg = _valid_config()
    path = str(tmp_path / "out.json")
    save_config(cfg, path)
    # No leftover .tmp
    assert not os.path.exists(path + ".tmp")
    # File contents match exactly
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == cfg


def test_save_pretty_prints_with_indent_2(tmp_path):
    cfg = _valid_config()
    path = str(tmp_path / "out.json")
    save_config(cfg, path)
    text = open(path, "r", encoding="utf-8").read()
    assert "\n" in text
    # 2-space indent for nested objects
    assert "\n  " in text


def test_migrate_flat_to_nested(tmp_path):
    flat = {
        "directory": "/home/jxser_8.1_vinh",
        "server_ip": "192.168.1.10",
        "server_mac": "AA-BB-CC-DD-EE-FF",
    }
    path = _write(tmp_path, flat)
    result = migrate_if_needed(path)
    assert result is True
    with open(path, "r", encoding="utf-8") as f:
        new = json.load(f)
    assert new["game"]["directory"] == "/home/jxser_8.1_vinh"
    assert new["game"]["server_ip"] == "192.168.1.10"
    assert new["game"]["server_mac"] == "AA-BB-CC-DD-EE-FF"
    # Backup exists with flat shape
    backup_path = path + BACKUP_SUFFIX
    assert os.path.exists(backup_path)
    with open(backup_path, "r", encoding="utf-8") as f:
        bak = json.load(f)
    assert bak == flat


def test_migrate_idempotent_when_nested(tmp_path):
    cfg = _valid_config()
    path = _write(tmp_path, cfg)
    result = migrate_if_needed(path)
    assert result is False
    assert not os.path.exists(path + BACKUP_SUFFIX)
    # File unchanged
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == cfg


def test_migrate_preserves_other_top_level_keys(tmp_path):
    legacy = {
        "directory": "/home/jx",
        "server_ip": "1.2.3.4",
        "server_mac": "AA",
        "admin": {"username": "u", "password": "p"},
        "session": {"secret_key": "s"},
    }
    path = _write(tmp_path, legacy)
    result = migrate_if_needed(path)
    assert result is True
    with open(path, "r", encoding="utf-8") as f:
        new = json.load(f)
    assert new["game"]["directory"] == "/home/jx"
    assert new["game"]["server_ip"] == "1.2.3.4"
    assert new["admin"]["username"] == "u"
    assert new["session"]["secret_key"] == "s"
    # Legacy top-level keys gone
    assert "directory" not in new
    assert "server_ip" not in new
    assert "server_mac" not in new


def test_configfile_constant():
    assert CONFIGFILE == "/root/.quanlyserver.json"
