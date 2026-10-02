from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import structlog
from conftest import MakeClient, TmaHeaders
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.core.errors import install_error_handlers
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client
from ocmanager.tma.deps import CurrentClient
from ocmanager.tma.testing import make_init_data

USER = {"id": 4242, "first_name": "Anna", "username": "anna", "language_code": "en"}


def init_data(settings: Settings, *, age_s: int = 0, **user: Any) -> str:
    return make_init_data(
        settings.bot_token.get_secret_value(),
        user=USER | user,
        auth_date=int(utcnow().timestamp()) - age_s,
    )


def tma(raw: str) -> dict[str, str]:
    return {"Authorization": f"tma {raw}"}


@pytest.fixture
async def http(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """Крошечное приложение с одним маршрутом: зависимость проверяется без роутера TMA."""
    app = FastAPI()
    app.state.settings = settings
    app.state.sessionmaker = sessionmaker
    install_error_handlers(app)

    @app.get("/whoami")
    async def whoami(ctx: CurrentClient) -> dict[str, Any]:
        return {"id": ctx.client.id, "lang": ctx.lang, "actor": ctx.actor.id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client


async def error_code(r: Any) -> str:
    return str(r.json()["error"]["code"])


@pytest.mark.parametrize(
    "header",
    [None, "", "tma", "tma ", "Bearer abc", "Basic abc", "tma-abc def"],
)
async def test_no_usable_authorization_is_401(http: AsyncClient, header: str | None) -> None:
    r = await http.get("/whoami", headers={} if header is None else {"Authorization": header})
    assert (r.status_code, await error_code(r)) == (401, "unauthorized")


async def test_the_first_request_creates_the_client_and_audits_it_once(
    http: AsyncClient, settings: Settings, session: AsyncSession
) -> None:
    raw = init_data(settings)
    first = await http.get("/whoami", headers=tma(raw))
    second = await http.get("/whoami", headers=tma(raw))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["lang"] == "en"
    assert await session.scalar(select(func.count()).select_from(Client)) == 1
    actions = list(await session.scalars(select(AuditLog.action)))
    assert actions == ["client.create"]


async def test_the_scheme_name_is_case_insensitive(http: AsyncClient, settings: Settings) -> None:
    r = await http.get("/whoami", headers={"Authorization": f"TMA {init_data(settings)}"})
    assert r.status_code == 200


async def test_a_changed_name_or_language_is_picked_up(
    http: AsyncClient, settings: Settings, session: AsyncSession
) -> None:
    await http.get("/whoami", headers=tma(init_data(settings)))
    r = await http.get(
        "/whoami", headers=tma(init_data(settings, first_name="Anya", language_code="ru"))
    )
    assert r.json()["lang"] == "ru"
    client = await subscriptions.find_client_by_telegram_id(session, 4242)
    assert client is not None
    await session.refresh(client)
    assert (client.first_name, client.lang) == ("Anya", "ru")


async def test_a_blocked_client_still_passes_so_that_the_app_can_say_so(
    http: AsyncClient, settings: Settings, session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client(telegram_id=4242, first_name="Anna", username="anna")
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    r = await http.get("/whoami", headers=tma(init_data(settings)))
    assert (r.status_code, r.json()["id"]) == (200, client.id)


async def test_an_expired_string_has_its_own_code(http: AsyncClient, settings: Settings) -> None:
    old = init_data(
        settings, age_s=int(timedelta(seconds=settings.tma_initdata_ttl_s).total_seconds()) + 60
    )
    r = await http.get("/whoami", headers=tma(old))
    assert (r.status_code, await error_code(r)) == (401, "initdata_expired")


async def test_a_forged_string_creates_nobody(
    http: AsyncClient, settings: Settings, session: AsyncSession
) -> None:
    forged = init_data(settings).replace("Anna", "Evil")
    r = await http.get("/whoami", headers=tma(forged))
    assert r.status_code == 401
    assert await session.scalar(select(func.count()).select_from(Client)) == 0


async def test_the_init_data_reaches_neither_the_response_nor_the_logs(
    http: AsyncClient, settings: Settings
) -> None:
    raw = init_data(settings) + "0"  # подпись испорчена
    with structlog.testing.capture_logs() as logs:
        r = await http.get("/whoami", headers=tma(raw))
    assert r.status_code == 401
    assert raw not in r.text
    assert raw not in repr(logs)


async def test_a_rejected_request_leaves_the_reason_in_the_log_but_not_the_data(
    public_client: AsyncClient, tma_headers: TmaHeaders
) -> None:
    secret = tma_headers()["Authorization"]
    with structlog.testing.capture_logs() as logs:
        await public_client.get("/api/tma/me")  # заголовка нет
        await public_client.get("/api/tma/me", headers={"Authorization": secret[:-4] + "0000"})
    reasons = [e["reason"] for e in logs if e["event"] == "tma_auth_rejected"]
    assert reasons == ["no initData in Authorization", "bad hash"]
    assert secret[10:60] not in repr(logs)  # сама initData в лог не попадает
