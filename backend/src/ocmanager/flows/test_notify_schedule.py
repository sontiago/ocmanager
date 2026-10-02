from datetime import UTC, datetime, timedelta

from conftest import MakeClient, MakeSubscription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.flows import notify
from ocmanager.notifications.models import OutboxMessage
from ocmanager.subscriptions.models import Client, Subscription

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
DAY = timedelta(days=1)


async def expiring(
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    *,
    expires_in: timedelta,
    period: timedelta = 30 * DAY,
    auto_renew: bool = False,
    **client: object,
) -> tuple[Client, Subscription]:
    """Живая подписка, которая закончится через `expires_in`, при периоде `period`."""
    who = await make_client(**client)
    sub = await make_subscription(who, days=30, now=NOW, auto_renew=auto_renew)
    sub.expires_at = NOW + expires_in
    sub.started_at = sub.expires_at - period
    sub.auto_renew = auto_renew
    return who, sub


async def messages(session: AsyncSession) -> list[OutboxMessage]:
    return list(await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


async def test_a_reminder_goes_out_inside_the_window(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    client, _ = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )

    assert await notify.enqueue_expiry_reminders(session, NOW) == 1

    [message] = await messages(session)
    assert (message.recipient_type, message.chat_id, message.template_key, message.lang) == (
        "client",
        client.telegram_id,
        "expiring_soon",
        "ru",
    )
    assert message.payload == {"days": 3, "expires": "05.10.2026"}


async def test_hourly_runs_remind_once_per_threshold(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30))

    total = 0
    for hour in range(0, 80):  # больше трёх суток почасовых запусков
        total += await notify.enqueue_expiry_reminders(session, NOW + timedelta(hours=hour))

    assert total == 2  # «за 3 дня» и «за 1 день», ни одного повтора


async def test_running_the_same_window_twice_is_harmless(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30))
    assert await notify.enqueue_expiry_reminders(session, NOW) == 1
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_outside_the_window_nothing_is_sent(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY + timedelta(minutes=1))
    before_window = 3 * DAY - timedelta(hours=1, minutes=1)
    await expiring(make_client, make_subscription, expires_in=before_window)
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_auto_renewing_subscriptions_get_no_reminder(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        auto_renew=True,
    )
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_a_blocked_client_gets_no_reminder(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    client, _ = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )
    client.is_blocked = True
    await session.flush()
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_a_short_trial_skips_the_reminder_longer_than_itself(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    # Триал на 3 дня, только что начался: «осталось 3 дня» — нелепость. «Остался 1 день» — к месту.
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        period=3 * DAY,
    )
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0

    assert await notify.enqueue_expiry_reminders(session, NOW + 2 * DAY) == 1
    [message] = await messages(session)
    assert message.payload["days"] == 1


async def test_expired_subscriptions_are_not_reminded(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    _, sub = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )
    sub.status = "expired"
    await session.flush()
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_an_english_client_is_reminded_in_english(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        language_code="en",
    )
    await notify.enqueue_expiry_reminders(session, NOW)
    [message] = await messages(session)
    assert message.lang == "en"


async def test_the_thresholds_come_from_the_runtime_settings(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await settings_store.update(session, {"expiry_reminder_days": [7]})
    await expiring(make_client, make_subscription, expires_in=7 * DAY - timedelta(minutes=30))
    assert await notify.enqueue_expiry_reminders(session, NOW) == 1
    [message] = await messages(session)
    assert message.payload["days"] == 7


async def test_stuck_events_alert_the_admins_once_a_day(session: AsyncSession) -> None:
    await settings_store.update(session, {"admin_chat_ids": [111]})
    session.add(
        EventOutbox(
            name="client.blocked",
            payload={"client_id": 1},
            available_at=NOW,
            attempts=bus.MAX_ATTEMPTS,
            last_error="boom",
        )
    )
    await session.flush()

    assert await notify.alert_stuck_events(session, NOW) == 1
    assert await notify.alert_stuck_events(session, NOW + timedelta(hours=5)) == 0
    assert await notify.alert_stuck_events(session, NOW + DAY) == 1

    first, _ = await messages(session)
    assert (first.template_key, first.payload) == ("internal_stuck", {"count": 1})


async def test_no_stuck_events_no_alert(session: AsyncSession) -> None:
    await settings_store.update(session, {"admin_chat_ids": [111]})
    session.add(
        EventOutbox(name="client.blocked", payload={"client_id": 1}, available_at=NOW, attempts=3)
    )
    await session.flush()
    assert await notify.alert_stuck_events(session, NOW) == 0
