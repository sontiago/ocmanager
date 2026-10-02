from datetime import timedelta
from typing import Any

import pytest
from arq import ArqRedis, Retry
from conftest import MakePlan, MakeWebhook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps.worker import (
    WEBHOOK_MAX_TRIES,
    WorkerSettings,
    process_webhook,
    sweep_webhooks,
    webhook_retry_delay,
)
from ocmanager.billing import webhooks
from ocmanager.billing.models import Payment, WebhookEvent
from ocmanager.billing.providers import build_providers
from ocmanager.billing.testing import webhook_body
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events.models import EventOutbox
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.subscriptions import service as subscriptions

PRODUCT = {"tribute": {"product_ref": "2001"}}


@pytest.fixture
def ctx(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], redis: ArqRedis
) -> dict[str, Any]:
    return {"settings": settings, "sessionmaker": sessionmaker, "redis": redis, "job_try": 1}


async def accepted(session: AsyncSession, settings: Settings) -> int:
    provider = build_providers(settings)["tribute"]
    result = await webhooks.receive(
        session, provider, webhook_body("new_subscription"), verified=True
    )
    assert result.webhook_event_id is not None
    return result.webhook_event_id


async def queued(redis: ArqRedis, function: str) -> list[tuple[Any, ...]]:
    return [j.args for j in await redis.queued_jobs() if j.function == function]


async def reload(session: AsyncSession, event_id: int) -> WebhookEvent:
    row = await session.get(WebhookEvent, event_id)
    assert row is not None
    await session.refresh(row)
    return row


def test_the_job_is_registered_with_eight_tries_and_no_kept_result() -> None:
    [fn] = [f for f in WorkerSettings.functions if f.name == "process_webhook"]
    assert (fn.max_tries, fn.keep_result_s) == (WEBHOOK_MAX_TRIES, 0)
    assert WEBHOOK_MAX_TRIES == 8


def test_the_sweeper_runs_every_minute() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:sweep_webhooks"]
    assert (job.second, job.minute) == ({50}, None)


@pytest.mark.parametrize(
    ("job_try", "minutes"), [(1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (6, 32), (7, 60), (8, 60)]
)
def test_the_retry_pause_doubles_up_to_an_hour(job_try: int, minutes: int) -> None:
    assert webhook_retry_delay(job_try) == timedelta(minutes=minutes)


async def test_the_job_processes_the_webhook_and_kicks_the_event_dispatcher(
    session: AsyncSession, ctx: dict[str, Any], settings: Settings, make_plan: MakePlan
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await accepted(session, settings)

    assert await process_webhook(ctx, event_id) == "processed"
    assert (await reload(session, event_id)).status == "processed"
    assert await session.scalar(select(func.count()).select_from(Payment)) == 1
    assert await queued(ctx["redis"], "dispatch_events") == [()]  # без ожидания cron


async def test_a_crash_rolls_everything_back_and_asks_for_a_retry(
    session: AsyncSession,
    ctx: dict[str, Any],
    settings: Settings,
    make_plan: MakePlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await accepted(session, settings)

    async def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("db went away")

    monkeypatch.setattr(subscription_flows, "activate", crash)

    with pytest.raises(Retry) as first:
        await process_webhook(ctx, event_id)
    assert first.value.defer_score == 60_000  # минута, в миллисекундах

    row = await reload(session, event_id)
    assert (row.status, row.attempts) == ("failed", 1)
    assert "db went away" in (row.last_error or "")
    # Откат полный: ни платежа (он записывался до сбоя), ни клиента.
    assert await session.scalar(select(func.count()).select_from(Payment)) == 0
    assert await subscriptions.find_client_by_telegram_id(session, 7001) is None

    ctx["job_try"] = 2
    with pytest.raises(Retry) as second:
        await process_webhook(ctx, event_id)
    assert second.value.defer_score == 120_000
    assert (await reload(session, event_id)).attempts == 2


async def test_the_last_try_marks_the_webhook_dead(
    session: AsyncSession,
    ctx: dict[str, Any],
    settings: Settings,
    make_plan: MakePlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await accepted(session, settings)

    async def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("still down")

    monkeypatch.setattr(subscription_flows, "activate", crash)
    ctx["job_try"] = WEBHOOK_MAX_TRIES

    assert await process_webhook(ctx, event_id) == "dead"  # без Retry: попытки кончились
    row = await reload(session, event_id)
    assert (row.status, row.attempts) == ("dead", 1)
    assert "webhook.dead_lettered" in list(await session.scalars(select(EventOutbox.name)))


async def test_the_job_retries_a_failed_webhook_to_success(
    session: AsyncSession, ctx: dict[str, Any], settings: Settings, make_plan: MakePlan
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await accepted(session, settings)
    row = await reload(session, event_id)
    row.status, row.attempts = "failed", 3
    await session.flush()

    ctx["job_try"] = 4
    assert await process_webhook(ctx, event_id) == "processed"


async def test_the_sweeper_requeues_only_stale_received_webhooks(
    session: AsyncSession, ctx: dict[str, Any], make_webhook: MakeWebhook
) -> None:
    now = utcnow()
    stale = await make_webhook(status="received", received_at=now - timedelta(minutes=5))
    await make_webhook(status="received", received_at=now)
    await make_webhook(status="processed", received_at=now - timedelta(minutes=5))
    await make_webhook(status="failed", received_at=now - timedelta(minutes=5))

    assert await sweep_webhooks(ctx) == 1
    assert await queued(ctx["redis"], "process_webhook") == [(stale.id,)]

    # Минуту спустя событие всё ещё не взято: подметальщик не копит дубли в очереди.
    assert await sweep_webhooks(ctx) == 1
    assert await queued(ctx["redis"], "process_webhook") == [(stale.id,)]
