"""Dashboard route. Protected by `require_auth`; renders `dashboard.html`."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from qlsv.web.auth import require_auth

router = APIRouter()


@router.get("/", include_in_schema=False)
def dashboard_root(request: Request) -> Response:
    """Render the placeholder authenticated dashboard.

    Plan 02 replaces the cookie-presence placeholder with proper session-backed
    auth via `require_auth`. Unauthenticated requests 302 to /login?next=/.
    """
    try:
        username = require_auth(request)
    except HTTPException as exc:
        # require_auth raised 302; honor it as a real redirect response.
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "username": username},
    )
