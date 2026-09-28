"""Процесс worker: очередь arq и cron.

Запуск: `uv run python -m ocmanager.apps.worker`.
Каждая задача, добавляющая cron, дописывает его в WorkerSettings.cron_jobs
и в test_worker.py::test_cron_registry — иначе тест падает.
"""

import logging
from typing import Any, ClassVar

import structlog
from arq import cron, func, run_worker
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.worker import Function

from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.logging import configure_logging
from ocmanager.events import bus
from ocmanager.flows.nodes import check_node_health
from ocmanager.nodes import registry

log = structlog.get_logger(__name__)

EVERY_5_SECONDS = set(range(0, 60, 5))


async def startup(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx.get("settings") or get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)
    # arq пишет две INFO-строки на каждый запуск cron (≈35 тыс. в сутки);
    # ошибки задач он логирует уровнем выше и их мы видим.
    logging.getLogger("arq.worker").setLevel(logging.WARNING)
    engine = make_engine(settings.database_url)
    ctx.update(settings=settings, engine=engine, sessionmaker=make_sessionmaker(engine))
    log.info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()
    log.info("worker_stopped")


async def dispatch_events(ctx: dict[str, Any]) -> int:
    delivered = await bus.dispatch_pending(ctx["sessionmaker"])
    if delivered:
        log.info("events_dispatched", delivered=delivered)
    return delivered


async def purge_event_outbox(ctx: dict[str, Any]) -> int:
    deleted = await bus.purge_dispatched(ctx["sessionmaker"])
    if deleted:
        log.info("event_outbox_purged", deleted=deleted)
    return deleted


async def check_nodes(ctx: dict[str, Any]) -> int:
    """Здоровье нод раз в минуту: статус в БД, кэш для api-public в Redis."""
    settings: Settings = ctx["settings"]
    async with ctx["sessionmaker"]() as session:
        await registry.ensure_local_node(session, settings)
        nodes = await registry.get_active_nodes(session)
        for node in nodes:
            health = await check_node_health(
                session, node, registry.driver_for(node, settings), ctx["redis"]
            )
            log.debug("node_health", node_id=node.id, state=health.state)
        await session.commit()
    await bus.kick_dispatch(ctx["redis"])  # NodeStatusChanged — без ожидания cron
    return len(nodes)


class WorkerSettings:
    functions: ClassVar[list[Function]] = [func(dispatch_events, keep_result=0)]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(dispatch_events, second=EVERY_5_SECONDS, keep_result=0),
        cron(purge_event_outbox, hour={4}, minute={0}, keep_result=0),
        cron(check_nodes, second={30}, keep_result=0),
    ]
    on_startup = startup
    on_shutdown = shutdown


def main() -> None:
    settings = get_settings()
    run_worker(
        WorkerSettings,  # type: ignore[arg-type]
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        ctx={"settings": settings},
    )


if __name__ == "__main__":
    main()
