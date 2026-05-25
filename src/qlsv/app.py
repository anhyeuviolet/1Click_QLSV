"""FastAPI app factory.

Plan 01 wires only the placeholder dashboard router and the /healthz smoke
endpoint. Plan 03 will add SessionMiddleware and the auth router against this
same factory — the signature `create_app(config: dict) -> FastAPI` is the
contract Plan 03 builds on.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from qlsv import __version__
from qlsv.web import dashboard


def create_app(config: dict) -> FastAPI:
    """Build the FastAPI app and attach `config` to `app.state.config`."""
    app = FastAPI(
        title="1Click QLSV",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = config

    # Framework-level health endpoint (Phase 4 monitor consumes this).
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Placeholder dashboard router (Plan 03 swaps with auth + Jinja).
    app.include_router(dashboard.router)

    return app
