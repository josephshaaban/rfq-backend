from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.exceptions import DocumentTooLargeError, DocumentTypeNotSupportedError

from app.logger import configure_logging, get_logger
from app.settings import get_settings
from app.db.session import init_engine
from app.db.init_db import create_tables
from app.api.v1.endpoints import health, documents, alerts, monitor
from app.api.v1.ws import events as ws_events
from app.workers.gdelt_monitor import GdeltMonitor

logger = get_logger(__name__)
settings = get_settings()

_monitor: GdeltMonitor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _monitor

    configure_logging()
    logger.info("Starting up", extra={"env": settings.app_env})

    # Database
    engine = await init_engine(settings.sqlite_db_path)
    await create_tables(engine)
    app.state.engine = engine

    # Background GDELT poller
    _monitor = GdeltMonitor()
    await _monitor.start()

    logger.info("Startup complete — listening on port %s", settings.port)
    yield

    # Shutdown
    logger.info("Shutting down")
    if _monitor:
        await _monitor.stop()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="RFQ Backend Platform",
        description="Document ingestion, AI extraction, WebSocket events, and supply-chain monitoring.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Set CORS_ORIGINS env var (comma-separated) before any shared deployment.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DocumentTooLargeError)
    async def document_too_large_handler(request: Request, exc: DocumentTooLargeError) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"detail": f"File exceeds maximum size of {exc.max_mb} MB", "type": "payload_too_large"},
        )

    @app.exception_handler(DocumentTypeNotSupportedError)
    async def document_type_not_supported_handler(request: Request, exc: DocumentTypeNotSupportedError) -> JSONResponse:
        return JSONResponse(
            status_code=415,
            content={"detail": f"Content type '{exc.content_type}' is not supported", "type": "unsupported_media_type"},
        )

    # REST routes
    app.include_router(health.router, tags=["health"])
    app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
    app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
    app.include_router(monitor.router, prefix="/api/v1", tags=["monitor"])

    # WebSocket
    app.include_router(ws_events.router, prefix="/api/v1", tags=["websocket"])

    # Serve WS test page
    app.mount("/ws-test", StaticFiles(directory="assets/static", html=True), name="ws-test")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        logger.exception("Unhandled exception", extra={"path": str(request.url)})
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": "internal_error"},
        )

    return app


app = create_app()
