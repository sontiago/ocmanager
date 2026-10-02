from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from conftest import MakeClient, MakeDevice, MakePayment, MakePlan, MakeSubscription, MakeWebhook
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core import settings_store
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import (
    DeviceIssued,
    DeviceRevoked,
    DomainEvent,
    NodeStatusChanged,
    PaymentNeedsReview,
    PaymentReceived,
    PaymentRefunded,
    SubscriptionActivated,
    SubscriptionExpired,
    WebhookDeadLettered,
    WebhookRejected,
)
from ocmanager.flows import notify
from ocmanager.nodes.models import Node
from ocmanager.notifications.models import OutboxMessage

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture(autouse=True)
def _notify_handlers(_isolated_event_handlers: None) -> None:
    """Зависимость от фикстуры conftest гарантирует порядок: сначала снимок реестра шины,
    потом наша регистрация — и она не утечёт в соседние тесты."""
    notify.register()


async def deliver(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], event: DomainEvent
) -> None:
    # События, порождённые подготовкой данных (activate и т. п.), не предмет теста.
    await session.execute(delete(EventOutbox))
    await bus.record(session, event)
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1  # 0 — обработчик упал


async def queued(session: AsyncSession) -> list[tuple[str, int, str, str]]:
    rows = await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))
    return [(m.recipient_type, m.chat_id, m.template_key, m.lang) for m in rows]


async def messages(session: AsyncSession) -> list[OutboxMessage]:
    return list(await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


async def set_admins(session: AsyncSession, *chat_ids: int) -> None:
    await settings_store.update(session, {"admin_chat_ids": list(chat_ids)})


def test_money_is_formatted_without_floats() -> None:
    assert notify.money(19900, "RUB") == "199.00 RUB"
    assert notify.money(5, "USD") == "0.05 USD"
    assert notify.money(0, "EUR") == "0.00 EUR"


def test_day_is_utc_date() -> None:
    assert notify.day(datetime(2026, 11, 1, 23, 30, tzinfo=UTC)) == "01.11.2026"


# --- платежи -----------------------------------------------------------------


async def test_a_payment_notifies_the_client_and_every_admin(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client(username="anna", language_code="ru")
    plan = await make_plan(name_i18n={"ru": "Месяц", "en": "Month"})
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client, plan_id=plan.id, amount=19900)
    await set_admins(session, 111, 222)

    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)

    assert await queued(session) == [
        ("client", client.telegram_id, "payment_accepted", "ru"),
        ("admin", 111, "payment_new", "ru"),
        ("admin", 222, "payment_new", "ru"),
    ]
    first, second, _ = await messages(session)
    assert first.payload == {"amount": "199.00 RUB", "plan": "Месяц", "expires": "01.11.2026"}
    assert second.payload == {
        "amount": "199.00 RUB",
        "client": f"@anna ({client.telegram_id})",
        "plan": "Месяц",
    }


async def test_the_same_payment_event_twice_queues_one_message(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)
    await set_admins(session, 111)
    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)
    await deliver(session, sessionmaker, event)

    assert len(await queued(session)) == 2  # клиенту одно и админу одно, а не по два


async def test_an_english_client_gets_english_and_the_english_plan_name(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client(language_code="en")
    plan = await make_plan(name_i18n={"ru": "Месяц", "en": "Month"})
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client, plan_id=plan.id)

    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)

    [message] = await messages(session)  # админов не настроено — только клиент
    assert (message.template_key, message.lang) == ("payment_accepted", "en")
    assert message.payload["plan"] == "Month"


async def test_a_payment_without_a_plan_shows_a_dash(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)  # plan_id=None

    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)

    [message] = await messages(session)
    assert message.payload["plan"] == "—"


async def test_a_blocked_client_gets_no_client_messages_but_admins_still_hear(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)
    client.is_blocked = True
    await session.flush()
    await set_admins(session, 111)

    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)

    assert await queued(session) == [("admin", 111, "payment_new", "ru")]


