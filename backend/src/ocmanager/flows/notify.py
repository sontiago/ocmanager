"""Склейка notifications + доменные события: что и кому отправить.

Обработчики только кладут сообщения в outbox_messages — в транзакции доставки события,
без сети и без commit. Отправляет их cron воркера (notifications/tasks.py): так упавший
Telegram не откатывает и не ретраит доменное событие.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Payment, Plan, WebhookEvent
from ocmanager.core import settings_store
from ocmanager.core.clock import utcnow
from ocmanager.core.i18n import pick
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import (
    DeviceIssued,
    DeviceRevoked,
    NodeStatusChanged,
    PaymentNeedsReview,
    PaymentReceived,
    PaymentRefunded,
    SubscriptionActivated,
    SubscriptionExpired,
    WebhookDeadLettered,
    WebhookRejected,
)
from ocmanager.nodes.models import Node
from ocmanager.notifications import service as notifications
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.state import LIVE, Status

DOWN = ("offline", "degraded")
REASON_LIMIT = 300
REMINDER_WINDOW = timedelta(hours=1)


def money(amount: int, currency: str) -> str:
    """Минорные единицы → «199.00 RUB». Целочисленно: float для денег не используется."""
    return f"{amount // 100}.{amount % 100:02d} {currency}"


def day(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%d.%m.%Y")


def who(client: Client) -> str:
    name = f"@{client.username}" if client.username else client.first_name
    return f"{name} ({client.telegram_id})"


async def to_client(
    session: AsyncSession,
    client_id: int,
    template_key: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str,
) -> bool:
    """Заблокированному клиенту и несуществующему не пишем."""
    client = await session.get(Client, client_id)
    if client is None or client.is_blocked:
        return False
    return await notifications.enqueue(
        session,
        recipient_type="client",
        chat_id=client.telegram_id,
        template_key=template_key,
        lang=client.lang,
        payload=payload,
        dedupe_key=dedupe_key,
    )


async def to_admins(
    session: AsyncSession,
    template_key: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
) -> int:
    """Сообщение каждому из admin_chat_ids на языке по умолчанию. Список пуст — тишина."""
    runtime = await settings_store.load(session)
    queued = 0
    for chat_id in runtime.admin_chat_ids:
        queued += await notifications.enqueue(
            session,
            recipient_type="admin",
            chat_id=chat_id,
            template_key=template_key,
            lang=runtime.default_lang,
            payload=payload,
            dedupe_key=dedupe_key,
        )
    return queued


def register() -> None:
    """Вызывается один раз на процесс воркера, рядом с handlers.register. Явно, а не при
    импорте: иначе любой тест, импортировавший модуль, получил бы боевые обработчики."""

    @bus.on(SubscriptionActivated)
    async def trial_started(event: SubscriptionActivated, session: AsyncSession) -> None:
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is None or sub.status != Status.TRIAL:
            return  # оплаченную активацию объявит PaymentReceived
        await to_client(
            session,
            event.client_id,
            "trial_started",
            {"days": (sub.expires_at - sub.started_at).days, "expires": day(sub.expires_at)},
            dedupe_key=f"trial_started:client:{event.client_id}",
        )

    @bus.on(PaymentReceived)
    async def payment_received(event: PaymentReceived, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        plan = None if payment.plan_id is None else await session.get(Plan, payment.plan_id)
        plan_name = (pick(plan.name_i18n, client.lang) or plan.code) if plan else "—"
        amount = money(payment.amount, payment.currency)
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is not None:
            await to_client(
                session,
                event.client_id,
                "payment_accepted",
                {"amount": amount, "plan": plan_name, "expires": day(sub.expires_at)},
                dedupe_key=f"payment_accepted:payment:{payment.id}",
            )
        await to_admins(
            session,
            "payment_new",
            {"amount": amount, "client": who(client), "plan": plan_name},
            dedupe_key=f"payment_new:payment:{payment.id}",
        )

    @bus.on(PaymentRefunded)
    async def payment_refunded(event: PaymentRefunded, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        await to_admins(
            session,
            "refund",
            {"amount": money(payment.amount, payment.currency), "client": who(client)},
            dedupe_key=f"refund:payment:{payment.id}",
        )

    @bus.on(PaymentNeedsReview)
    async def payment_needs_review(event: PaymentNeedsReview, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        await to_admins(
            session,
            "payment_blocked_client",
            {"amount": money(payment.amount, payment.currency), "client": who(client)},
            dedupe_key=f"needs_review:payment:{payment.id}",
        )

    @bus.on(WebhookDeadLettered)
    async def webhook_dead(event: WebhookDeadLettered, session: AsyncSession) -> None:
        row = await session.get(WebhookEvent, event.webhook_event_id)
        if row is None:
            return
        await to_admins(
            session,
            "webhook_dead",
            {
                "provider": row.provider,
                "id": row.id,
                "reason": (row.last_error or "—")[:REASON_LIMIT],
            },
            dedupe_key=f"webhook_dead:{row.id}",
        )

    @bus.on(WebhookRejected)
    async def webhook_rejected(event: WebhookRejected, session: AsyncSession) -> None:
        row = await session.get(WebhookEvent, event.webhook_event_id)
        if row is None:
            return
        # Флуд подделанных вебхуков не должен стать флудом админу: один алерт в час на провайдера.
        bucket = utcnow().strftime("%Y%m%d%H")
        await to_admins(
            session,
            "webhook_bad_signature",
            {"provider": row.provider, "id": row.id},
            dedupe_key=f"bad_signature:{row.provider}:{bucket}",
        )

    @bus.on(NodeStatusChanged)
    async def node_status_changed(event: NodeStatusChanged, session: AsyncSession) -> None:
        node = await session.get(Node, event.node_id)
        if node is None:
            return
        if event.new in DOWN and event.old not in DOWN:
            await to_admins(session, "node_down", {"node": node.name, "state": event.new})
        elif event.new == "online" and event.old in DOWN:
            await to_admins(session, "node_up", {"node": node.name})

    @bus.on(DeviceIssued)
    async def device_issued(event: DeviceIssued, session: AsyncSession) -> None:
        device = await session.get(Device, event.device_id)
        if device is None:
            return
        await to_client(
            session,
            event.client_id,
            "device_issued",
            {"device": device.name},
            dedupe_key=f"device_issued:device:{device.id}",
        )

    @bus.on(DeviceRevoked)
    async def device_revoked(event: DeviceRevoked, session: AsyncSession) -> None:
        device = await session.get(Device, event.device_id)
        if device is None:
            return
        await to_client(
            session,
            event.client_id,
            "device_revoked",
            {"device": device.name},
            dedupe_key=f"device_revoked:device:{device.id}",
        )

    @bus.on(SubscriptionExpired)
    async def subscription_expired(event: SubscriptionExpired, session: AsyncSession) -> None:
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is None or Status(sub.status) in LIVE:
            return  # продлили, пока событие ждало очереди
        await to_client(
            session,
            event.client_id,
            "expired",
            {},
            dedupe_key=f"expired:client:{event.client_id}:{sub.expires_at.isoformat()}",
        )


async def enqueue_expiry_reminders(session: AsyncSession, now: datetime) -> int:
    """Напоминания «подписка скоро закончится». Запускается раз в час: окно длиной в час
    для каждого порога, так что одна подписка попадает в него один раз; dedupe_key страхует
    от повторного запуска и от сдвига расписания. Автопродление — без напоминания:
    продлится само."""
    runtime = await settings_store.load(session)
    live = [s.value for s in LIVE]
    queued = 0
    for days in runtime.expiry_reminder_days:
        threshold = now + timedelta(days=days)
        rows = await session.execute(
            select(Subscription, Client)
            .join(Client, Client.id == Subscription.client_id)
            .where(
                Subscription.status.in_(live),
                Subscription.auto_renew.is_(False),
                Subscription.expires_at >= threshold - REMINDER_WINDOW,
                Subscription.expires_at < threshold,
                Client.is_blocked.is_(False),
            )
        )
        for sub, client in rows:
            if sub.expires_at - sub.started_at <= timedelta(days=days):
                continue  # период короче порога: «осталось 3 дня» в первый же час — нелепость
            queued += await to_client(
                session,
                client.id,
                "expiring_soon",
                {"days": days, "expires": day(sub.expires_at)},
                dedupe_key=f"expiring:{client.id}:{sub.expires_at.date()}:{days}",
            )
    return queued


async def alert_stuck_events(session: AsyncSession, now: datetime) -> int:
    """События outbox, исчерпавшие попытки, сами не доставятся: нужен человек. Алерт — раз в сутки,
    пока они лежат."""
    stuck = await session.scalar(
        select(func.count())
        .select_from(EventOutbox)
        .where(EventOutbox.dispatched_at.is_(None), EventOutbox.attempts >= bus.MAX_ATTEMPTS)
    )
    if not stuck:
        return 0
    return await to_admins(
        session, "internal_stuck", {"count": stuck}, dedupe_key=f"internal_stuck:{now.date()}"
    )
