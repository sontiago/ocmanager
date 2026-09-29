import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakeDevice, MakeSubscription
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core import settings_store
from ocmanager.core.config import Settings
from ocmanager.flows import traffic as flows
from ocmanager.nodes import registry, traffic
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import SessionLog, TrafficSample
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.state import PlanTerms

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
DAY = timedelta(days=1)


async def push(
    session: AsyncSession,
    settings: Settings,
    username: str,
    when: datetime,
    *,
    bytes_in: int = 0,
    bytes_out: int = 0,
    sid: str = "1",
) -> None:
    """Опрос ноды в момент `when`, в котором есть одна сессия username."""
    node = await registry.ensure_local_node(session, settings)
    fake = FakeNodeDriver()
    fake.add_session(
        username, bytes_in=bytes_in, bytes_out=bytes_out, session_id=sid, connected_at=T0
    )
    await traffic.collect(session, node.id, fake.sessions, when)


@pytest.fixture
async def client_with_two_devices(
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> tuple[int, str, str]:
    client = await make_client()
    await make_subscription(client, days=30, now=T0)
    a = await make_device(client, seq=1)
    b = await make_device(client, seq=2)
    return client.id, a.ocserv_username, b.ocserv_username


async def test_usage_is_summed_over_all_devices_of_the_client(
    session: AsyncSession,
    settings: Settings,
    client_with_two_devices: tuple[int, str, str],
) -> None:
    client_id, d1, d2 = client_with_two_devices
    await push(session, settings, d1, T0 + MIN, bytes_in=100, bytes_out=50)
    await push(session, settings, d2, T0 + MIN, bytes_in=10, bytes_out=5, sid="2")
    await flows.apply_usage(session, [d1, d2], T0 + 2 * MIN)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.traffic_used_bytes == 165


async def test_only_the_current_period_counts(
    session: AsyncSession,
    settings: Settings,
    client_with_two_devices: tuple[int, str, str],
) -> None:
    client_id, d1, _ = client_with_two_devices
    await push(session, settings, d1, T0 - DAY, bytes_in=999)  # до начала периода
    await push(session, settings, d1, T0 + MIN, bytes_in=1000)  # +1 из дельты
    await flows.apply_usage(session, [d1], T0 + 2 * MIN)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.traffic_used_bytes == 1


async def test_revoked_devices_traffic_still_counts(
    session: AsyncSession,
    settings: Settings,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=T0)
    old = await make_device(client, seq=1, revoked=True)
    new = await make_device(client, seq=2)
    await push(session, settings, old.ocserv_username, T0 + MIN, bytes_in=700)
    await push(session, settings, new.ocserv_username, T0 + MIN, bytes_in=300, sid="2")
    await flows.apply_usage(session, [new.ocserv_username], T0 + 2 * MIN)
    sub = await subscriptions.get_subscription(session, client.id)
    assert sub is not None
    assert sub.traffic_used_bytes == 1000


async def test_last_seen_is_set_only_for_the_named_devices(
    session: AsyncSession, client_with_two_devices: tuple[int, str, str]
) -> None:
    _, d1, d2 = client_with_two_devices
    await flows.apply_usage(session, [d1], T0 + MIN)
    seen = {d.ocserv_username: d.last_seen_at for d in await session.scalars(select(Device))}
    assert seen == {d1: T0 + MIN, d2: None}


async def test_usernames_without_a_subscription_or_device_are_harmless(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    device = await make_device(await make_client())
    await flows.apply_usage(session, [device.ocserv_username, "c999-d1"], T0)
    await flows.apply_usage(session, [], T0)


async def test_collect_traffic_end_to_end(
    session: AsyncSession,
    settings: Settings,
    client_with_two_devices: tuple[int, str, str],
) -> None:
    client_id, d1, _ = client_with_two_devices
    fake = FakeNodeDriver()
    fake.add_session(d1, bytes_in=400, bytes_out=100, connected_at=T0)
    with registry.override_driver(fake):
        [result] = (await flows.collect_traffic(session, settings, T0 + 5 * MIN)).values()
    assert (result.opened, result.bytes_in, result.bytes_out) == (1, 400, 100)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.traffic_used_bytes == 500


async def test_unreachable_node_is_skipped_and_its_sessions_stay_open(
    session: AsyncSession,
    settings: Settings,
    client_with_two_devices: tuple[int, str, str],
) -> None:
    _, d1, _ = client_with_two_devices
    await push(session, settings, d1, T0 + MIN, bytes_in=10)
    with registry.override_driver(FakeNodeDriver(occtl_ok=False)):
        assert await flows.collect_traffic(session, settings, T0 + 6 * MIN) == {}
    log = await session.scalar(select(SessionLog))
    assert log is not None
    assert log.ended_at is None  # молчание ноды — не конец сессии


async def test_purge_uses_the_retention_setting(session: AsyncSession, settings: Settings) -> None:
    await push(session, settings, "c1-d1", T0, bytes_in=1)
    await push(session, settings, "c1-d1", T0 + 20 * DAY, bytes_in=2)
    await settings_store.update(session, {"traffic_retention_days": 7})
    assert await flows.purge_samples(session, T0 + 21 * DAY) == 1
    [left] = (await session.scalars(select(TrafficSample))).all()
    assert left.bytes_in_delta == 1


async def test_usage_rollup_does_not_undo_a_concurrent_renewal(
    committed_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Продление сбрасывает расход. Подсчёт трафика, который стартовал одновременно, не должен
    вернуть старую цифру: apply_usage берёт подписку FOR UPDATE и ждёт коммита продления."""
    async with committed_sessionmaker() as s, s.begin():
        client = Client(telegram_id=1, first_name="A", lang="ru")
        s.add(client)
        await s.flush()
        plan_id = await s.scalar(
            text(
                "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
                " currency) VALUES ('m1', '{}', 30, 1, 1, 'RUB') RETURNING id"
            )
        )
        assert plan_id is not None
        terms = PlanTerms(plan_id, 30, 1, None, False)
        await subscriptions.activate(s, client.id, terms, T0, auto_renew=True)
        s.add(
            Device(
                client_id=client.id,
                seq=1,
                name="d",
                platform="linux",
                ocserv_username=f"c{client.id}-d1",
                cert_serial="1",
                cert_fingerprint="00",
                issued_at=T0,
                cert_expires_at=T0 + 300 * DAY,
            )
        )
        client_id, username = client.id, f"c{client.id}-d1"
        node = await registry.ensure_local_node(s, settings)
        fake = FakeNodeDriver()
        fake.add_session(username, bytes_in=5000, session_id="1", connected_at=T0)
        await traffic.collect(s, node.id, fake.sessions, T0 + MIN)

    renewed_at = T0 + 2 * 60 * MIN
    lock_held = asyncio.Event()

    async def renewing() -> None:
        async with committed_sessionmaker() as a, a.begin():
            await subscriptions.renew(a, client_id, terms, renewed_at)
            lock_held.set()
            await asyncio.sleep(0.3)  # держим блокировку, пока подсчёт трафика ждёт

    async def rolling_up() -> None:
        await lock_held.wait()
        async with committed_sessionmaker() as b, b.begin():
            await flows.apply_usage(b, [username], renewed_at + MIN)

    await asyncio.gather(renewing(), rolling_up())
    async with committed_sessionmaker() as s:
        sub = await subscriptions.get_subscription(s, client_id)
        assert sub is not None
        assert sub.traffic_period_start == renewed_at
        assert sub.traffic_used_bytes == 0  # 5000 байт были в прошлом периоде
