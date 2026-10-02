"""Процесс worker: очередь arq и cron.

Запуск: `uv run python -m ocmanager.apps.worker`.
Каждая задача, добавляющая cron, дописывает его в WorkerSettings.cron_jobs
и в test_worker.py::test_cron_registry — иначе тест падает.
"""

import logging
from datetime import timedelta
from typing import Any, ClassVar

import httpx
import structlog
from arq import Retry, cron, func, run_worker
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.worker import Function

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.billing.providers import build_providers
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.logging import configure_logging
from ocmanager.events import bus
from ocmanager.flows import handlers
from ocmanager.flows import notify as notify_flows
from ocmanager.flows import purchase as purchase_flows
from ocmanager.flows import reconcile as reconcile_flows
from ocmanager.flows import revocations as revocation_flows
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.flows import traffic as traffic_flows
from ocmanager.flows.nodes import check_node_health
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.notifications import tasks as notification_tasks
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca

log = structlog.get_logger(__name__)

EVERY_5_SECONDS = set(range(0, 60, 5))
WEBHOOK_MAX_TRIES = 8
WEBHOOK_MAX_DELAY = timedelta(hours=1)


async def startup(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx.get("settings") or get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)
    # arq пишет две INFO-строки на каждый запуск cron (≈35 тыс. в сутки);
    # ошибки задач он логирует уровнем выше и их мы видим.
    logging.getLogger("arq.worker").setLevel(logging.WARNING)
    engine = make_engine(settings.database_url)
    ctx.update(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        http=httpx.AsyncClient(timeout=httpx.Timeout(10.0)),
    )
    handlers.register(settings)
    notify_flows.register()
    log.info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()
    await ctx["engine"].dispose()
    log.info("worker_stopped")


def get_ca(ctx: dict[str, Any]) -> CertificateAuthority:
    """CA читается при первом обращении, а не при старте: воркер без ca.key (CI, тесты)
    должен запускаться, а падать — только задача, которой ключ нужен."""
    ca: CertificateAuthority | None = ctx.get("ca")
    if ca is None:
        ca = ctx["ca"] = load_ca(ctx["settings"].pki_dir)
    return ca


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


async def send_outbox(ctx: dict[str, Any]) -> int:
    """Уведомления из очереди — в Telegram. Раз в 5 секунд, не больше 50 за запуск."""
    sent = await notification_tasks.send_pending(
        ctx["sessionmaker"], ctx["http"], ctx["settings"].bot_token.get_secret_value()
    )
    if sent:
        log.info("notifications_sent", count=sent)
    return sent


async def expiry_reminders(ctx: dict[str, Any]) -> int:
    """Напоминания об истечении — раз в час."""
    async with ctx["sessionmaker"]() as session:
        queued = await notify_flows.enqueue_expiry_reminders(session, utcnow())
        await session.commit()
    if queued:
        log.info("expiry_reminders_queued", count=queued)
    return queued


async def alert_stuck_events(ctx: dict[str, Any]) -> int:
    """Недоставленные события доменной шины — алерт админу раз в сутки."""
    async with ctx["sessionmaker"]() as session:
        queued = await notify_flows.alert_stuck_events(session, utcnow())
        await session.commit()
    return queued


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


async def expire_subscriptions(ctx: dict[str, Any]) -> int:
    """Истёкшие подписки → expired; обработчики событий уберут доступ на ноде."""
    async with ctx["sessionmaker"]() as session:
        client_ids = await subscription_flows.expire_due(session, utcnow())
        await session.commit()
    if client_ids:
        log.info("subscriptions_expired", count=len(client_ids))
        await bus.kick_dispatch(ctx["redis"])
    return len(client_ids)


async def apply_revocations(ctx: dict[str, Any]) -> int:
    """Отзывы → CRL на ноде. Недоступная нода — не ошибка задачи: повторим через 30 секунд."""
    async with ctx["sessionmaker"]() as session:
        try:
            applied = await revocation_flows.apply_revocations(
                session, ctx["settings"], get_ca(ctx), utcnow()
            )
        except NodeUnreachable as exc:
            log.warning("revocations_not_applied", error=str(exc))
            return 0
        await session.commit()
    if applied:
        log.info("revocations_applied", count=applied)
    return applied


async def refresh_crl(ctx: dict[str, Any]) -> None:
    async with ctx["sessionmaker"]() as session:
        await revocation_flows.refresh_crl(session, ctx["settings"], get_ca(ctx), utcnow())
    log.info("crl_refreshed")


