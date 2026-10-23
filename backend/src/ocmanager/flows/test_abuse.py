from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakeDevice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.core.config import Settings
from ocmanager.flows import abuse
from ocmanager.nodes import registry
from ocmanager.nodes.models import SessionLog, TrafficDaily
from ocmanager.notifications.models import OutboxMessage

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
GIB = 1024**3
ADMIN = 777


async def setup_admin(session: AsyncSession, **settings: int) -> None:
    await settings_store.update(session, {"admin_chat_ids": [ADMIN], **settings})


async def alerts(session: AsyncSession) -> list[OutboxMessage]:
    rows = await session.scalars(
        select(OutboxMessage)
        .where(OutboxMessage.template_key.like("abuse_%"))
        .order_by(OutboxMessage.id)
    )
    return list(rows)


async def add_traffic(
    session: AsyncSession, username: str, *, gib: int, day_offset: int = 0
) -> None:
    node = await registry.ensure_local_node(session, _settings())
    session.add(
        TrafficDaily(
            username=username,
            node_id=node.id,
            day=(NOW - timedelta(days=day_offset)).date(),
            bytes_in=gib * GIB // 2,
            bytes_out=gib * GIB - gib * GIB // 2,
        )
    )
    await session.flush()


def _settings() -> Settings:
    return Settings(_env_file=None)


async def add_session(
    session: AsyncSession, username: str, ip: str | None, *, age: timedelta = timedelta(hours=1)
) -> None:
    node = await registry.ensure_local_node(session, _settings())
    when = NOW - age
    session.add(
        SessionLog(
            node_id=node.id,
            username=username,
            ocserv_session_id=f"{username}-{when.timestamp()}-{ip}",
            started_at=when,
            client_ip=ip,
            bytes_in=0,
            bytes_out=0,
            last_polled_at=when,
        )
    )
    await session.flush()


# ── трафик за сутки ────────────────────────────────────────────────────────


async def test_a_client_above_the_daily_threshold_is_reported_once_per_day(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    client = await make_client(first_name="Big", username="big")
    device = await make_device(client)
    await add_traffic(session, device.ocserv_username, gib=120)

    assert await abuse.detect(session, NOW) == 1
    assert (
        await abuse.detect(session, NOW + timedelta(minutes=15)) == 0
    )  # тот же день, тот же клиент
    [msg] = await alerts(session)
    assert (msg.template_key, msg.recipient_type, msg.chat_id) == ("abuse_traffic", "admin", ADMIN)
    assert msg.payload["client"] == f"@big ({client.telegram_id})"
    assert msg.payload["traffic"] == "120 GB"
    assert msg.payload["limit"] == "100 GB"


async def test_the_next_day_reports_again(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=120)
    await abuse.detect(session, NOW)
    tomorrow = NOW + timedelta(days=1)
    await add_traffic(session, device.ocserv_username, gib=130, day_offset=-1)
    assert await abuse.detect(session, tomorrow) == 1


async def test_traffic_below_the_threshold_is_quiet(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=99)
    assert await abuse.detect(session, NOW) == 0


async def test_the_threshold_itself_counts(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=100)
    assert await abuse.detect(session, NOW) == 1


async def test_traffic_is_summed_over_all_devices_of_a_client(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    client = await make_client()
    for seq in (1, 2):
        device = await make_device(client, seq=seq)
        await add_traffic(session, device.ocserv_username, gib=60)
    assert await abuse.detect(session, NOW) == 1


async def test_only_todays_traffic_counts(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=500, day_offset=1)
    assert await abuse.detect(session, NOW) == 0


async def test_traffic_of_unknown_usernames_is_ignored(session: AsyncSession) -> None:
    await setup_admin(session)
    await add_traffic(session, "c999-d1", gib=500)
    assert await abuse.detect(session, NOW) == 0


async def test_a_zero_threshold_switches_the_traffic_rule_off(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_daily_traffic_gb=0)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=500)
    assert await abuse.detect(session, NOW) == 0


async def test_the_threshold_is_read_from_the_settings(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_daily_traffic_gb=10)
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=11)
    assert await abuse.detect(session, NOW) == 1


