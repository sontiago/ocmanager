from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakeDevice, MakePlan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps.worker import (
    WorkerSettings,
    apply_revocations,
    check_nodes,
    collect_traffic,
    dispatch_events,
    expire_subscriptions,
    get_ca,
    purge_event_outbox,
    purge_traffic,
    reconcile_nodes,
    refresh_crl,
    shutdown,
    startup,
)
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import ClientBlocked
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node
from ocmanager.nodes.service import cached_health
from ocmanager.provisioning import service as provisioning
from ocmanager.provisioning.pki.ca import CertificateAuthority, save_ca
from ocmanager.subscriptions.service import get_subscription


def test_cron_registry() -> None:
    names = {job.name for job in WorkerSettings.cron_jobs}
    assert names == {
        "cron:dispatch_events",
        "cron:purge_event_outbox",
        "cron:check_nodes",
        "cron:expire_subscriptions",
        "cron:apply_revocations",
        "cron:refresh_crl",
        "cron:collect_traffic",
        "cron:purge_traffic",
        "cron:reconcile_nodes",
    }


def test_dispatch_events_runs_every_5_seconds() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:dispatch_events"]
    assert job.second == set(range(0, 60, 5))


def test_purge_runs_daily_at_4_utc() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:purge_event_outbox"]
    assert (job.hour, job.minute, job.second) == ({4}, {0}, 0)


def test_kick_job_is_registered_without_result() -> None:
    [fn] = [f for f in WorkerSettings.functions if f.name == "dispatch_events"]
    assert fn.keep_result_s == 0


def test_check_nodes_runs_every_minute() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:check_nodes"]
    assert job.second == {30}
    assert job.minute is None


async def test_dispatch_events_delivers(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seen: list[int] = []

    @bus.on(ClientBlocked)
    async def handler(event: ClientBlocked, _: AsyncSession) -> None:
        seen.append(event.client_id)

    await bus.record(session, ClientBlocked(client_id=3))
    await session.commit()

    assert await dispatch_events({"sessionmaker": sessionmaker}) == 1
    assert seen == [3]


async def test_purge_event_outbox_deletes_old_dispatched(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    now = utcnow()
    session.add(
        EventOutbox(
            name="client.blocked",
            payload={"client_id": 1},
            available_at=now,
            dispatched_at=now - timedelta(days=31),
        )
    )
    await session.commit()
    assert await purge_event_outbox({"sessionmaker": sessionmaker}) == 1


async def test_startup_and_shutdown(settings: Settings, db_engine: object) -> None:
    ctx: dict[str, Any] = {"settings": settings}
    await startup(ctx)
    assert await dispatch_events(ctx) == 0
    await shutdown(ctx)


async def test_check_nodes_updates_status_and_cache(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    settings: Settings,
) -> None:
    ctx: dict[str, Any] = {
        "settings": settings,
        "sessionmaker": sessionmaker,
        "redis": redis,
    }
    with registry.override_driver(FakeNodeDriver()):
        assert await check_nodes(ctx) == 1
    node = await session.scalar(select(Node).where(Node.name == "local"))
    assert node is not None
    assert node.status == "online"
    health = await cached_health(redis, node.id)
    assert health is not None
    assert health.state == "online"


def test_expire_subscriptions_runs_every_minute() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:expire_subscriptions"]
    assert job.second == {10}
    assert job.minute is None


async def test_expire_subscriptions_expires_and_kicks_the_dispatcher(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    make_client: MakeClient,
    make_plan: MakePlan,
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=1)
    await subscription_flows.activate(
        session,
        client.id,
        subscription_flows.terms_from_plan(plan),
        Actor.system(),
        utcnow() - timedelta(days=2),
        auto_renew=True,
    )
    await session.commit()
    ctx: dict[str, Any] = {"sessionmaker": sessionmaker, "redis": redis}
    assert await expire_subscriptions(ctx) == 1
    assert [j.function for j in await redis.queued_jobs()] == ["dispatch_events"]
    assert await expire_subscriptions(ctx) == 0
    sub = await get_subscription(session, client.id)
    assert sub is not None
    await session.refresh(sub)
    assert sub.status == "expired"


def test_apply_revocations_runs_twice_a_minute() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:apply_revocations"]
    assert job.second == {15, 45}


def test_crl_is_refreshed_daily_at_3_utc() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:refresh_crl"]
    assert (job.hour, job.minute, job.second) == ({3}, {0}, 0)


def test_get_ca_loads_lazily_and_once(
    settings: Settings, tmp_path: Path, test_ca: CertificateAuthority
) -> None:
    ctx: dict[str, Any] = {"settings": settings.model_copy(update={"pki_dir": tmp_path})}
    with pytest.raises(FileNotFoundError):  # воркеру без ключа стартовать можно, а брать ключ — нет
        get_ca(ctx)
    save_ca(test_ca, tmp_path)
    first = get_ca(ctx)
    assert get_ca(ctx) is first


async def test_apply_revocations_task_survives_an_unreachable_node(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    test_ca: CertificateAuthority,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    device = await make_device(await make_client())
    await provisioning.revoke_device(
        session, device.id, owner_client_id=None, reason="x", now=utcnow()
    )
    await session.commit()
    ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker, "ca": test_ca}
    with registry.override_driver(FakeNodeDriver(occtl_ok=False)):
        assert await apply_revocations(ctx) == 0
    with registry.override_driver(FakeNodeDriver()):
        assert await apply_revocations(ctx) == 1
        assert await apply_revocations(ctx) == 0


async def test_refresh_crl_task_publishes(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    test_ca: CertificateAuthority,
) -> None:
    fake = FakeNodeDriver()
    ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker, "ca": test_ca}
    async with sessionmaker() as s:
        await registry.ensure_local_node(s, settings)
        await s.commit()
    with registry.override_driver(fake):
        await refresh_crl(ctx)
    assert fake.crl is not None


def test_traffic_is_collected_every_5_minutes() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:collect_traffic"]
    assert job.minute == set(range(0, 60, 5))
    assert job.second == {20}


def test_traffic_samples_are_purged_daily() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:purge_traffic"]
    assert (job.hour, job.minute, job.second) == ({4}, {30}, 0)


async def test_collect_traffic_task_counts_seen_sessions(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    fake = FakeNodeDriver()
    fake.add_session("c1-d1", bytes_in=10)
    fake.add_session("c2-d1", bytes_in=20)
    ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker}
    with registry.override_driver(fake):
        assert await collect_traffic(ctx) == 2


async def test_purge_traffic_task(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    assert await purge_traffic({"sessionmaker": sessionmaker}) == 0


def test_reconcile_runs_every_5_minutes() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:reconcile_nodes"]
    assert job.minute == set(range(0, 60, 5))
    assert job.second == {40}


async def test_reconcile_task_heals_and_reports_the_number_of_drifts(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    test_ca: CertificateAuthority,
) -> None:
    fake = FakeNodeDriver(allowlist=None, crl=None)
    ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker, "ca": test_ca}
    with registry.override_driver(fake):
        assert await reconcile_nodes(ctx) == 2  # allowlist_missing + crl_missing
        assert await reconcile_nodes(ctx) == 0
