from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps.worker import (
    WorkerSettings,
    dispatch_events,
    purge_event_outbox,
    shutdown,
    startup,
)
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import ClientBlocked


def test_cron_registry() -> None:
    names = {job.name for job in WorkerSettings.cron_jobs}
    assert names == {"cron:dispatch_events", "cron:purge_event_outbox"}


def test_dispatch_events_runs_every_5_seconds() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:dispatch_events"]
    assert job.second == set(range(0, 60, 5))


def test_purge_runs_daily_at_4_utc() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:purge_event_outbox"]
    assert (job.hour, job.minute, job.second) == ({4}, {0}, 0)


def test_kick_job_is_registered_without_result() -> None:
    [fn] = [f for f in WorkerSettings.functions if f.name == "dispatch_events"]
    assert fn.keep_result_s == 0


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
