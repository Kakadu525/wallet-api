import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.wallets import router as wallets_router
from app.config import settings
from app.database import engine
from app.metrics import PrometheusMiddleware, metrics_endpoint

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("wallet-api")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s %s", settings.app_name, settings.app_version)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="REST API для работы с балансом кошельков пользователей",
    version=settings.app_version,
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Idempotent-Replay", "Retry-After"],
    )

if settings.metrics_enabled:
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)

app.include_router(auth_router)
app.include_router(wallets_router)


@app.get("/health", tags=["health"], summary="Живость и доступность БД")
async def health_check() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})


if settings.serve_ui and STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

else:

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")