# ── много устройств с одного адреса ────────────────────────────────────────


async def devices_from_one_ip(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice, n: int, ip: str
) -> None:
    for _ in range(n):
        client = await make_client()
        device = await make_device(client)
        await add_session(session, device.ocserv_username, ip)


async def test_many_devices_from_one_address_are_reported_once_per_day(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    await devices_from_one_ip(session, make_client, make_device, 10, "203.0.113.7")
    assert await abuse.detect(session, NOW) == 1
    assert await abuse.detect(session, NOW + timedelta(minutes=15)) == 0
    [msg] = await alerts(session)
    assert msg.template_key == "abuse_shared_ip"
    assert msg.payload == {"ip": "203.0.113.7", "devices": 10, "clients": 10}


async def test_a_few_devices_from_one_address_are_normal(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session)
    await devices_from_one_ip(session, make_client, make_device, 9, "203.0.113.7")
    assert await abuse.detect(session, NOW) == 0


async def test_one_device_reconnecting_many_times_counts_once(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=3)
    device = await make_device(await make_client())
    for hours in range(1, 8):
        await add_session(
            session, device.ocserv_username, "203.0.113.7", age=timedelta(hours=hours)
        )
    assert await abuse.detect(session, NOW) == 0


async def test_devices_of_one_family_count_as_devices_not_clients(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=3)
    client = await make_client()
    for seq in (1, 2, 3):
        device = await make_device(client, seq=seq)
        await add_session(session, device.ocserv_username, "198.51.100.1")
    assert await abuse.detect(session, NOW) == 1
    [msg] = await alerts(session)
    assert (msg.payload["devices"], msg.payload["clients"]) == (3, 1)


async def test_old_sessions_do_not_count(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=2)
    for _ in range(3):
        device = await make_device(await make_client())
        await add_session(session, device.ocserv_username, "203.0.113.7", age=timedelta(hours=30))
    assert await abuse.detect(session, NOW) == 0


async def test_sessions_without_an_address_are_ignored(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=2)
    for _ in range(3):
        device = await make_device(await make_client())
        await add_session(session, device.ocserv_username, None)
    assert await abuse.detect(session, NOW) == 0


async def test_different_addresses_are_judged_separately(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=3)
    await devices_from_one_ip(session, make_client, make_device, 2, "203.0.113.7")
    await devices_from_one_ip(session, make_client, make_device, 2, "203.0.113.8")
    assert await abuse.detect(session, NOW) == 0


async def test_a_zero_threshold_switches_the_address_rule_off(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=0)
    await devices_from_one_ip(session, make_client, make_device, 20, "203.0.113.7")
    assert await abuse.detect(session, NOW) == 0


# ── общее ──────────────────────────────────────────────────────────────────


async def test_without_admin_chats_nothing_is_queued_and_nothing_fails(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=500)
    assert await abuse.detect(session, NOW) == 0
    assert await alerts(session) == []


async def test_both_rules_can_fire_in_one_run(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await setup_admin(session, abuse_devices_per_ip=3)
    client = await make_client()
    heavy = await make_device(client)
    await add_traffic(session, heavy.ocserv_username, gib=500)
    await devices_from_one_ip(session, make_client, make_device, 3, "203.0.113.7")
    assert await abuse.detect(session, NOW) == 2
    assert sorted(m.template_key for m in await alerts(session)) == [
        "abuse_shared_ip",
        "abuse_traffic",
    ]


async def test_every_admin_gets_the_alert(
    session: AsyncSession, make_client: MakeClient, make_device: MakeDevice
) -> None:
    await settings_store.update(session, {"admin_chat_ids": [1, 2]})
    device = await make_device(await make_client())
    await add_traffic(session, device.ocserv_username, gib=500)
    assert await abuse.detect(session, NOW) == 2
    assert sorted(m.chat_id for m in await alerts(session)) == [1, 2]


@pytest.mark.parametrize("kind", ["abuse_traffic", "abuse_shared_ip"])
def test_alert_templates_exist(kind: str) -> None:
    from ocmanager.notifications import render

    assert kind in render.keys("ru")
    assert kind in render.keys("en")
