"""Публичный процесс: /api/tma/*, /api/health, /webhooks/*, /internal/*.

Не имеет доступа к Docker (Global Constraints): всё, что трогает ноду,
делают worker и api-admin.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.apps import internal
from ocmanager.billing.router import router as webhooks_router
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.errors import install_error_handlers
from ocmanager.core.logging import configure_logging
from ocmanager.core.redis import create_redis
from ocmanager.tma.router import router as tma_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)
    dev = settings.env != "production"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.redis = await create_redis(settings.redis_url)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="ocmanager public api",
        lifespan=lifespan,
        openapi_url="/api/openapi.json" if dev else None,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
    )
    app.state.settings = settings
    install_error_handlers(app)

    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(tma_router)
    app.include_router(api)
    app.include_router(webhooks_router)
    app.include_router(internal.router)
    return app
