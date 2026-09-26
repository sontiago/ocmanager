import asyncio
from datetime import timedelta

import time_machine
from arq import ArqRedis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.clock import utcnow
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import ClientBlocked, DeviceRevoked, SubscriptionActivated


async def outbox(session: AsyncSession) -> list[EventOutbox]:
    session.expire_all()
    return list(await session.scalars(select(EventOutbox).order_by(EventOutbox.id)))


async def test_record_and_deliver(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seen: list[SubscriptionActivated] = []

    @bus.on(SubscriptionActivated)
    async def handler(event: SubscriptionActivated, _: AsyncSession) -> None:
        seen.append(event)

    await bus.record(session, SubscriptionActivated(client_id=7))
    await session.commit()

    assert await bus.dispatch_pending(sessionmaker) == 1
    assert seen == [SubscriptionActivated(client_id=7)]
    [row] = await outbox(session)
    assert row.dispatched_at is not None
    assert row.payload == {"client_id": 7}
    assert await bus.dispatch_pending(sessionmaker) == 0


async def test_handler_receives_only_its_events(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seen: list[str] = []

    @bus.on(ClientBlocked, DeviceRevoked)
    async def handler(event: ClientBlocked | DeviceRevoked, _: AsyncSession) -> None:
        seen.append(event.name)

    await bus.record(session, SubscriptionActivated(client_id=1))
    await bus.record(session, ClientBlocked(client_id=1))
    await bus.record(session, DeviceRevoked(client_id=1, device_id=2, username="c1-d2"))
    await session.commit()

    assert await bus.dispatch_pending(sessionmaker) == 3
    assert seen == ["client.blocked", "device.revoked"]


async def test_event_without_handlers_is_marked_dispatched(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await bus.record(session, ClientBlocked(client_id=1))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1
    [row] = await outbox(session)
    assert row.dispatched_at is not None


async def test_handler_changes_commit_with_delivery(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await session.execute(text("CREATE TEMP TABLE effects (client_id int)"))

    @bus.on(ClientBlocked)
    async def handler(event: ClientBlocked, s: AsyncSession) -> None:
        await s.execute(text("INSERT INTO effects VALUES (:c)"), {"c": event.client_id})

    await bus.record(session, ClientBlocked(client_id=5))
    await session.commit()
    await bus.dispatch_pending(sessionmaker)
    assert await session.scalar(text("SELECT client_id FROM effects")) == 5


async def test_failing_handler_rolls_back_all_handlers_and_backs_off(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await session.execute(text("CREATE TEMP TABLE effects (client_id int)"))

    @bus.on(ClientBlocked)
    async def first(event: ClientBlocked, s: AsyncSession) -> None:
        await s.execute(text("INSERT INTO effects VALUES (:c)"), {"c": event.client_id})

    @bus.on(ClientBlocked)
    async def second(event: ClientBlocked, s: AsyncSession) -> None:
        raise RuntimeError("node is down")

    await bus.record(session, ClientBlocked(client_id=5))
    await session.commit()
    before = utcnow()

    assert await bus.dispatch_pending(sessionmaker) == 0
    [row] = await outbox(session)
    assert row.dispatched_at is None
    assert row.attempts == 1
    assert row.last_error == "RuntimeError: node is down"
    assert row.available_at >= before + timedelta(seconds=2)
    assert await session.scalar(text("SELECT count(*) FROM effects")) == 0
    # до истечения backoff событие не выбирается повторно
    assert await bus.dispatch_pending(sessionmaker) == 0
    assert (await outbox(session))[0].attempts == 1


async def test_retry_after_backoff_delivers(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    calls = 0

    @bus.on(ClientBlocked)
    async def flaky(event: ClientBlocked, _: AsyncSession) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first time fails")

    await bus.record(session, ClientBlocked(client_id=1))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 0

    with time_machine.travel(utcnow() + timedelta(seconds=3)):
        assert await bus.dispatch_pending(sessionmaker) == 1
    assert calls == 2


async def test_malformed_payload_counts_as_failure(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    session.add(EventOutbox(name="client.blocked", payload={"oops": 1}, available_at=utcnow()))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 0
    [row] = await outbox(session)
    assert (row.attempts, row.dispatched_at) == (1, None)
    assert row.last_error is not None
    assert row.last_error.startswith("ValidationError")


async def test_dead_event_is_not_selected(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    session.add(
        EventOutbox(
            name="client.blocked",
            payload={"client_id": 1},
            available_at=utcnow(),
            attempts=bus.MAX_ATTEMPTS,
        )
    )
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 0


def test_backoff_is_capped() -> None:
    assert bus.backoff(1) == timedelta(seconds=2)
    assert bus.backoff(5) == timedelta(seconds=32)
    assert bus.backoff(9) == timedelta(seconds=300)


async def test_limit_bounds_one_call(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    for i in range(5):
        await bus.record(session, ClientBlocked(client_id=i))
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker, limit=3) == 3
    assert await bus.dispatch_pending(sessionmaker, limit=3) == 2


async def test_uncommitted_event_is_invisible(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with committed_sessionmaker() as producer:
        await bus.record(producer, ClientBlocked(client_id=1))
        await producer.flush()
        assert await bus.dispatch_pending(committed_sessionmaker) == 0
        await producer.rollback()


async def test_concurrent_dispatchers_deliver_each_event_once(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    calls: list[int] = []

    @bus.on(ClientBlocked)
    async def slow(event: ClientBlocked, _: AsyncSession) -> None:
        calls.append(event.client_id)
        await asyncio.sleep(0.01)

    async with committed_sessionmaker() as s, s.begin():
        for i in range(20):
            await bus.record(s, ClientBlocked(client_id=i))

    a, b = await asyncio.gather(
        bus.dispatch_pending(committed_sessionmaker),
        bus.dispatch_pending(committed_sessionmaker),
    )
    assert a + b == 20
    assert a > 0
    assert b > 0
    assert sorted(calls) == list(range(20))
    async with committed_sessionmaker() as s:
        pending = await s.scalar(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.dispatched_at.is_(None))
        )
    assert pending == 0


async def test_kick_enqueues_single_job(redis: ArqRedis) -> None:
    await bus.kick_dispatch(redis)
    await bus.kick_dispatch(redis)
    jobs = await redis.queued_jobs()
    assert [j.function for j in jobs] == ["dispatch_events"]


async def test_kick_swallows_redis_errors() -> None:
    class BrokenRedis:
        async def enqueue_job(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("redis down")

    await bus.kick_dispatch(BrokenRedis())  # type: ignore[arg-type]


def test_registry_starts_empty_in_each_test() -> None:
    # предыдущие тесты регистрировали обработчики; фикстура conftest их убрала
    assert bus._handlers.get("client.blocked", []) == []
