from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.versioning import is_compatible

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    setup_logging()
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.version, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=lifespan)
    install_error_handlers(app)
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["X-Server-Version", "X-Min-Client-Version"])

    @app.middleware("http")
    async def version_headers(request: Request, call_next):
        client = request.headers.get("X-Client-Version")
        if client and not is_compatible(client, s.min_client_version):
            return JSONResponse(
                {"error": {"code": "CLIENT_UPDATE_REQUIRED", "message": "Client version too old",
                           "details": {"client": client, "min_client_version": s.min_client_version,
                                       "server": s.version}}},
                status_code=426, headers={"X-Server-Version": s.version, "X-Min-Client-Version": s.min_client_version})
        response = await call_next(request)
        response.headers["X-Server-Version"] = s.version
        response.headers["X-Min-Client-Version"] = s.min_client_version
        return response

    from app.auth.router import router as auth_router
    from app.modules.org.router import router as org_router
    from app.modules.system.router import router as system_router

    for r in (auth_router, org_router, system_router):
        app.include_router(r, prefix=API_PREFIX)
    _include_optional(app)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Background services. Not started by tests that use TestClient without `with`."""
    import logging

    s = get_settings()
    started = []
    if s.background_jobs:
        from app.ops.events import hub
        hub.start()
        started.append(hub.stop)
        from app.ops.scheduler import start_scheduler
        sched = start_scheduler()
        started.append(lambda: sched.shutdown(wait=False))
        if not s.is_online and s.discovery_enabled:
            from app.ops.discovery import MdnsAdvertiser, UdpResponder
            for svc in (UdpResponder(), MdnsAdvertiser()):
                try:
                    svc.start()
                    started.append(svc.stop)
                except Exception as exc:  # discovery is a convenience; never block startup
                    logging.getLogger("mytech").warning("discovery %s not started: %s", type(svc).__name__, exc)
    yield
    for stop in reversed(started):
        try:
            stop()
        except Exception:
            pass


def _include_optional(app: FastAPI) -> None:
    """Routers of later modules register themselves here."""
    import importlib

    for mod in MODULE_ROUTERS:
        app.include_router(importlib.import_module(mod).router, prefix=API_PREFIX)


MODULE_ROUTERS: list[str] = [
    "app.modules.org.settings",
    "app.modules.library.router",
    "app.modules.crm.router",
    "app.modules.sales.router",
    "app.modules.production.router",
    "app.modules.inventory.router",
    "app.modules.purchasing.router",
    "app.modules.treasury.router",
    "app.modules.privacy.router",
]

app = create_app()
