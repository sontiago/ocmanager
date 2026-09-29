from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from conftest import MakeClient, MakeDevice, MakeSubscription
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps.public_api import create_app
from ocmanager.core.config import Settings
from ocmanager.nodes.models import SessionLog, TrafficSample
from ocmanager.subscriptions import service as subscriptions

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
GOOD: dict[str, Any] = {
    "username": "c1-d1",
    "session_id": "7",
    "bytes_in": 1500,
    "bytes_out": 2500,
    "duration_sec": 600,
    "remote_ip": "203.0.113.9",
}


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def valid(settings: Settings) -> str:
    return settings.internal_token.get_secret_value()


async def post(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    body: object = GOOD,
    *,
    token: str | None = None,
    host: str = "10.0.0.5",
) -> Response:
    app = create_app(settings)
    app.state.sessionmaker = sessionmaker  # lifespan в тесте не запускается
    transport = ASGITransport(app=app, client=(host, 40000))
    headers = {"X-Internal-Token": token} if token is not None else {}
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post("/internal/session-end", json=body, headers=headers)


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_valid_report_is_recorded(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    r = await post(settings, sessionmaker, token=valid(settings))
    assert (r.status_code, r.content) == (204, b"")
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert (log.username, log.bytes_in, log.bytes_out) == ("c1-d1", 1500, 2500)
    assert (log.final_received, log.client_ip) == (True, "203.0.113.9")
    sample = await session.scalar(select(TrafficSample))
    assert sample is not None
    assert (sample.bytes_in_delta, sample.bytes_out_delta) == (1500, 2500)


async def test_repeat_is_acknowledged_but_counted_once(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    for _ in range(2):
        assert (await post(settings, sessionmaker, token=valid(settings))).status_code == 204
    assert await count(session, TrafficSample) == 1
    assert await count(session, SessionLog) == 1


@pytest.mark.parametrize("token", [None, "", "wrong", "x" * 200, "dev-internal-token"])
async def test_missing_or_wrong_token_is_401(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str | None,
) -> None:
    r = await post(settings, sessionmaker, token=token)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert await count(session, SessionLog) == 0


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "2606:4700::1111"])
async def test_public_address_is_refused_even_with_the_right_token(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    host: str,
) -> None:
    r = await post(settings, sessionmaker, token=valid(settings), host=host)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    assert await count(session, SessionLog) == 0


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "172.17.0.1", "192.168.65.1", "::1"])
async def test_private_addresses_are_accepted(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, host: str
) -> None:
    assert (await post(settings, sessionmaker, token=valid(settings), host=host)).status_code == 204


@pytest.mark.parametrize(
    "bad",
    [
        {"username": "root"},
        {"username": "c1-d1\n"},
        {"username": "../etc/passwd"},
        {"username": "c01-d1"},
        {"username": ""},
        {"session_id": "abc"},
        {"session_id": ""},
        {"session_id": "1" * 21},
        {"bytes_in": -1},
        {"bytes_out": "many"},
        {"duration_sec": -5},
        {"bytes_in": 2**63},
        {"remote_ip": "not-an-ip"},
        {"extra": 1},
    ],
)
async def test_bad_body_is_422(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    bad: dict[str, Any],
) -> None:
    r = await post(settings, sessionmaker, GOOD | bad, token=valid(settings))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert await count(session, SessionLog) == 0


@pytest.mark.parametrize("field", ["username", "session_id", "bytes_in", "bytes_out"])
async def test_missing_field_is_422(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, field: str
) -> None:
    body = {k: v for k, v in GOOD.items() if k != field}
    assert (await post(settings, sessionmaker, body, token=valid(settings))).status_code == 422


async def test_not_json_is_422(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    r = await post(settings, sessionmaker, "just text", token=valid(settings))
    assert r.status_code == 422


@pytest.mark.parametrize("ip", ["", None, "2001:db8::1"])
async def test_remote_ip_may_be_empty_or_ipv6(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    ip: str | None,
) -> None:
    """disconnect.sh шлёт пустую строку, если ocserv не назвал адрес."""
    r = await post(settings, sessionmaker, GOOD | {"remote_ip": ip}, token=valid(settings))
    assert r.status_code == 204
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert log.client_ip == (ip or None)


async def test_report_updates_the_clients_traffic_usage(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    """Слепая сессия (между опросами) тоже должна попасть в расход подписки."""
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    device = await make_device(client)
    await session.commit()
    body = GOOD | {"username": device.ocserv_username}
    assert (await post(settings, sessionmaker, body, token=valid(settings))).status_code == 204
    sub = await subscriptions.get_subscription(session, client.id)
    assert sub is not None
    await session.refresh(sub)
    assert sub.traffic_used_bytes == 4000
