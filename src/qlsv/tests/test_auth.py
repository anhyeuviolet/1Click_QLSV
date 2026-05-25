"""Tests for Phase 1 / Plan 02 auth: /login, /logout, require_auth dependency.

Covers all behaviour bullets from `01-02-PLAN.md <behavior>` for Task 2,
plus the cookie-attribute regression test from `<acceptance_criteria>`.
"""
from __future__ import annotations

import re
import secrets

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from qlsv.app import create_app
from qlsv.web.auth import _is_safe_next, require_auth

# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

ADMIN_USER = "ngdat"
ADMIN_PW = "hunter2"
IDLE = 2592000


def _config() -> dict:
    return {
        "game": {"directory": "/home/jxser", "server_ip": "", "server_mac": ""},
        "web": {
            "bind_addr": "127.0.0.1",
            "port": 0,
            "idle_timeout_seconds": IDLE,
            "cookie_secure": False,
        },
        "admin": {"username": ADMIN_USER, "password": ADMIN_PW},
        "session": {"secret_key": secrets.token_urlsafe(48)},
        "db": {
            "mysql": {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "p"},
            "mssql": {"host": "127.0.0.1", "port": 1433, "user": "SA", "password": "p"},
        },
    }


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_config()), follow_redirects=False)


def _login(client: TestClient, username: str = ADMIN_USER, password: str = ADMIN_PW) -> TestClient:
    """Drive a successful login through the form endpoint and return the same client."""
    r = client.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, r.status_code
    return client


# --------------------------------------------------------------------------- #
# Unauthenticated access                                                       #
# --------------------------------------------------------------------------- #


def test_get_root_unauth_redirects_to_login_with_next(client):
    r = client.get("/")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert re.match(r"^/login(\?next=/)?$", loc), loc


def test_get_login_returns_200_and_form(client):
    r = client.get("/login")
    assert r.status_code == 200
    body = r.text
    assert "Đăng nhập" in body
    assert "Tên đăng nhập" in body
    assert '<form' in body
    assert 'method="post"' in body
    assert 'action="/login"' in body


def test_get_login_when_authed_redirects_to_root(client):
    _login(client)
    r = client.get("/login")
    assert r.status_code == 302
    assert r.headers["location"] == "/"


# --------------------------------------------------------------------------- #
# POST /login                                                                  #
# --------------------------------------------------------------------------- #


def test_post_login_wrong_credentials_returns_200_with_error_banner(client):
    r = client.post("/login", data={"username": "bad", "password": "bad"})
    assert r.status_code == 200
    body = r.text
    assert "Tên đăng nhập hoặc mật khẩu không đúng" in body
    assert 'role="alert"' in body
    # No session cookie issued on failure (or it carries an empty session).
    # Starlette only sets the cookie when session was mutated; failure path
    # does NOT touch the session, so no Set-Cookie at all.
    set_cookie_headers = [v for k, v in r.headers.raw if k.lower() == b"set-cookie"]
    for raw in set_cookie_headers:
        assert b"session=" not in raw or b"session=;" in raw, raw


def test_post_login_correct_credentials_redirects_to_root(client):
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    set_cookie = r.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    # Case-insensitive attribute presence.
    lower = set_cookie.lower()
    assert "httponly" in lower
    assert "samesite=strict" in lower
    assert "path=/" in lower
    assert f"max-age={IDLE}" in lower


