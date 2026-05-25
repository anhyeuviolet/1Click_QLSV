"""Dashboard routes — GET / (full page) + GET /api/services/status (HTMX partial).

Both routes are protected by ``require_auth``. The HTMX endpoint returns the
``<tbody>`` fragment via ``_service_table.html`` so the table self-perpetuates
its own poll attrs (DASH-02).

Status resolution per truth table D-10: ``compute_status`` combines
``state.json::expected_running`` (intent) with live ``pgrep`` output
(reality) into one of ``running | stopped | crashed``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from qlsv import processes, state
from qlsv.i18n import TRANSLATION
from qlsv.processes import (
    SERVICE_DISPLAY_LABELS,
    SERVICE_PGREP_PATTERNS,
    compute_status,
)
from qlsv.web.auth import require_auth

router = APIRouter()


def _build_rows() -> list[dict[str, Any]]:
    """Probe live processes + load state, render the canonical row list.

    Iteration order follows ``SERVICE_PGREP_PATTERNS`` insertion order —
    that is the UI render order.
    """
    current_state = state.load_state()
    alive = processes.probe_all()
    rows: list[dict[str, Any]] = []
    for svc in SERVICE_PGREP_PATTERNS:
        expected = state.get_expected_running(current_state, svc)
        status = compute_status(svc, expected, alive.get(svc, False))
        rows.append(
            {
                "service": svc,
                "label": SERVICE_DISPLAY_LABELS[svc],
                "status": status,
                "badge_text": TRANSLATION[f"badge_{status}"],
            }
        )
    return rows


def _poll_interval(request: Request) -> int:
    cfg = getattr(request.app.state, "config", {}) or {}
    dash = cfg.get("dashboard", {}) or {}
    try:
        return int(dash.get("poll_interval_seconds", 5))
    except (TypeError, ValueError):
        return 5


@router.get("/", include_in_schema=False)
def dashboard_root(request: Request) -> Response:
    """Render the authenticated dashboard with the live service status table."""
    try:
        username = require_auth(request)
    except HTTPException as exc:
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=302)

    rows = _build_rows()
    poll_interval = _poll_interval(request)
    refresh_hint = TRANSLATION["refresh_hint_template"].format(seconds=poll_interval)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "username": username,
            "t": TRANSLATION,
            "rows": rows,
            "poll_interval": poll_interval,
            "refresh_hint": refresh_hint,
            "services_empty_heading": TRANSLATION["services_empty_heading"],
            "services_empty_body": TRANSLATION["services_empty_body"],
        },
    )


@router.get("/api/services/status", include_in_schema=False)
def services_status_partial(request: Request) -> Response:
    """Return the ``<tbody>`` fragment for HTMX polling (DASH-02).

    On unauthenticated request ``require_auth`` raises HTTPException(302).
    HTMX will surface the redirect via its native 3xx handling; Plan 04
    adds a friendlier toast. Plan 02 accepts the bare 302.
    """
    try:
        require_auth(request)
    except HTTPException as exc:
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=302)

    rows = _build_rows()
    poll_interval = _poll_interval(request)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "_service_table.html",
        {
            "request": request,
            "rows": rows,
            "poll_interval": poll_interval,
            "services_empty_heading": TRANSLATION["services_empty_heading"],
            "services_empty_body": TRANSLATION["services_empty_body"],
        },
    )
