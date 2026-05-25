"""POST /api/network/save + GET /api/network/preview (Plan 02-04 D-15 / D-16 / M-7).
Plus POST /api/game/directory (post-Phase-2 UX-parity gap — original
``2.3.2/app.py:684`` had a Tkinter folder picker we missed).

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

from pathlib import Path

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


# --------------------------------------------------------------------------- #
# Game directory selector — restores UX parity with 2.3.2/app.py:684          #
# (Tkinter filedialog.askdirectory). Phase-2 gap-closure.                     #
# --------------------------------------------------------------------------- #


def _validate_game_dir(raw: str) -> tuple[Path | None, str | None]:
    """Return (resolved_path, error_message).

    Accepted iff: absolute, exists, is a directory, contains both
    ``gateway/`` and ``server1/`` (the two subtrees jx.sh actually cds into).
    No symlink-escape: the resolved path itself does not need to live under
    any prefix — admins legitimately keep game trees under /home/* or /opt/* —
    but it MUST be a real directory after ``resolve(strict=True)``.
    """
    raw = raw.strip()
    if not raw:
        return None, TRANSLATION["game_dir_error_empty"]
    if not raw.startswith("/"):
        return None, TRANSLATION["game_dir_error_relative"]
    try:
        p = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, TRANSLATION["game_dir_error_missing"]
    if not p.is_dir():
        return None, TRANSLATION["game_dir_error_not_dir"]
    if not (p / "gateway").is_dir() or not (p / "server1").is_dir():
        return None, TRANSLATION["game_dir_error_not_jx_tree"]
    return p, None


def _render_game_dir_card(
    request: Request,
    *,
    current: str,
    error: str | None = None,
    saved: bool = False,
    suggestions: list[str] | None = None,
) -> Response:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "_game_dir_card.html",
        {
            "request": request,
            "t": TRANSLATION,
            "current_dir": current,
            "error": error,
            "saved": saved,
            "suggestions": suggestions or [],
        },
    )


def _scan_jx_trees(roots: tuple[str, ...] = ("/home", "/opt")) -> list[str]:
    """Find directories under ``roots`` that look like a JX1 server tree.

    A candidate must contain both ``gateway/`` and ``server1/``. Bounded
    scan: only direct children of each root, never recursive. Silent on
    permission / missing-root errors.
    """
    found: list[str] = []
    for root in roots:
        try:
            entries = list(Path(root).iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir() and (entry / "gateway").is_dir() and (entry / "server1").is_dir():
                    found.append(str(entry))
            except OSError:
                continue
    return sorted(set(found))


@router.get("/api/game/directory", include_in_schema=False)
def game_dir_preview(request: Request) -> Response:
    """Render the current directory card with scan suggestions."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    cfg = request.app.state.config
    current = (cfg.get("game") or {}).get("directory", "")
    return _render_game_dir_card(
        request, current=current, suggestions=_scan_jx_trees()
    )


@router.post("/api/game/directory", include_in_schema=False)
def game_dir_save(request: Request, directory: str = Form(...)) -> Response:
    """Validate + persist ``game.directory``."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    resolved, err = _validate_game_dir(directory)
    if err is not None:
        return _render_game_dir_card(
            request,
            current=directory,
            error=err,
            suggestions=_scan_jx_trees(),
        )

    cfg = request.app.state.config
    game = cfg.setdefault("game", {})
    game["directory"] = str(resolved)
    config_module.save_config(cfg)

    return _render_game_dir_card(
        request, current=str(resolved), saved=True, suggestions=_scan_jx_trees()
    )
