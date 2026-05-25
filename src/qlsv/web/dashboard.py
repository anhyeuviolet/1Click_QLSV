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

from pathlib import Path

from qlsv import processes, state
from qlsv.i18n import TRANSLATION
from qlsv.jobs import history, log_stream, runner
from qlsv.net import get_all_network_interfaces
from qlsv.processes import (
    SERVICE_DISPLAY_LABELS,
    SERVICE_PGREP_PATTERNS,
    compute_status,
)
from qlsv.web.auth import require_auth

_ACTION_VI = {
    "start_all": "Start all",
    "stop_all": "Stop all",
    "start": "Start",
    "stop": "Stop",
}
_LIVE_REATTACH_BYTES = 64 * 1024  # 64 KiB

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


def _annotate_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    enriched = dict(job)
    enriched["action_vi"] = _ACTION_VI.get(
        job.get("action", ""), job.get("action", "")
    )
    return enriched


def _read_tail(path: Path, max_bytes: int = _LIVE_REATTACH_BYTES) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    try:
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _build_history_options(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format <option> rows for the history dropdown — most-recent first.

    Each entry exposes both ``label`` (legacy Plan 03 key) and
    ``display_label`` (Plan 04 ``_history_card.html`` key) — same string,
    two names so we don't break either template.
    """
    out: list[dict[str, Any]] = []
    for j in reversed(jobs[-20:]):
        jid = j.get("id")
        if not jid:
            continue
        started = (j.get("started_at") or "")[:16].replace("T", " ")
        action_vi = _ACTION_VI.get(j.get("action", ""), j.get("action", ""))
        svc = j.get("service") or ""
        exit_code = j.get("exit_code")
        if exit_code is None:
            tail = ""
        else:
            tail = f" (exit {exit_code})"
        label = f"{started} — {action_vi} {svc}{tail}".strip()
        out.append({"id": jid, "label": label, "display_label": label})
    return out


def _resolve_ip_mac_context(config: dict[str, Any]) -> dict[str, Any]:
    """Compute the IP/MAC card context for ``GET /`` (Plan 04 D-15 / D-16 / M-7).

    Branches:
      - No interfaces detected → ``interfaces=[]``; the template renders the
        empty-state heading + body.
      - Saved IP/MAC empty → ``first_run=True``; pick first interface as
        the visible default; ``show_drift_banner=False``.
      - Saved IP/MAC match an interface exactly → normal state; no banners.
      - Saved IP/MAC drift (no interface matches) → ``show_drift_banner=True``;
        fall back to first interface so the admin can re-Save (M-7).
    """
    try:
        interfaces = get_all_network_interfaces()
    except OSError:
        interfaces = []

    game = (config.get("game") or {}) if isinstance(config, dict) else {}
    saved_ip = (game.get("server_ip") or "").strip()
    saved_mac = (game.get("server_mac") or "").strip()

    if not interfaces:
        return {
            "interfaces": [],
            "current_iface": {"ip": saved_ip, "mac": saved_mac},
            "selected": None,
            "first_run": False,
            "show_drift_banner": False,
        }

    if not saved_ip and not saved_mac:
        first = interfaces[0]
        return {
            "interfaces": interfaces,
            "current_iface": first,
            "selected": first["interface"],
            "first_run": True,
            "show_drift_banner": False,
        }

    match = next(
        (i for i in interfaces if i["ip"] == saved_ip and i["mac"] == saved_mac),
        None,
    )
    if match is not None:
        return {
            "interfaces": interfaces,
            "current_iface": match,
            "selected": match["interface"],
            "first_run": False,
            "show_drift_banner": False,
        }

    # M-7: saved values don't match — drift banner + fall back to interfaces[0].
    fallback = interfaces[0]
    return {
        "interfaces": interfaces,
        "current_iface": fallback,
        "selected": fallback["interface"],
        "first_run": False,
        "show_drift_banner": True,
    }


def _resolve_last_job() -> tuple[dict[str, Any] | None, bool, str]:
    """Return (job, attach_sse, log_text) for the dashboard render."""
    current = runner.current_job()
    if current is None:
        jobs = history.list_jobs()
        current = jobs[-1] if jobs else None
        if current is None:
            return None, False, ""
        attach = False
    else:
        attach = current.get("ended_at") is None

    log_text = _read_tail(log_stream.JOB_LOG_DIR / f"{current['id']}.log")
    return current, attach, log_text


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

    last_job, attach_sse, last_job_log = _resolve_last_job()
    action_running = runner.current_job() is not None
    history_options = _build_history_options(history.list_jobs())

    cfg = getattr(request.app.state, "config", {}) or {}
    ip_mac_ctx = _resolve_ip_mac_context(cfg)
    game_dir = (cfg.get("game") or {}).get("directory", "")

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
            "last_job": _annotate_job(last_job),
            "last_job_log": last_job_log,
            "attach_sse": attach_sse,
            "action_running": action_running,
            "history_options": history_options,
            # Plan 04 — IP/MAC card
            "interfaces": ip_mac_ctx["interfaces"],
            "current_iface": ip_mac_ctx["current_iface"],
            "selected": ip_mac_ctx["selected"],
            "first_run": ip_mac_ctx["first_run"],
            "show_drift_banner": ip_mac_ctx["show_drift_banner"],
            "show_reconfig_banner": False,
            "show_save_success_toast": False,
            # Plan 04 — history dropdown
            "history_jobs": history_options,
            # Phase-2 gap closure — game directory picker
            "current_dir": game_dir,
            "error": None,
            "saved": False,
            "suggestions": [],
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
    action_running = runner.current_job() is not None

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "_service_table.html",
        {
            "request": request,
            "t": TRANSLATION,
            "rows": rows,
            "poll_interval": poll_interval,
            "services_empty_heading": TRANSLATION["services_empty_heading"],
            "services_empty_body": TRANSLATION["services_empty_body"],
            "action_running": action_running,
        },
    )
