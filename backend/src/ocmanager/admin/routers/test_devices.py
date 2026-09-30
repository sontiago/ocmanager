import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakeDevice, MakeSubscription
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.flows import handlers
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import SessionLog
from ocmanager.provisioning.models import Revocation


@pytest.fixture
def fake(settings: Settings) -> Iterator[FakeNodeDriver]:
    handlers.register(settings)
    driver = FakeNodeDriver(allowlist=set())
    with registry.override_driver(driver):
        yield driver


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/devices"),
        ("POST", "/admin/devices/1/revoke"),
        ("GET", "/admin/devices/1/sessions"),
    ],
)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


async def test_revoke_needs_the_csrf_token(admin_client: AsyncClient) -> None:
    del admin_client.headers["X-CSRF-Token"]
    r = await admin_client.post("/admin/devices/1/revoke", json={"reason": "x"})
    assert r.status_code == 403


async def ids(admin_client: AsyncClient, **params: str | int) -> list[int]:
    r = await admin_client.get("/admin/devices", params=params)
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()["items"]]


async def test_search_by_username_and_by_owner_telegram_id(
    admin_client: AsyncClient, make_client: MakeClient, make_device: MakeDevice
) -> None:
    anna = await make_client(telegram_id=111)
    boris = await make_client(telegram_id=222)
    d1 = await make_device(anna, seq=1)
    d2 = await make_device(boris, seq=1)
    assert await ids(admin_client, q=d1.ocserv_username) == [d1.id]
    assert await ids(admin_client, q="222") == [d2.id]
    assert await ids(admin_client, q="dev1") == [d2.id, d1.id]  # название устройства
    assert await ids(admin_client, q="%") == []
    assert await ids(admin_client, q="9" * 40) == []


async def test_platform_and_revoked_filters_and_pagination(
    admin_client: AsyncClient, make_client: MakeClient, make_device: MakeDevice
) -> None:
    client = await make_client()
    live = await make_device(client, seq=1)
    dead = await make_device(client, seq=2, revoked=True)
    assert await ids(admin_client, revoked="false") == [live.id]
    assert await ids(admin_client, revoked="true") == [dead.id]
    assert await ids(admin_client, platform="linux") == [dead.id, live.id]
    assert await ids(admin_client, platform="ios") == []
    assert (await admin_client.get("/admin/devices?platform=beos")).status_code == 422
    page = (await admin_client.get("/admin/devices?limit=1&offset=1")).json()
    assert (page["total"], [d["id"] for d in page["items"]]) == (2, [live.id])


async def test_rows_name_the_owner(
    admin_client: AsyncClient, make_client: MakeClient, make_device: MakeDevice
) -> None:
    client = await make_client(telegram_id=4242, first_name="Anna")
    device = await make_device(client)
    row = (await admin_client.get("/admin/devices")).json()["items"][0]
    assert (row["telegram_id"], row["client_name"], row["client_id"]) == (4242, "Anna", client.id)
    assert row["username"] == device.ocserv_username
    assert row["is_online"] is None  # кэша ноды нет


async def test_online_filter_follows_the_node_cache(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: ArqRedis,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    here = await make_device(client, seq=1)
    away = await make_device(client, seq=2)
    node = await registry.ensure_local_node(session, settings)
    await redis.set(service.online_key(node.id), json.dumps([here.ocserv_username]))
    assert await ids(admin_client, online="true") == [here.id]
    assert await ids(admin_client, online="false") == [away.id]
    rows = (await admin_client.get("/admin/devices")).json()["items"]
    assert {r["id"]: r["is_online"] for r in rows} == {here.id: True, away.id: False}


async def test_online_filter_without_a_cache_is_refused_not_guessed(
    admin_client: AsyncClient, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await make_device(await make_client())
    r = await admin_client.get("/admin/devices?online=true")
    assert (r.status_code, r.json()["error"]["code"]) == (503, "node_unavailable")
    assert (await admin_client.get("/admin/devices")).status_code == 200


async def test_revoke_records_everything_once(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    device = await make_device(await make_client())
    url = f"/admin/devices/{device.id}/revoke"
    first = await admin_client.post(url, json={"reason": "  утерян  "})
    assert first.status_code == 200, first.text
    assert first.json()["revocation_reason"] == "утерян"
    again = await admin_client.post(url, json={"reason": "другая причина"})
    assert again.status_code == 200
    assert again.json()["revoked_at"] == first.json()["revoked_at"]
    assert again.json()["revocation_reason"] == "утерян"  # повтор ничего не переписал

    async def count(model: type) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    assert await count(Revocation) == 1
    events = list(await session.scalars(select(EventOutbox.name)))
    assert events.count("device.revoked") == 1
    audits = list(await session.scalars(select(AuditLog).where(AuditLog.action == "device.revoke")))
    assert len(audits) == 1
    assert audits[0].actor_type == "admin"
    assert audits[0].details["reason"] == "утерян"


async def test_revoke_cuts_the_device_off_at_the_node(
    admin_client: AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake: FakeNodeDriver,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, now=utcnow())
    device = await make_device(client)
    fake.allowlist = {device.ocserv_username}
    fake.add_session(device.ocserv_username)
    await admin_client.post(f"/admin/devices/{device.id}/revoke", json={"reason": "утерян"})
    await bus.dispatch_pending(sessionmaker)
    assert fake.allowlist == set()
    assert fake.sessions == []


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 201}])
async def test_a_bad_reason_is_422(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_device: MakeDevice,
    body: dict[str, str],
) -> None:
    device = await make_device(await make_client())
    r = await admin_client.post(f"/admin/devices/{device.id}/revoke", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")


async def test_unknown_and_absurd_ids(admin_client: AsyncClient) -> None:
    body = {"reason": "x"}
    r = await admin_client.post("/admin/devices/424242/revoke", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert (await admin_client.post("/admin/devices/0/revoke", json=body)).status_code == 422
    huge = await admin_client.post(f"/admin/devices/{'9' * 30}/revoke", json=body)
    assert huge.status_code == 422
    assert (await admin_client.get("/admin/devices/424242/sessions")).status_code == 404


async def test_sessions_are_newest_first_and_belong_to_the_device(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    now = utcnow()
    client = await make_client()
    mine = await make_device(client, seq=1)
    other = await make_device(client, seq=2)
    node = await registry.ensure_local_node(session, settings)
    for n, username in enumerate([mine.ocserv_username] * 3 + [other.ocserv_username]):
        started = now - timedelta(hours=n)
        session.add(
            SessionLog(
                node_id=node.id,
                username=username,
                ocserv_session_id=str(n),
                started_at=started,
                ended_at=started + timedelta(minutes=5),
                client_ip="203.0.113.7",
                bytes_in=10 * n,
                bytes_out=20 * n,
                last_polled_at=started,
                final_received=True,
            )
        )
    await session.flush()
    body = (await admin_client.get(f"/admin/devices/{mine.id}/sessions")).json()
    assert body["total"] == 3
    stamps = [s["started_at"] for s in body["items"]]
    assert stamps == sorted(stamps, reverse=True)
    assert {s["username"] for s in body["items"]} == {mine.ocserv_username}
    assert body["items"][0]["duration_sec"] == 300
    page = (await admin_client.get(f"/admin/devices/{mine.id}/sessions?limit=2&offset=2")).json()
    assert (page["total"], len(page["items"])) == (3, 1)
