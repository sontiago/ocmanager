from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from conftest import MakeClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import (
    ClientBlocked,
    ClientUnblocked,
    DeviceIssued,
    DeviceRevoked,
    DomainEvent,
    SubscriptionActivated,
    SubscriptionAutoRenewCancelled,
    SubscriptionExpired,
    SubscriptionRenewed,
)
from ocmanager.flows import devices, handlers
from ocmanager.flows import subscriptions as sub_flows
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.provisioning.pki.ca import CertificateAuthority

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)
ACTOR = Actor.system()


@pytest.fixture
def clock() -> Iterator[time_machine.Traveller]:
    """Часы стоят на NOW: и запись события, и доставка, и обработчик видят одно время."""
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def fake(settings: Settings, clock: time_machine.Traveller) -> Iterator[FakeNodeDriver]:
    """Обработчики зарегистрированы, драйвер подменён. Реестр шины чистит conftest."""
    handlers.register(settings)
    driver = FakeNodeDriver(allowlist={"c999-d1"})
    with registry.override_driver(driver):
        yield driver


@pytest.mark.parametrize(
    "event",
    [
        SubscriptionActivated(client_id=1),
        SubscriptionRenewed(client_id=1),
        SubscriptionExpired(client_id=1),
        ClientBlocked(client_id=1),
        ClientUnblocked(client_id=1),
        DeviceIssued(client_id=1, device_id=1),
        DeviceRevoked(client_id=1, device_id=1, username="c1-d1"),
    ],
    ids=lambda e: e.name,
)
async def test_every_access_event_syncs_the_node(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake: FakeNodeDriver,
    event: DomainEvent,
) -> None:
    await bus.record(session, event)
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1
    assert fake.allowlist == set()  # «чужой» c999-d1 убран: список пересчитан целиком


async def test_events_that_do_not_change_access_do_not_touch_the_node(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], fake: FakeNodeDriver
) -> None:
    await bus.record(session, SubscriptionAutoRenewCancelled(client_id=1))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1
    assert fake.calls == []
    assert fake.allowlist == {"c999-d1"}


async def test_issue_and_expiry_end_to_end(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake: FakeNodeDriver,
    clock: time_machine.Traveller,
    make_client: MakeClient,
    trial_plan: Plan,
    test_ca: CertificateAuthority,
) -> None:
    client = await make_client()
    await sub_flows.start_trial(
        session, client.id, sub_flows.terms_from_plan(trial_plan), ACTOR, NOW
    )
    device = (
        await devices.issue_device(
            session,
            client_id=client.id,
            name="A",
            platform="linux",
            device_limit=1,
            ca=test_ca,
            actor=ACTOR,
            now=NOW,
        )
    ).device
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 2  # activated + issued
    assert fake.allowlist == {device.ocserv_username}

    fake.add_session(device.ocserv_username)
    later = NOW + 4 * DAY  # trial — 3 дня
    clock.move_to(later)
    await sub_flows.expire_due(session, later)
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1
    assert fake.allowlist == set()
    assert fake.sessions == []


async def test_handler_is_idempotent(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], fake: FakeNodeDriver
) -> None:
    for _ in range(2):
        await bus.record(session, ClientBlocked(client_id=1))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 2
    publishes = [c for c in fake.calls if c[0] == "publish_allowlist"]
    assert len(publishes) == 1  # второй раз разницы нет — записи нет


async def test_unreachable_node_leaves_the_event_for_a_retry(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], fake: FakeNodeDriver
) -> None:
    fake.occtl_ok = False
    await bus.record(session, ClientBlocked(client_id=1))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 0
    row = await session.scalar(select(EventOutbox))
    assert row is not None
    await session.refresh(row)
    assert row.dispatched_at is None
    assert row.attempts == 1
    assert row.last_error is not None
    assert "NodeUnreachable" in row.last_error

    fake.occtl_ok = True
    row.available_at = NOW  # backoff прошёл
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1
    assert fake.allowlist == set()
