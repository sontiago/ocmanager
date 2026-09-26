"""Транзакционный outbox доменных событий.

record() пишет событие в event_outbox в транзакции вызывающего — событие
появляется тогда и только тогда, когда закоммичено изменение, его породившее.
dispatch_pending() в воркере доставляет события обработчикам, каждое — в своей
транзакции вместе с их изменениями. Доставка at-least-once: обработчики
обязаны быть идемпотентными и не должны сами делать commit/rollback.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import structlog
from arq import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.clock import utcnow
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import DomainEvent, parse_event

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 10
MAX_BACKOFF_S = 300
KICK_JOB_ID = "dispatch_events:kick"

Handler = Callable[[Any, AsyncSession], Awaitable[None]]

_handlers: defaultdict[str, list[Handler]] = defaultdict(list)


def on[H: Handler](*event_types: type[DomainEvent]) -> Callable[[H], H]:
    """Регистрирует обработчик событий `event_types`. Порядок вызова —
    порядок регистрации. Первый параметр обработчика аннотируется типом
    события (или их объединением, если событий несколько)."""

    def register(handler: H) -> H:
        for event_type in event_types:
            _handlers[event_type.name].append(handler)
        return handler

    return register


@contextmanager
def isolated_handlers() -> Iterator[None]:
    """Для тестов: обработчики, зарегистрированные внутри, удаляются на выходе."""
    saved = {name: list(handlers) for name, handlers in _handlers.items()}
    try:
        yield
    finally:
        _handlers.clear()
        _handlers.update(saved)


async def record(session: AsyncSession, event: DomainEvent) -> None:
    session.add(
        EventOutbox(
            name=event.name,
            payload=event.model_dump(mode="json"),
            available_at=utcnow(),
        )
    )


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts, MAX_BACKOFF_S))


async def _dispatch_one(session: AsyncSession) -> bool | None:
    """Берёт одно готовое событие под блокировку и доставляет его.
    None — очередь пуста; True — доставлено; False — обработчик упал."""
    now = utcnow()
    row = await session.scalar(
        select(EventOutbox)
        .where(
            EventOutbox.dispatched_at.is_(None),
            EventOutbox.available_at <= now,
            EventOutbox.attempts < MAX_ATTEMPTS,
        )
        .order_by(EventOutbox.available_at, EventOutbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    try:
        # SAVEPOINT: падение обработчика откатывает изменения всех обработчиков
        # этого события, но не блокировку строки и не учёт попытки.
        async with session.begin_nested():
            event = parse_event(row.name, row.payload)
            for handler in _handlers.get(row.name, []):
                await handler(event, session)
    except Exception as exc:
        row.attempts += 1
        row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        row.available_at = now + backoff(row.attempts)
        log.warning(
            "event_handler_failed",
            event_id=row.id,
            event_name=row.name,
            attempts=row.attempts,
            dead=row.attempts >= MAX_ATTEMPTS,
            exc_info=exc,
        )
        return False
    row.dispatched_at = now
    return True


async def dispatch_pending(
    sessionmaker: async_sessionmaker[AsyncSession], *, limit: int = 100
) -> int:
    """Доставляет до `limit` готовых событий. Возвращает число доставленных.
    Параллельные вызовы безопасны: строки берутся FOR UPDATE SKIP LOCKED."""
    delivered = 0
    for _ in range(limit):
        async with sessionmaker() as session, session.begin():
            outcome = await _dispatch_one(session)
        if outcome is None:
            break
        delivered += int(outcome)
    return delivered


async def kick_dispatch(redis: ArqRedis) -> None:
    """Просит воркер разобрать outbox сейчас, не дожидаясь cron.
    Вызывается после commit. Best effort: при ошибке Redis событие
    всё равно доставит cron в течение 5 секунд."""
    try:
        await redis.enqueue_job("dispatch_events", _job_id=KICK_JOB_ID)
    except Exception as exc:
        log.warning("kick_dispatch_failed", exc_info=exc)