def test_post_login_with_next_redirects_to_next(client):
    r = client.post(
        "/login",
        data={"username": ADMIN_USER, "password": ADMIN_PW, "next": "/somewhere"},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/somewhere"


def test_post_login_with_external_next_falls_back_to_root(client):
    # Protocol-relative URL must be rejected by _is_safe_next.
    r = client.post(
        "/login",
        data={
            "username": ADMIN_USER,
            "password": ADMIN_PW,
            "next": "//evil.example/",
        },
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_post_login_uses_constant_time_compare():
    """Source-level evidence that secrets.compare_digest is used (D-04)."""
    src = (
        __import__("pathlib").Path("src/qlsv/web/auth.py").read_text(encoding="utf-8")
    )
    assert "secrets.compare_digest" in src or "compare_digest" in src


def test_post_login_form_with_empty_password_is_rejected(client):
    # FastAPI's Form(...) without min_length will accept "" — our code path
    # explicitly forces credentials_ok = False on empty password.
    r = client.post("/login", data={"username": ADMIN_USER, "password": ""})
    # Either a 200 re-render with the error, or 422 from the form parser;
    # never a 302.
    assert r.status_code in (200, 422), r.status_code
    assert "session=" not in r.headers.get("set-cookie", "")


def test_post_login_username_preserved_on_error(client):
    r = client.post("/login", data={"username": "ngdat", "password": "wrong"})
    assert r.status_code == 200
    assert 'value="ngdat"' in r.text
    # Password field must NOT be pre-filled.
    assert 'name="password"' in r.text
    assert 'value="wrong"' not in r.text


# --------------------------------------------------------------------------- #
# POST /logout                                                                 #
# --------------------------------------------------------------------------- #


def test_post_logout_clears_session_and_redirects(client):
    _login(client)
    # Confirm authenticated.
    r = client.get("/")
    assert r.status_code == 200

    r = client.post("/logout")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"
    set_cookie = r.headers.get("set-cookie", "")
    # Either Max-Age=0 or an expiry in the past — Starlette uses Max-Age=0.
    assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()

    # After logout the client should be bounced from `/` again.
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


def test_get_logout_not_allowed(client):
    r = client.get("/logout")
    assert r.status_code == 405


# --------------------------------------------------------------------------- #
# require_auth dependency                                                      #
# --------------------------------------------------------------------------- #


def test_require_auth_dependency_redirects_when_unauth():
    """Mount a throwaway route that uses require_auth and exercise both paths."""
    app = create_app(_config())

    @app.get("/_probe")
    def probe(user: str = Depends(require_auth)) -> dict:
        return {"user": user}

    c = TestClient(app, follow_redirects=False)

    # Unauthenticated: 302 to /login?next=/_probe
    r = c.get("/_probe")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/login?next=")
    assert "%2F_probe" in loc or "/_probe" in loc

    # Authenticated: 200
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    r = c.get("/_probe")
    assert r.status_code == 200
    assert r.json() == {"user": ADMIN_USER}


# --------------------------------------------------------------------------- #
# Cookie attribute regression                                                  #
# --------------------------------------------------------------------------- #


def test_session_cookie_has_required_flags(client):
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
    assert r.status_code == 302
    set_cookie = r.headers["set-cookie"]
    lower = set_cookie.lower()
    assert "httponly" in lower, set_cookie
    assert "samesite=strict" in lower, set_cookie
    assert "secure" not in lower, set_cookie  # cookie_secure=False in test config
    assert f"max-age={IDLE}" in lower, set_cookie


# --------------------------------------------------------------------------- #
# _is_safe_next unit                                                           #
# --------------------------------------------------------------------------- #


def test_is_safe_next_accepts_absolute_same_origin_paths():
    assert _is_safe_next("/") == "/"
    assert _is_safe_next("/foo") == "/foo"
    assert _is_safe_next("/foo/bar?x=1") == "/foo/bar?x=1"


def test_is_safe_next_rejects_external_and_relative():
    assert _is_safe_next(None) is None
    assert _is_safe_next("") is None
    assert _is_safe_next("//evil.example/") is None
    assert _is_safe_next("http://evil.example/") is None
    assert _is_safe_next("foo") is None


# --------------------------------------------------------------------------- #
# No hardcoded credentials                                                     #
# --------------------------------------------------------------------------- #


def test_auth_module_has_no_hardcoded_credentials():
    src = (
        __import__("pathlib").Path("src/qlsv/web/auth.py").read_text(encoding="utf-8")
    )
    assert "1234560123" not in src
    assert "SAJx123456" not in src
