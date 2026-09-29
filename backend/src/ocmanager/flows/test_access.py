from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakeDevice, MakeSubscription
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.flows import access
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node
from ocmanager.provisioning.service import list_devices
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture
async def node(session: AsyncSession, settings: Settings) -> Node:
    return await registry.ensure_local_node(session, settings)


def writes(fake: FakeNodeDriver) -> list[str]:
    """Что менялось на ноде (чтения не считаем)."""
    return [name for name, _ in fake.calls if name in {"publish_allowlist", "disconnect_user"}]


async def live_client(
    make_client: MakeClient, make_subscription: MakeSubscription, make_device: MakeDevice
) -> tuple[Client, str]:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    return client, (await make_device(client)).ocserv_username


# --- desired_usernames -----------------------------------------------------


async def test_desired_matches_has_access_on_every_kind_of_client(
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    """Запрос доступа и чистая функция обязаны совпадать на одном наборе данных."""
    active = await make_client()
    await make_subscription(active, days=30, now=NOW)
    await make_device(active, seq=1)
    await make_device(active, seq=2, revoked=True)

    trial = await make_client()
    await make_subscription(trial, days=3, now=NOW)  # как trial по сроку
    await make_device(trial)

    cancelled = await make_client()
    await make_subscription(cancelled, days=30, now=NOW)
    await subscriptions.cancel_auto_renew(session, cancelled.id)
    await make_device(cancelled)

    expired = await make_client()
    await make_subscription(expired, days=1, now=NOW - 5 * DAY)
    await subscriptions.expire_due(session, NOW)
    await make_device(expired)

    lagging = await make_client()  # cron не успел: статус active, срок прошёл
    await make_subscription(lagging, days=1, now=NOW - 5 * DAY)
    await make_device(lagging)

    blocked = await make_client()
    await make_subscription(blocked, days=30, now=NOW)
    await subscriptions.set_blocked(session, blocked.id, True, NOW)
    await make_device(blocked)

    flag_only = await make_client()  # is_blocked без смены статуса подписки
    await make_subscription(flag_only, days=30, now=NOW)
    flag_only.is_blocked = True
    await make_device(flag_only)

    no_subscription = await make_client()
    await make_device(no_subscription)

    desired = await access.desired_usernames(session, NOW)
    everyone = [active, trial, cancelled, expired, lagging, blocked, flag_only, no_subscription]
    for client in everyone:
        has_access = await subscriptions.client_has_access(session, client.id, NOW)
        for device in await list_devices(session, client.id, include_revoked=True):
            expected = has_access and device.revoked_at is None
            assert (device.ocserv_username in desired) is expected, device.ocserv_username
    assert desired == {f"c{active.id}-d1", f"c{trial.id}-d1", f"c{cancelled.id}-d1"}


# --- sync_access -----------------------------------------------------------


async def test_publishes_the_allowlist_and_reports_the_diff(
    session: AsyncSession,
    node: Node,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    _, username = await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver(allowlist={"c999-d1"})
    result = await access.sync_access(session, node, fake, NOW)
    assert fake.allowlist == {username}
    assert (result.added, result.removed) == (frozenset({username}), frozenset({"c999-d1"}))


async def test_second_sync_touches_nothing(
    session: AsyncSession,
    node: Node,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver()
    await access.sync_access(session, node, fake, NOW)
    fake.calls.clear()
    result = await access.sync_access(session, node, fake, NOW)
    assert not result.changed
    assert writes(fake) == []


async def test_missing_allowlist_file_is_created_even_when_nobody_is_allowed(
    session: AsyncSession, node: Node
) -> None:
    fake = FakeNodeDriver(allowlist=None)
    await access.sync_access(session, node, fake, NOW)
    assert fake.allowlist == set()


async def test_user_who_lost_access_is_kicked_out(
    session: AsyncSession,
    node: Node,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    _, username = await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver()
    await access.sync_access(session, node, fake, NOW)
    fake.add_session(username)
    await subscriptions.expire_due(session, NOW + 31 * DAY)
    result = await access.sync_access(session, node, fake, NOW + 31 * DAY)
    assert fake.allowlist == set()
    assert fake.sessions == []
    assert result.disconnected == frozenset({username})


async def test_foreign_session_is_kicked_out(session: AsyncSession, node: Node) -> None:
    fake = FakeNodeDriver()
    fake.add_session("c999-d1")
    result = await access.sync_access(session, node, fake, NOW)
    assert fake.sessions == []
    assert result.disconnected == frozenset({"c999-d1"})


async def test_allowed_session_is_left_alone(
    session: AsyncSession,
    node: Node,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    _, username = await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver()
    fake.add_session(username)
    await access.sync_access(session, node, fake, NOW)
    assert [s.username for s in fake.sessions] == [username]


async def test_unreachable_occtl_is_raised_but_the_file_is_already_updated(
    session: AsyncSession,
    node: Node,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    _, username = await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver(occtl_ok=False)
    with pytest.raises(NodeUnreachable):
        await access.sync_access(session, node, fake, NOW)
    assert fake.allowlist == {username}  # файл доступен и при молчащем occtl


async def test_sync_all_nodes_creates_the_local_node_and_syncs_it(
    session: AsyncSession,
    settings: Settings,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    _, username = await live_client(make_client, make_subscription, make_device)
    fake = FakeNodeDriver()
    with registry.override_driver(fake):
        results = await access.sync_all_nodes(session, settings, NOW)
    assert fake.allowlist == {username}
    assert [r.added for r in results.values()] == [frozenset({username})]


async def test_sync_all_nodes_reports_unreachable_after_trying_everyone(
    session: AsyncSession, settings: Settings
) -> None:
    with registry.override_driver(FakeNodeDriver(occtl_ok=False)), pytest.raises(NodeUnreachable):
        await access.sync_all_nodes(session, settings, NOW)
