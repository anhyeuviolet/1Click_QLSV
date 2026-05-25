"""Auth routes: GET/POST /login, POST /logout, and the `require_auth` dependency.

Contract (Plan 02 <interfaces>):
  router: APIRouter — registers GET /login, POST /login, POST /logout
  require_auth(request) -> str: returns the authenticated username, or raises
    HTTPException(302) redirecting to /login?next=<encoded original path>.

Credentials are read from `request.app.state.config["admin"]` — never hardcoded.
Comparison uses `secrets.compare_digest` (D-04) on bytes to avoid timing leaks.

Vietnamese copy is sourced from `qlsv.i18n.TRANSLATION` (delivered by Plan 03
Task 1) — no fallback dict, no inline overrides.
"""
from __future__ import annotations

import secrets
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from qlsv.i18n import TRANSLATION

router = APIRouter()


def _is_safe_next(next_url: Optional[str]) -> Optional[str]:
    """Return `next_url` only if it is a same-origin absolute path.

    Must start with `/` AND NOT start with `//` (rejects protocol-relative
    redirects like `//evil.example/`). Anything else returns None and the
    caller should fall back to `/`.
    """
    if not next_url:
        return None
    if not next_url.startswith("/"):
        return None
    if next_url.startswith("//"):
        return None
    return next_url


def require_auth(request: Request) -> str:
    """FastAPI dependency / inline guard for authenticated routes.

    Returns the username on success. On failure raises an HTTPException
    carrying a 302 to `/login?next=<encoded original path>` (when the path
    is not `/`).
    """
    user = request.session.get("user")
    if user:
        return user
    path = request.url.path or "/"
    next_param = "?next=" + urllib.parse.quote(path, safe="/")
    raise HTTPException(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": f"/login{next_param}"},
    )


@router.get("/login", include_in_schema=False)
def login_form(request: Request) -> Response:
    """Render the login form. If already authenticated, 302 to `/`."""
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=302)
    templates = request.app.state.templates
    next_param = _is_safe_next(request.query_params.get("next"))
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "username": "",
            "next": next_param,
        },
    )


@router.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
) -> Response:
    """Validate credentials and either redirect or re-render with error."""
    cfg = request.app.state.config
    admin_cfg = (cfg.get("admin") or {})
    expected_user = admin_cfg.get("username", "")
    expected_pw = admin_cfg.get("password", "")

    # Constant-time compare on bytes (D-04). Compute BOTH before combining so
    # short-circuit evaluation cannot leak per-field timing.
    user_ok = secrets.compare_digest(
        username.encode("utf-8"), expected_user.encode("utf-8")
    )
    pw_ok = secrets.compare_digest(
        password.encode("utf-8"), expected_pw.encode("utf-8")
    )
    credentials_ok = bool(user_ok) & bool(pw_ok)

    # Empty password is never valid even if expected_pw happens to be empty
    # (defensive — load_config rejects empty admin.password at startup).
    if not password:
        credentials_ok = False

    if credentials_ok:
        request.session["user"] = username
        target = _is_safe_next(next) or "/"
        return RedirectResponse(url=target, status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": TRANSLATION["login_error_invalid"],
            "username": username,
            "next": _is_safe_next(next),
        },
        status_code=200,
    )


@router.post("/logout", include_in_schema=False)
def logout(request: Request) -> Response:
    """Clear the session and redirect to /login."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
