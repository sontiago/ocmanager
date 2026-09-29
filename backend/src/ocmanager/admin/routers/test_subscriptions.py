from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import MakeClient, MakeDevice, MakeSubscription
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.flows import handlers
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.subscriptions.models import Subscription


@pytest.fixture
def fake(settings: Settings) -> Iterator[FakeNodeDriver]:
    handlers.register(settings)
    driver = FakeNodeDriver(allowlist=set())
    with registry.override_driver(driver):
        yield driver


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/subscriptions"),
        ("POST", "/admin/subscriptions/1/cancel-auto-renew"),
        ("POST", "/admin/subscriptions/1/expire"),
    ],
)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


async def rows(admin_client: AsyncClient, **params: str | int) -> list[int]:
    r = await admin_client.get("/admin/subscriptions", params=params)
    assert r.status_code == 200, r.text
    return [row["client_id"] for row in r.json()["items"]]


async def test_the_expiring_filter_takes_only_live_subscriptions_inside_the_window(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    now = utcnow()
    soon, sooner, far, ended, overdue = [await make_client() for _ in range(5)]
    subs = {
        soon: await make_subscription(soon, days=2, now=now),
        sooner: await make_subscription(sooner, days=1, now=now),
        far: await make_subscription(far, days=10, now=now),
        ended: await make_subscription(ended, days=1, now=now),
        overdue: await make_subscription(overdue, days=5, now=now),
    }
    subs[ended].status = "expired"  # срок в окне, но подписка уже закрыта
    subs[overdue].expires_at = now - timedelta(hours=1)  # cron ещё не успел
    await session.flush()

    # ближайшие первыми: просроченная, за ней те, что кончаются раньше
    assert await rows(admin_client, expiring_within_days=3) == [overdue.id, sooner.id, soon.id]
    assert await rows(admin_client, expiring_within_days=0) == [overdue.id]
    assert far.id in await rows(admin_client, expiring_within_days=30)
    assert ended.id not in await rows(admin_client, expiring_within_days=30)


@pytest.mark.parametrize("days", [-1, 3651, 99_999_999])
async def test_a_silly_window_is_422(admin_client: AsyncClient, days: int) -> None:
    r = await admin_client.get(f"/admin/subscriptions?expiring_within_days={days}")
    assert r.status_code == 422


async def test_status_and_plan_filters_and_pagination(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    now = utcnow()
    a, b, c = await make_client(), await make_client(), await make_client()
    await make_subscription(a, now=now)  # тариф plan1: код даёт фабрика по порядку
    await make_subscription(b, now=now)
    sc = await make_subscription(c, now=now)
    sc.status = "expired"
    await session.flush()
    assert sorted(await rows(admin_client, status="active")) == sorted([a.id, b.id])
    assert await rows(admin_client, status="expired") == [c.id]
    assert await rows(admin_client, plan="plan1") == [a.id]
    assert await rows(admin_client, plan="ghost") == []
    page = (await admin_client.get("/admin/subscriptions?limit=1&offset=1")).json()
    assert (page["total"], len(page["items"])) == (3, 1)
    assert (await admin_client.get("/admin/subscriptions?status=bogus")).status_code == 422


async def test_rows_name_the_client_and_the_plan(
    admin_client: AsyncClient, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    client = await make_client(telegram_id=4242, first_name="Anna", username="anna_k")
    await make_subscription(client, now=utcnow())
    row = (await admin_client.get("/admin/subscriptions")).json()["items"][0]
    assert (row["telegram_id"], row["first_name"], row["username"]) == (4242, "Anna", "anna_k")
    assert (row["status"], row["auto_renew"], row["plan_is_trial"]) == ("active", True, False)


async def test_cancel_auto_renew_once(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    await make_subscription(client, now=utcnow(), auto_renew=True)
    url = f"/admin/subscriptions/{client.id}/cancel-auto-renew"
    assert (await admin_client.post(url)).json() == {"changed": True}
    assert (await admin_client.post(url)).json() == {"changed": False}
    sub = await session.scalar(select(Subscription))
    assert sub is not None
    await session.refresh(sub)
    assert (sub.status, sub.auto_renew) == ("cancelled", False)
    cancels = await session.scalars(
        select(AuditLog).where(AuditLog.action == "subscription.cancel_auto_renew")
    )
    assert len(list(cancels)) == 1


async def test_cancel_and_expire_for_a_missing_client_are_404(admin_client: AsyncClient) -> None:
    for action in ("cancel-auto-renew", "expire"):
        r = await admin_client.post(f"/admin/subscriptions/424242/{action}")
        assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert (await admin_client.post("/admin/subscriptions/0/expire")).status_code == 422


async def test_a_client_without_a_subscription_has_nothing_to_cancel_or_expire(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    client = await make_client()
    for action in ("cancel-auto-renew", "expire"):
        r = await admin_client.post(f"/admin/subscriptions/{client.id}/{action}")
        assert r.json() == {"changed": False}


async def test_expire_takes_the_access_away_at_the_node(
    admin_client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake: FakeNodeDriver,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=utcnow())
    device = await make_device(client)
    fake.allowlist = {device.ocserv_username}
    fake.add_session(device.ocserv_username)

    r = await admin_client.post(f"/admin/subscriptions/{client.id}/expire")
    assert r.json() == {"changed": True}
    sub = await session.scalar(select(Subscription))
    assert sub is not None
    await session.refresh(sub)
    assert sub.status == "expired"
    assert sub.expires_at <= utcnow()  # срок обрезан: «expires_at > now» больше не держит доступ

    await bus.dispatch_pending(sessionmaker)  # то, что сделал бы воркер
    assert fake.allowlist == set()
    assert fake.sessions == []  # и сессия разорвана
    names = list(await session.scalars(select(EventOutbox.name)))
    assert names.count("subscription.expired") == 1

    assert (await admin_client.post(f"/admin/subscriptions/{client.id}/expire")).json() == {
        "changed": False
    }
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "subscription.expire"))
    assert audit is not None
    assert audit.actor_type == "admin"
    assert audit.details["forced"] is True
