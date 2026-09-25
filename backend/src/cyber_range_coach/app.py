from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, get_settings
from .database import Database
from .errors import install_error_handlers
from .routers import (
    command_practice,
    devices,
    learning,
    missions,
    studio,
    system,
    targets,
    terminal,
)
from .services.ai import AIBroker
from .services.command_practice import CommandCatalog
from .services.commands import SafeCommandRunner
from .services.curriculum import Curriculum
from .services.docker import DockerDiscovery
from .services.missions import MissionCatalog
from .services.preflight import PreflightService
from .services.relay import RelayManager
from .services.secrets import SecretProtectionError, build_secret_protector
from .services.ssh import RangeRunner, TerminalManager
from .services.wsl import WslKeepAlive

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    database = Database(settings)
    database.initialize()
    runner = SafeCommandRunner(settings.subprocess_timeout_seconds)
    docker = DockerDiscovery(runner)
    curriculum = Curriculum(settings.curriculum_dir)
    command_catalog = CommandCatalog(settings.command_catalog_dir)
    mission_catalog = MissionCatalog(settings.mission_catalog_dir, command_catalog)
    try:
        protector = build_secret_protector(
            settings.data_dir, settings.allow_insecure_dev_secrets or settings.testing
        )
    except SecretProtectionError:
        protector = None
    relays = RelayManager(
        settings.relay_bind_host,
        settings.relay_port_start,
        settings.relay_port_end,
        settings.relay_ttl_seconds,
    )
    wsl_keepalive = WslKeepAlive(runner, settings.subprocess_timeout_seconds)
    terminals = TerminalManager(settings, database, protector, wsl_keepalive.ensure)
    range_runner = RangeRunner(settings, database, protector, wsl_keepalive.ensure)
    ai = AIBroker(settings, runner)
    preflight = PreflightService(settings, database, runner, docker, range_runner, terminals)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await terminals.stop_all()
        await relays.stop_all()
        await wsl_keepalive.close()

    app = FastAPI(
        title="Cyber Range Coach",
        version=__version__,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.runner = runner
    app.state.docker = docker
    app.state.curriculum = curriculum
    app.state.command_catalog = command_catalog
    app.state.mission_catalog = mission_catalog
    app.state.protector = protector
    app.state.relays = relays
    app.state.terminals = terminals
    app.state.range_runner = range_runner
    app.state.wsl_keepalive = wsl_keepalive
    app.state.ai = ai
    app.state.preflight = preflight
    app.state.run_start_lock = asyncio.Lock()

    install_error_handlers(app)

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "database": database.integrity_check()}

    app.include_router(system.router)
    app.include_router(targets.router)
    app.include_router(learning.router)
    app.include_router(command_practice.router)
    app.include_router(missions.router)
    app.include_router(devices.router)
    app.include_router(studio.router)
    app.include_router(terminal.router)

    dist = settings.frontend_dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    if (dist / "index.html").is_file():

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str) -> FileResponse:
            requested = (dist / full_path).resolve()
            try:
                requested.relative_to(dist)
            except ValueError:
                return FileResponse(dist / "index.html")
            if requested.is_file() and not requested.name.startswith("."):
                return FileResponse(requested)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def frontend_missing() -> JSONResponse:
            return JSONResponse(
                {
                    "status": "backend-ready",
                    "message": "Нужен frontend development server или production build.",
                }
            )

    return app
