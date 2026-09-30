"""Процесс api-admin: /admin/*. Слушает только 127.0.0.1 (дизайн §9), доступ — по SSH-туннелю.

В отличие от api-public, у этого процесса есть доступ к Docker: он управляет нодой.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.admin.routers import auth as auth_router
from ocmanager.admin.routers import clients as clients_router
from ocmanager.admin.routers import devices as devices_router
from ocmanager.admin.routers import plans as plans_router
from ocmanager.admin.routers import subscriptions as subscriptions_router
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.errors import error_response, install_error_handlers
from ocmanager.core.logging import configure_logging
from ocmanager.core.redis import create_redis

# Защита от DNS-rebinding: браузер админа с открытым туннелем не должен давать
# чужому сайту ходить в админку под именем evil.example → 127.0.0.1.
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def request_hostname(host_header: str) -> str | None:
    """Имя хоста из заголовка Host без порта: `localhost:8080`, `[::1]:8080`."""
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


class HostGuard:
    """Чистый ASGI-middleware, а не BaseHTTPMiddleware: тот оборачивает ответ в собственные
    потоки и плохо переносит долгие стримы (SSE-логи), теряя отключение клиента."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            host = Headers(scope=scope).get("host", "")
            hostname = request_hostname(host)
            if hostname is None or hostname.lower() not in ALLOWED_HOSTS:
                response = error_response(400, "invalid_host", "invalid host")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)

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

    # Админка слушает только loopback, поэтому документация доступна и в проде.
    app = FastAPI(
        title="ocmanager admin api",
        lifespan=lifespan,
        openapi_url="/admin/openapi.json",
        docs_url="/admin/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    install_error_handlers(app)

    app.add_middleware(HostGuard)

    api = APIRouter(prefix="/admin")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(auth_router.router)
    api.include_router(clients_router.router)
    api.include_router(subscriptions_router.router)
    api.include_router(plans_router.router)
    api.include_router(devices_router.router)
    app.include_router(api)
    return app
