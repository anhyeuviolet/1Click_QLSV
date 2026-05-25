"""Placeholder dashboard router for Plan 01.

Plan 03 replaces the cookie check with real SessionMiddleware-based auth and
swaps the PlainTextResponse for a Jinja template.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

router = APIRouter()


@router.get("/", include_in_schema=False)
def dashboard_root(request: Request):
    """Show the dashboard if a session cookie is present, else 302 to /login.

    The session-cookie check is intentionally coarse in Plan 01 (any cookie
    value passes). Plan 03 wires Starlette SessionMiddleware so a forged
    cookie cannot pass (T-01-06).
    """
    if not request.cookies.get("session"):
        # Preserve `next` so login can bounce admin back to where they were.
        return RedirectResponse(url="/login?next=/", status_code=302)
    return PlainTextResponse("Trang chính - placeholder", status_code=200)
