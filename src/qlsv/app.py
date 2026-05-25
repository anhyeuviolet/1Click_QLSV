"""FastAPI app factory.

Wires SessionMiddleware (signed cookies per D-05/D-06/D-07/D-08), the Jinja2
template environment, the `/static` mount, and the `auth` + `dashboard` routers.

Contract: `create_app(config: dict) -> FastAPI`. `config` is attached to
`app.state.config`; templates are attached to `app.state.templates`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from qlsv import __version__
from qlsv.config import ConfigError
from qlsv.web import auth, dashboard
from qlsv.web import jobs as web_jobs
from qlsv.web import services as web_services

_WEB_DIR = Path(__file__).parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


def create_app(config: dict) -> FastAPI:
    """Build the FastAPI app and attach `config` to `app.state.config`."""
    app = FastAPI(
        title="1Click QLSV",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = config

    # Jinja2 environment (autoescape on by default).
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    # Static assets (CSS + vendored htmx).
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Session cookie contract — D-05/D-06/D-07/D-08, locked in 01-02-PLAN <interfaces>.
    web_cfg = config.get("web", {}) or {}
    session_cfg = config.get("session", {}) or {}
    secret_key = session_cfg.get("secret_key")
    if not secret_key:
        # Fail-fast: config loader should already have caught this, but be defensive.
        raise ConfigError("Chưa cấu hình session.secret_key")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="session",
        https_only=bool(web_cfg.get("cookie_secure", False)),
        same_site="strict",
        max_age=int(web_cfg.get("idle_timeout_seconds", 2592000)),
    )

    # Framework-level health endpoint (Phase 4 monitor consumes this).
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Auth router: GET/POST /login, POST /logout.
    app.include_router(auth.router)
    # Dashboard router: GET /.
    app.include_router(dashboard.router)
    # Plan 02-03 routers: Start/Stop + job log / live-tail.
    # IMPORTANT: uvicorn MUST run with ``--workers 1`` — the job runner's
    # asyncio.Lock is process-local, so multiple workers would each
    # accept concurrent jobs and race on jx.sh. The Phase 4 systemd unit
    # pins this.
    app.include_router(web_services.router)
    app.include_router(web_jobs.router)

    return app
