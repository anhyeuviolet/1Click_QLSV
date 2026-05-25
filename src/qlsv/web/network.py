"""POST /api/network/save + GET /api/network/preview (Plan 02-04 D-15 / D-16 / M-7).

Both routes are auth-gated. The form / query parameter ``iface`` must match
an interface name returned by ``qlsv.net.get_all_network_interfaces`` — strict
equality, no globbing, no path traversal (T-02-20 / T-02-21).

On save, ``config.game.server_ip`` and ``config.game.server_mac`` are written
atomically with mode 0600 via ``qlsv.config.save_config`` (which delegates to
``qlsv._atomic.write_json``, H-6). If any service is alive at save time
(``probe_all`` returns any True), the response embeds the amber
``ip_mac_reconfig_banner`` so the admin knows to bounce services to pick up
the new IP/MAC via ``gameconfigs/*.cfg`` sync at start time.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from qlsv import config as config_module
from qlsv.i18n import TRANSLATION
from qlsv.net import get_all_network_interfaces
from qlsv.processes import probe_all
from qlsv.web.auth import require_auth

router = APIRouter()


def _auth_or_redirect(request: Request) -> Response | None:
    try:
        require_auth(request)
        return None
    except HTTPException as exc:
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=302)


def _render_card(
    request: Request,
    *,
    interfaces: list[dict],
    current_iface: dict,
    selected: str | None,
    show_reconfig_banner: bool = False,
    show_drift_banner: bool = False,
    first_run: bool = False,
    show_save_success_toast: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "_ip_mac_card.html",
        {
            "request": request,
            "t": TRANSLATION,
            "interfaces": interfaces,
            "current_iface": current_iface,
            "selected": selected,
            "first_run": first_run,
            "show_reconfig_banner": show_reconfig_banner,
            "show_drift_banner": show_drift_banner,
            "show_save_success_toast": show_save_success_toast,
        },
    )
    if extra_headers:
        for k, v in extra_headers.items():
            response.headers[k] = v
    return response


@router.get("/api/network/preview", include_in_schema=False)
def network_preview(request: Request) -> Response:
    """Render the IP/MAC card for ``iface`` — used by the dropdown HTMX swap."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    iface = request.query_params.get("iface", "")
    interfaces = get_all_network_interfaces()
    match = next((i for i in interfaces if i["interface"] == iface), None)
    if match is None:
        return JSONResponse(
            {"error": TRANSLATION["ip_mac_iface_not_found"]},
            status_code=400,
        )

    return _render_card(
        request,
        interfaces=interfaces,
        current_iface=match,
        selected=iface,
        # Preview is a transient state — never re-show banners.
    )


@router.post("/api/network/save", include_in_schema=False)
def network_save(request: Request, iface: str = Form(...)) -> Response:
    """Persist ``game.server_ip`` / ``game.server_mac`` atomically."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    interfaces = get_all_network_interfaces()
    match = next((i for i in interfaces if i["interface"] == iface), None)
    if match is None:
        return JSONResponse(
            {"error": TRANSLATION["ip_mac_iface_not_found"]},
            status_code=400,
        )

    cfg = request.app.state.config
    game = cfg.setdefault("game", {})
    game["server_ip"] = match["ip"]
    game["server_mac"] = match["mac"]

    # Atomic write 0600 via qlsv._atomic.write_json (H-6 / Phase 1 WR-01).
    config_module.save_config(cfg)

    # If any service is currently alive the admin needs to bounce them so
    # gameconfigs/*.cfg gets re-rendered with the new SERVER_IP/SERVER_MAC.
    try:
        show_reconfig_banner = any(probe_all().values())
    except OSError:
        # pgrep not available in test environments — fall back to "no banner".
        show_reconfig_banner = False

    return _render_card(
        request,
        interfaces=interfaces,
        current_iface=match,
        selected=iface,
        show_reconfig_banner=show_reconfig_banner,
        show_save_success_toast=True,
        extra_headers={"HX-Trigger": "ip-mac-saved"},
    )
