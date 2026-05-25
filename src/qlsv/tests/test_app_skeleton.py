"""Tests for the FastAPI walking-skeleton: app factory, /healthz, / redirect, __main__."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qlsv.app import create_app


def _valid_config() -> dict:
    return {
        "game": {"directory": "/home/jxser", "server_ip": "", "server_mac": ""},
        "web": {"bind_addr": "127.0.0.1", "port": 0, "idle_timeout_seconds": 2592000, "cookie_secure": False},
        "admin": {"username": "admin", "password": "secret"},
        "session": {"secret_key": "k" * 32},
        "db": {
            "mysql": {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "p"},
            "mssql": {"host": "127.0.0.1", "port": 1433, "user": "SA", "password": "p"},
        },
    }


@pytest.fixture
def client() -> TestClient:
    app = create_app(_valid_config())
    return TestClient(app, follow_redirects=False)


def test_create_app_returns_fastapi():
    app = create_app(_valid_config())
    assert isinstance(app, FastAPI)
    assert app.state.config["admin"]["username"] == "admin"


def test_root_unauthenticated_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    loc = r.headers.get("location", "")
    assert loc.startswith("/login")


def test_root_unauthenticated_preserves_next(client):
    r = client.get("/")
    loc = r.headers.get("location", "")
    # next= preserved (root is /)
    assert "next=" in loc


def test_health_endpoint(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.text
    assert "ok" in body.lower()


def test_main_module_fails_on_missing_config(tmp_path):
    """`python -m qlsv` with QLSV_CONFIG_PATH=/nonexistent exits non-zero with Vietnamese error."""
    missing = str(tmp_path / "absent.json")
    env = os.environ.copy()
    env["QLSV_CONFIG_PATH"] = missing
    # PYTHONIOENCODING ensures stderr decodes Vietnamese diacritics on Windows.
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "qlsv"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode != 0
    stderr = result.stderr or ""
    assert ("Không tìm thấy" in stderr) or ("Chưa cấu hình" in stderr)
