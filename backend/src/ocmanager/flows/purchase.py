"""Покупка: вебхук провайдера → клиент, платёж, подписка.

Границу транзакции держит вызывающий (воркер): функции ничего не коммитят. Исход «мёртвый
вебхук» (`dead`) — возвращаемое значение, а не исключение (П5-8): платёж и запись о проблеме
обязаны сохраниться, иначе деньги получены, а следов нет. Исключение — это сбой инфраструктуры:
воркер откатывает всё и повторяет."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing import service as billing
from ocmanager.billing.models import WebhookEvent
from ocmanager.billing.providers.base import PaymentProvider, ProviderEvent, ProviderPayloadError
from ocmanager.core.errors import Conflict, InvalidTransition, NotFound, SubscriptionInactive
from ocmanager.events import bus
from ocmanager.events.types import (
    PaymentNeedsReview,
    PaymentReceived,
    PaymentRefunded,
    WebhookDeadLettered,
)
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.flows.clients import register_client
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.schemas import TelegramIdentity

log = structlog.get_logger(__name__)

Outcome = Literal["processed", "ignored", "dead", "skipped"]

PROCESSABLE = ("received", "failed")
REQUEUEABLE = ("failed", "dead")
STALE_AFTER = timedelta(seconds=60)
ERROR_LIMIT = 2000
ACTOR = Actor.system()


async def _close(
    session: AsyncSession, row: WebhookEvent, status: Literal["processed", "ignored"], now: datetime
) -> None:
    row.status = status
    row.processed_at = now
    row.last_error = None
    await session.flush()


async def _dead(session: AsyncSession, row: WebhookEvent, reason: str) -> Outcome:
    """Повтор не поможет: нужен человек. Вебхук остаётся в БД с причиной, админ видит его
    в разделе «Платежи» и переобрабатывает после исправления."""
    row.status = "dead"
    row.last_error = reason[:ERROR_LIMIT]
    await bus.record(session, WebhookDeadLettered(webhook_event_id=row.id))
    await audit.record(
        session,
        ACTOR,
        "webhook.dead",
        target_type="webhook",
        target_id=str(row.id),
        details={"reason": reason[:200]},
    )
    await session.flush()
    log.warning("webhook_dead", webhook_event_id=row.id, reason=reason)
    return "dead"


async def _client_for(session: AsyncSession, telegram_id: int) -> Client:
    """Оплатить можно, ни разу не открыв Mini App: тогда клиента создаём (П5-9)."""
    client = await subscriptions.find_client_by_telegram_id(session, telegram_id)
    if client is not None:
        return client
    ident = TelegramIdentity(
        telegram_id=telegram_id, first_name=str(telegram_id), username=None, language_code=None
    )
    return (await register_client(session, ident, actor=ACTOR)).client


async def process_webhook_event(
    session: AsyncSession,
    webhook_event_id: int,
    now: datetime,
    providers: Mapping[str, PaymentProvider],
) -> Outcome:
    # FOR UPDATE: два воркера с одним job не обработают событие дважды — второй дождётся
    # коммита первого, увидит статус processed и выйдет.
    row = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.id == webhook_event_id).with_for_update()
    )
    if row is None or row.status not in PROCESSABLE or not row.signature_ok:
        return "skipped"

    provider = providers.get(row.provider)
    if provider is None:
        return await _dead(session, row, f"provider {row.provider!r} is not configured")
    try:
        event = provider.parse(row.payload)
    except ProviderPayloadError as exc:
        return await _dead(session, row, f"unparseable payload: {exc}")

    if event.kind == "ignored":
        await _close(session, row, "ignored", now)
        return "ignored"
    if event.telegram_id is None:
        return await _dead(session, row, "payload has no telegram user id")

    if event.kind == "subscription_cancelled":
        return await _cancel(session, row, event.telegram_id, now)
    if event.kind == "refund":
        return await _refund(session, row, event, now)
    return await _pay(session, row, event, event.telegram_id, now)


async def _cancel(
    session: AsyncSession, row: WebhookEvent, telegram_id: int, now: datetime
) -> Outcome:
    """Отмена в Tribute — это auto_renew=false; доступ живёт до конца оплаченного срока."""
    client = await subscriptions.find_client_by_telegram_id(session, telegram_id)
    if client is not None:
        await subscription_flows.cancel_auto_renew(session, client.id, ACTOR)
    await _close(session, row, "processed", now)
    return "processed"


async def _refund(
    session: AsyncSession, row: WebhookEvent, event: ProviderEvent, now: datetime
) -> Outcome:
    """Возврат помечает платёж и зовёт человека; доступ не отнимается (П5-10)."""
    if event.external_payment_id is None:
        return await _dead(session, row, "refund has no payment id")
    refund = await billing.mark_refunded(session, row.provider, event.external_payment_id)
    if refund is None:
        return await _dead(session, row, "refund of an unknown payment")
    if refund.changed:
        payment = refund.payment
        await bus.record(
            session, PaymentRefunded(payment_id=payment.id, client_id=payment.client_id)
        )
        await audit.record(
            session,
            ACTOR,
            "payment.refund",
            target_type="client",
            target_id=str(payment.client_id),
            details={"payment_id": payment.id},
        )
    await _close(session, row, "processed", now)
    return "processed"


async def _pay(
    session: AsyncSession,
    row: WebhookEvent,
    event: ProviderEvent,
    telegram_id: int,
    now: datetime,
) -> Outcome:
    external_id, product_ref = event.external_payment_id, event.product_ref
    amount, currency = event.amount, event.currency
    if external_id is None or product_ref is None or amount is None or currency is None:
        return await _dead(
            session, row, "payload lacks payment fields (payment id, product, amount or currency)"
        )
    plan = await billing.find_plan_by_product(session, row.provider, product_ref)
    if plan is None:
        return await _dead(session, row, f"no plan is linked to product {product_ref!r}")

    client = await _client_for(session, telegram_id)
    payment = await billing.record_payment(
        session,
        provider=row.provider,
        external_id=external_id,
        client_id=client.id,
        plan_id=plan.id,
        amount=amount,
        currency=currency,
        payload=row.payload,
        now=now,
    )
    if payment is None:
        # Платёж уже был: либо зачтён (повторная доставка — выходим), либо записан, но доступ
        # не выдан (заблокированный клиент, П5-13) — тогда пробуем выдать ещё раз.
        payment = await billing.get_payment(session, row.provider, external_id)
        if payment.processed_at is not None:
            await _close(session, row, "processed", now)
            return "processed"

    terms = subscription_flows.terms_from_plan(plan)
    try:
        # SAVEPOINT: отказ подписки откатывает только её собственные записи, платёж остаётся.
        async with session.begin_nested():
            if event.kind == "subscription_started":
                sub = await subscription_flows.activate(
                    session,
                    client.id,
                    terms,
                    ACTOR,
                    now,
                    auto_renew=True,
                    provider=row.provider,
                    external_subscription_id=event.external_subscription_id,
                )
            else:
                sub = await subscription_flows.renew(
                    session,
                    client.id,
                    terms,
                    ACTOR,
                    now,
                    provider=row.provider,
                    external_subscription_id=event.external_subscription_id,
                )
    except (SubscriptionInactive, InvalidTransition) as exc:
        await bus.record(session, PaymentNeedsReview(payment_id=payment.id, client_id=client.id))
        return await _dead(
            session, row, f"payment {payment.id} recorded, access not granted: {exc.message}"
        )

    payment.subscription_id = sub.id
    payment.processed_at = now
    await bus.record(session, PaymentReceived(payment_id=payment.id, client_id=client.id))
    await audit.record(
        session,
        ACTOR,
        "payment.receive",
        target_type="client",
        target_id=str(client.id),
        details={
            "payment_id": payment.id,
            "provider": row.provider,
            "amount": amount,
            "currency": currency,
            "plan_code": plan.code,
        },
    )
    await _close(session, row, "processed", now)
    await session.flush()
    return "processed"


async def record_failure(
    session: AsyncSession, webhook_event_id: int, error: str, *, final: bool
) -> None:
    """Учёт неудачной попытки. Вызывается воркером в отдельной транзакции после отката.
    Уже обработанное или закрытое событие не трогаем: гонка двух воркеров не должна
    «воскрешать» его в failed."""
    row = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.id == webhook_event_id).with_for_update()
    )
    if row is None or row.status not in PROCESSABLE:
        return
    row.attempts += 1
    row.last_error = error[:ERROR_LIMIT]
    if final:
        row.status = "dead"
        await bus.record(session, WebhookDeadLettered(webhook_event_id=row.id))
        await audit.record(
            session,
            ACTOR,
            "webhook.dead",
            target_type="webhook",
            target_id=str(row.id),
            details={"attempts": row.attempts},
        )
    else:
        row.status = "failed"
    await session.flush()


async def requeue_webhook(
    session: AsyncSession, webhook_event_id: int, actor: Actor
) -> WebhookEvent:
    """Ручная переобработка из админки: `failed`/`dead` → `received`, попытки с нуля.
    Постановку в очередь делает вызывающий после коммита."""
    row = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.id == webhook_event_id).with_for_update()
    )
    if row is None:
        raise NotFound("webhook not found")
    if row.status not in REQUEUEABLE or not row.signature_ok:
        raise Conflict(f"webhook is {row.status}: nothing to reprocess")
    row.status = "received"
    row.attempts = 0
    row.last_error = None
    await audit.record(
        session,
        actor,
        "webhook.reprocess",
        target_type="webhook",
        target_id=str(row.id),
    )
    await session.flush()
    return row


async def stale_received(session: AsyncSession, now: datetime, *, limit: int = 100) -> list[int]:
    """Принятые, но не взятые в работу дольше минуты: постановка в очередь потерялась (упал
    Redis между записью и enqueue). Подхватывает cron-подметальщик воркера."""
    return list(
        await session.scalars(
            select(WebhookEvent.id)
            .where(
                WebhookEvent.status == "received",
                WebhookEvent.signature_ok,
                WebhookEvent.received_at < now - STALE_AFTER,
            )
            .order_by(WebhookEvent.id)
            .limit(limit)
        )
    )
