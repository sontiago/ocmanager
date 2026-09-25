from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ocmanager.apps.public_api import create_app
from ocmanager.core.config import Settings


async def get(settings: Settings, url: str) -> tuple[int, object]:
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get(url)
        return r.status_code, r.json()


async def test_health(settings: Settings) -> None:
    assert await get(settings, "/api/health") == (200, {"status": "ok"})


async def test_unknown_path_uses_error_envelope(settings: Settings) -> None:
    assert await get(settings, "/api/nope") == (
        404,
        {"error": {"code": "not_found", "message": "not_found"}},
    )


async def test_openapi_hidden_in_production(settings: Settings) -> None:
    prod = settings.model_copy(update={"env": "production"})
    status, _ = await get(prod, "/api/openapi.json")
    assert status == 404


async def test_lifespan_opens_db_and_redis(settings: Settings, db_engine: object) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.sessionmaker() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        assert await app.state.redis.ping()