async def test_a_refund_and_a_blocked_payment_alert_the_admins_only(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    payment = await make_payment(client, amount=500, currency="USD")
    await set_admins(session, 111)

    event = PaymentRefunded(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)
    await deliver(
        session, sessionmaker, PaymentNeedsReview(payment_id=payment.id, client_id=client.id)
    )

    assert await queued(session) == [
        ("admin", 111, "refund", "ru"),
        ("admin", 111, "payment_blocked_client", "ru"),
    ]
    refund, _ = await messages(session)
    assert refund.payload["amount"] == "5.00 USD"


# --- вебхуки -----------------------------------------------------------------


async def test_a_dead_webhook_alerts_the_admins_with_the_reason(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_webhook: MakeWebhook,
) -> None:
    webhook = await make_webhook(status="dead", last_error="no plan for product 7")
    await set_admins(session, 111)

    await deliver(session, sessionmaker, WebhookDeadLettered(webhook_event_id=webhook.id))

    [message] = await messages(session)
    assert message.template_key == "webhook_dead"
    assert message.payload == {
        "provider": "tribute",
        "id": webhook.id,
        "reason": "no plan for product 7",
    }


async def test_bad_signature_alerts_are_throttled_to_one_per_hour(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_webhook: MakeWebhook,
) -> None:
    first = await make_webhook(status="rejected", signature_ok=False)
    second = await make_webhook(status="rejected", signature_ok=False)
    await set_admins(session, 111, 222)

    await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=first.id))
    await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=second.id))
    assert len(await queued(session)) == 2  # по одному на админа, не по два

    with time_machine.travel(NOW + timedelta(hours=1), tick=False):
        await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=second.id))
    assert len(await queued(session)) == 4


# --- нода --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("online", "offline", "node_down"),
        ("online", "degraded", "node_down"),
        ("unknown", "offline", "node_down"),
        ("offline", "online", "node_up"),
        ("degraded", "online", "node_up"),
        ("degraded", "offline", None),
        ("offline", "degraded", None),
        ("unknown", "online", None),
    ],
)
async def test_node_transitions(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    old: str,
    new: str,
    expected: str | None,
) -> None:
    node = Node(name="local", driver="local_docker", public_host="vpn.example.com")
    session.add(node)
    await session.flush()
    await set_admins(session, 111)

    await deliver(session, sessionmaker, NodeStatusChanged(node_id=node.id, old=old, new=new))

    sent = await messages(session)
    if expected is None:
        assert sent == []
    else:
        [message] = sent
        assert message.template_key == expected
        assert message.payload["node"] == "local"


# --- устройства и подписка ---------------------------------------------------


async def test_device_events_notify_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    device = await make_device(client, seq=1)

    await deliver(session, sessionmaker, DeviceIssued(client_id=client.id, device_id=device.id))
    await deliver(
        session,
        sessionmaker,
        DeviceRevoked(client_id=client.id, device_id=device.id, username=device.ocserv_username),
    )

    assert await queued(session) == [
        ("client", client.telegram_id, "device_issued", "ru"),
        ("client", client.telegram_id, "device_revoked", "ru"),
    ]
    issued, _ = await messages(session)
    assert issued.payload == {"device": "dev1"}


async def test_a_trial_activation_greets_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, days=3, now=NOW)
    sub.status = "trial"
    await session.flush()

    await deliver(session, sessionmaker, SubscriptionActivated(client_id=client.id))

    [message] = await messages(session)
    assert message.template_key == "trial_started"
    assert message.payload == {"days": 3, "expires": "05.10.2026"}


async def test_a_paid_activation_is_silent(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)  # статус active

    await deliver(session, sessionmaker, SubscriptionActivated(client_id=client.id))

    assert await queued(session) == []  # об оплате расскажет PaymentReceived


async def test_expiry_tells_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, days=30, now=NOW)
    sub.status = "expired"
    await session.flush()

    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))
    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))

    assert await queued(session) == [("client", client.telegram_id, "expired", "ru")]


async def test_expired_is_silent_if_the_subscription_was_renewed_meanwhile(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)  # живая: событие устарело

    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))

    assert await queued(session) == []


async def test_expired_is_silent_for_a_client_without_a_subscription(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
) -> None:
    client = await make_client()
    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))
    assert await queued(session) == []
