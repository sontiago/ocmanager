import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ocmanager.apps.admin_api import create_app, request_hostname
from ocmanager.core.config import Settings


async def get(settings: Settings, url: str, *, host: str = "localhost:8080") -> tuple[int, object]:
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.get(url, headers={"Host": host})
        return r.status_code, r.json()


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:8080", "127.0.0.1:8080", "[::1]:8080", "LOCALHOST:8080"]
)
async def test_loopback_hosts_are_served(settings: Settings, host: str) -> None:
    assert await get(settings, "/admin/health", host=host) == (200, {"status": "ok"})


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:8080",
        "localhost.evil.example",
        "localhost@evil.example",
        "127.0.0.1.evil.example",
        "10.0.0.5:8080",
        "",
    ],
)
async def test_foreign_hosts_are_refused(settings: Settings, host: str) -> None:
    status, body = await get(settings, "/admin/health", host=host)
    assert status == 400
    assert body == {"error": {"code": "invalid_host", "message": "invalid host"}}


def test_hostname_parsing() -> None:
    assert request_hostname("[::1]:8080") == "::1"
    assert request_hostname("localhost:8080") == "localhost"
    assert request_hostname("[::1") is None


async def test_unknown_path_uses_error_envelope(settings: Settings) -> None:
    assert await get(settings, "/admin/nope") == (
        404,
        {"error": {"code": "not_found", "message": "not_found"}},
    )


async def test_openapi_is_served(settings: Settings) -> None:
    status, body = await get(settings, "/admin/openapi.json")
    assert status == 200
    assert isinstance(body, dict)
    assert "/admin/health" in body["paths"]


async def test_lifespan_opens_db_and_redis(settings: Settings, db_engine: object) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.sessionmaker() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        assert await app.state.redis.ping()
