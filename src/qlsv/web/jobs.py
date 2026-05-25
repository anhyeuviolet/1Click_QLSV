"""GET /api/jobs/log + /api/jobs/live-tail (DASH-04 / H-3 / H-4 / T-02-12).

``/api/jobs/log`` is the unified endpoint:

  ?job_id=<32-hex>&mode=static   → HTML fragment of the tail-pane with the
                                   last 1 MB of log content, NO SSE attach.
  ?job_id=<32-hex>&mode=stream   → text/event-stream of live tail frames
                                   (terminates when sidecar <id>.exit appears).
  ?job_id=                       → "live" mode (H-3): HTML fragment that
                                   reattaches SSE to whichever job is
                                   currently running (or empty state).

``/api/jobs/live-tail`` is the dedicated SSE re-attach hook used when the
history dropdown switches back to "— live —"; it always returns the full
``<section id="tail-pane">`` wrapper so HTMX outerHTML swap rebuilds the
DOM node (the SSE listener on the previous node dies with it).

Job-id alphabet (``^[0-9a-f]{32}$``) is enforced at every entry point —
defends ``JOB_LOG_DIR / job_id`` against path traversal (T-02-12).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from qlsv.i18n import TRANSLATION
from qlsv.jobs import history, log_stream, runner
from qlsv.web.auth import require_auth

router = APIRouter()

# Static-mode tail size cap — never read more than this from disk for the
# initial pre-stream paint (keeps the HTTP response bounded even if a single
# job logged hundreds of MB).
_STATIC_TAIL_BYTES = 1 * 1024 * 1024  # 1 MiB
_LIVE_REATTACH_BYTES = 64 * 1024  # 64 KiB


_ACTION_VI = {
    "start_all": "Start all",
    "stop_all": "Stop all",
    "start": "Start",
    "stop": "Stop",
}


def _auth_or_redirect(request: Request) -> Response | None:
    try:
        require_auth(request)
        return None
    except HTTPException as exc:
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=302)


def _read_tail(path: Path, max_bytes: int) -> str:
    """Read at most ``max_bytes`` from the tail of ``path``. Missing → ''."""
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
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _annotate_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """Attach an ``action_vi`` label so the template doesn't need a filter."""
    if not job:
        return None
    enriched = dict(job)
    enriched["action_vi"] = _ACTION_VI.get(job.get("action", ""), job.get("action", ""))
    return enriched


def _render_tail_pane(
    request: Request,
    job: dict[str, Any] | None,
    log_text: str,
    attach_sse: bool,
) -> Response:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "_tail_pane.html",
        {
            "request": request,
            "t": TRANSLATION,
            "last_job": _annotate_job(job),
            "last_job_log": log_text,
            "attach_sse": attach_sse,
        },
    )


@router.get("/api/jobs/log", include_in_schema=False)
async def jobs_log(request: Request) -> Response:
    """Static log fragment OR SSE stream, gated by ``mode`` query."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    job_id = request.query_params.get("job_id", "")
    mode = request.query_params.get("mode", "static")

    # H-3: empty job_id ⇒ "live" pane (re-attach to whatever is running).
    if job_id == "":
        current = runner.current_job()
        if current is None:
            # Fall back to the most-recent completed job, but DON'T attach SSE
            # (it has already ended).
            jobs = history.list_jobs()
            current = jobs[-1] if jobs else None
            attach = False
            log_text = ""
        else:
            attach = True
            log_text = _read_tail(
                log_stream.JOB_LOG_DIR / f"{current['id']}.log",
                _LIVE_REATTACH_BYTES,
            )
        return _render_tail_pane(request, current, log_text, attach)

    if not log_stream.validate_job_id(job_id):
        return JSONResponse(
            {"error": TRANSLATION["tail_pane_job_pruned"]},
            status_code=400,
        )

    log_path = log_stream.JOB_LOG_DIR / f"{job_id}.log"

    if mode == "stream":
        # SSE — the generator itself re-validates job_id (ValueError-safe).
        return StreamingResponse(
            log_stream.tail_file(job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # mode == "static" — render fragment with the tail content baked in.
    if not log_path.exists():
        return JSONResponse(
            {"error": TRANSLATION["tail_pane_job_pruned"]},
            status_code=404,
        )

    job = history.get_job(job_id)
    log_text = _read_tail(log_path, _STATIC_TAIL_BYTES)
    return _render_tail_pane(request, job, log_text, attach_sse=False)


@router.get("/api/jobs/live-tail", include_in_schema=False)
async def jobs_live_tail(request: Request) -> Response:
    """Re-attach the tail-pane to the current (or most-recent) job."""
    redirect = _auth_or_redirect(request)
    if redirect is not None:
        return redirect

    current = runner.current_job()
    if current is None:
        jobs = history.list_jobs()
        current = jobs[-1] if jobs else None
        attach = False
    else:
        attach = current.get("ended_at") is None

    log_text = ""
    if current and current.get("id"):
        log_text = _read_tail(
            log_stream.JOB_LOG_DIR / f"{current['id']}.log",
            _LIVE_REATTACH_BYTES,
        )

    return _render_tail_pane(request, current, log_text, attach)