async def reconcile_nodes(ctx: dict[str, Any]) -> int:
    """Сверка нод с БД раз в 5 минут. Возвращает число найденных дрейфов."""
    async with ctx["sessionmaker"]() as session:
        reports = await reconcile_flows.reconcile_all(
            session, ctx["settings"], get_ca(ctx), utcnow()
        )
        await session.commit()
    return sum(len(r.drifts) for r in reports)


async def collect_traffic(ctx: dict[str, Any]) -> int:
    """Опрос сессий раз в 5 минут: дельты трафика и расход по подпискам."""
    async with ctx["sessionmaker"]() as session:
        results = await traffic_flows.collect_traffic(session, ctx["settings"], utcnow())
        await session.commit()
    return sum(r.seen for r in results.values())


async def purge_traffic(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session:
        deleted = await traffic_flows.purge_samples(session, utcnow())
        await session.commit()
    if deleted:
        log.info("traffic_samples_purged", deleted=deleted)
    return deleted


def webhook_retry_delay(job_try: int) -> timedelta:
    """1, 2, 4, 8, 16, 32 минуты, дальше — час: Tribute сам ретраит около суток, нам хватает
    окна, чтобы пережить недоступность БД или баг, исправленный релизом."""
    return min(timedelta(minutes=2 ** (job_try - 1)), WEBHOOK_MAX_DELAY)


async def process_webhook(ctx: dict[str, Any], webhook_event_id: int) -> str:
    """Обработка принятого вебхука. Сбой откатывает всё, учитывает попытку и просит arq
    повторить; после последней попытки вебхук становится dead (событие уходит админу)."""
    job_try: int = ctx.get("job_try", 1)
    providers = build_providers(ctx["settings"])
    try:
        async with ctx["sessionmaker"]() as session:
            outcome = await purchase_flows.process_webhook_event(
                session, webhook_event_id, utcnow(), providers
            )
            await session.commit()
    except Exception as exc:
        final = job_try >= WEBHOOK_MAX_TRIES
        async with ctx["sessionmaker"]() as session:
            await purchase_flows.record_failure(
                session, webhook_event_id, f"{type(exc).__name__}: {exc}", final=final
            )
            await session.commit()
        log.warning(
            "webhook_failed",
            webhook_event_id=webhook_event_id,
            job_try=job_try,
            dead=final,
            exc_info=exc,
        )
        if final:
            await bus.kick_dispatch(ctx["redis"])
            return "dead"
        raise Retry(defer=webhook_retry_delay(job_try)) from exc
    log.info("webhook_processed", webhook_event_id=webhook_event_id, outcome=outcome)
    await bus.kick_dispatch(ctx["redis"])  # события subscription.* / payment.* — без ожидания cron
    return outcome


async def sweep_webhooks(ctx: dict[str, Any]) -> int:
    """Принятые вебхуки, которые минуту спустя всё ещё не в работе (Redis лёг между записью и
    постановкой в очередь), ставятся в очередь заново. `_job_id` не даёт копить дубли."""
    async with ctx["sessionmaker"]() as session:
        stale = await purchase_flows.stale_received(session, utcnow())
    for webhook_event_id in stale:
        await ctx["redis"].enqueue_job(
            "process_webhook", webhook_event_id, _job_id=f"webhook:{webhook_event_id}"
        )
    if stale:
        log.warning("webhooks_requeued", count=len(stale))
    return len(stale)


class WorkerSettings:
    functions: ClassVar[list[Function]] = [
        func(dispatch_events, keep_result=0),
        func(process_webhook, max_tries=WEBHOOK_MAX_TRIES, keep_result=0),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(dispatch_events, second=EVERY_5_SECONDS, keep_result=0),
        cron(purge_event_outbox, hour={4}, minute={0}, keep_result=0),
        cron(send_outbox, second=EVERY_5_SECONDS, keep_result=0),
        cron(expiry_reminders, minute={0}, second={5}, keep_result=0),
        cron(alert_stuck_events, hour={9}, minute={0}, second={10}, keep_result=0),
        cron(check_nodes, second={30}, keep_result=0),
        cron(expire_subscriptions, second={10}, keep_result=0),
        cron(apply_revocations, second={15, 45}, keep_result=0),
        cron(refresh_crl, hour={3}, minute={0}, keep_result=0),
        cron(collect_traffic, minute=set(range(0, 60, 5)), second={20}, keep_result=0),
        cron(purge_traffic, hour={4}, minute={30}, keep_result=0),
        cron(reconcile_nodes, minute=set(range(0, 60, 5)), second={40}, keep_result=0),
        cron(sweep_webhooks, second={50}, keep_result=0),
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
