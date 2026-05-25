"""POST /api/services/start + POST /api/services/stop (DASH-03 / OPS-02).

Whitelists the optional ``?service=`` query param against
``ALLOWED_SERVICES`` BEFORE handing off to ``runner.run_job`` — defence-in-
depth against bash command injection (T-02-11). Returns:

  200 JSON ``{"job_id": "<32-hex>", "action": ..., "service": ...}`` on success.
  409 JSON ``{"error": "Đang có lệnh khác chạy..."}`` with header
      ``HX-Trigger: lock-busy`` so the client toast handler fires
      (DASH-05 / H-2).
  400 JSON ``{"error": "Service không hợp lệ"}`` for unknown service.
  302 redirect to ``/login?next=...`` when not authenticated.

Empty / missing ``?service=`` ⇒ full-stack action (``start_all`` / ``stop_all``).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from qlsv.i18n import TRANSLATION
from qlsv.jobs import runner
from qlsv.processes import ALLOWED_SERVICES
from qlsv.web.auth import require_auth

router = APIRouter()


def _auth_or_redirect(request: Request) -> tuple[str | None, Response | None]:
    try:
        return require_auth(request), None
    except HTTPException as exc:
        location = (exc.headers or {}).get("Location", "/login")
        return None, RedirectResponse(url=location, status_code=302)


def _service_param(request: Request) -> str | None:
    raw = request.query_params.get("service", "")
    raw = raw.strip()
    return raw or None


async def _dispatch(request: Request, base_action: str) -> Response:
    _, redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    service = _service_param(request)
    if service is None:
        action = "start_all" if base_action == "start" else "stop_all"
    else:
        if service not in ALLOWED_SERVICES:
            return JSONResponse(
                {"error": "Service không hợp lệ"},
                status_code=400,
            )
        action = base_action  # "start" | "stop"

    try:
        job_id = await runner.run_job(action, service, request.app.state.config)
    except runner.LockBusy:
        return JSONResponse(
            {"error": TRANSLATION["toast_lock_busy"]},
            status_code=409,
            headers={"HX-Trigger": "lock-busy"},
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse(
        {"job_id": job_id, "action": action, "service": service}
    )


@router.post("/api/services/start", include_in_schema=False)
async def services_start(request: Request) -> Response:
    return await _dispatch(request, "start")


@router.post("/api/services/stop", include_in_schema=False)
async def services_stop(request: Request) -> Response:
    return await _dispatch(request, "stop")
