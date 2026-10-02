import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakeClient, MakePlan, MakeWebhook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing import plans as plan_service
from ocmanager.billing import webhooks
from ocmanager.billing.models import Payment, WebhookEvent
from ocmanager.billing.plans import PlanCreate
from ocmanager.billing.providers.base import PaymentProvider
from ocmanager.billing.providers.tribute import TributeProvider
from ocmanager.billing.testing import webhook_body
from ocmanager.core.config import Settings
from ocmanager.core.errors import Conflict, NotFound
from ocmanager.events.models import EventOutbox
from ocmanager.flows import purchase
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.subscriptions import service as subscriptions

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
ADMIN = Actor("admin", "1")
REFUNDED_PURCHASE = "purchase:78901"  # как в фикстуре digital_product_refund
PRODUCT = {"tribute": {"product_ref": "2001", "link": "https://t.me/tribute/app?startapp=s1"}}
TELEGRAM_ID = 7001  # как в фикстурах вебхуков


@pytest.fixture
def tribute(settings: Settings) -> TributeProvider:
    assert settings.tribute_api_key is not None
    return TributeProvider(settings.tribute_api_key.get_secret_value())


@pytest.fixture
def providers(tribute: TributeProvider) -> dict[str, PaymentProvider]:
    return {"tribute": tribute}


async def intake(
    session: AsyncSession, tribute: TributeProvider, body: bytes, *, verified: bool = True
) -> int:
    result = await webhooks.receive(session, tribute, body, verified=verified)
    assert result.webhook_event_id is not None
    return result.webhook_event_id


async def run(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    event_id: int,
    now: datetime = NOW,
) -> str:
    return await purchase.process_webhook_event(session, event_id, now, providers)


async def deliver(
    session: AsyncSession,
    tribute: TributeProvider,
    providers: dict[str, PaymentProvider],
    name: str,
    now: datetime = NOW,
    **overrides: Any,
) -> str:
    """Принять и сразу обработать вебхук по имени фикстуры."""
    return await run(
        session, providers, await intake(session, tribute, webhook_body(name, **overrides)), now
    )


async def events(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(EventOutbox.name).order_by(EventOutbox.id)))


async def payments(session: AsyncSession) -> list[Payment]:
    return list(await session.scalars(select(Payment).order_by(Payment.id)))


async def sub_of(session: AsyncSession, telegram_id: int = TELEGRAM_ID) -> Any:
    client = await subscriptions.find_client_by_telegram_id(session, telegram_id)
    assert client is not None
    return await subscriptions.get_subscription(session, client.id)


async def row_of(session: AsyncSession, event_id: int) -> WebhookEvent:
    row = await session.get(WebhookEvent, event_id)
    assert row is not None
    await session.refresh(row)
    return row


# --- оплата -----------------------------------------------------------------------------


async def test_a_new_client_pays_before_ever_opening_the_app(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    plan = await make_plan(provider_product_ids=PRODUCT)
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, providers, event_id) == "processed"

    client = await subscriptions.find_client_by_telegram_id(session, TELEGRAM_ID)
    assert client is not None
    assert client.first_name == str(TELEGRAM_ID)  # имя обновит первый заход в Mini App
    sub = await subscriptions.get_subscription(session, client.id)
    assert sub is not None
    assert (sub.status, sub.auto_renew, sub.provider, sub.plan_id) == (
        "active",
        True,
        "tribute",
        plan.id,
    )
    assert sub.external_subscription_id == "1001"
    assert sub.expires_at == NOW + timedelta(days=30)

    [payment] = await payments(session)
    assert (payment.amount, payment.currency, payment.status) == (19900, "RUB", "succeeded")
    assert (payment.client_id, payment.subscription_id, payment.plan_id) == (
        client.id,
        sub.id,
        plan.id,
    )
    assert payment.processed_at == NOW
    assert await events(session) == ["subscription.activated", "payment.received"]
    row = await row_of(session, event_id)
    assert (row.status, row.processed_at) == ("processed", NOW)


async def test_the_payment_is_audited(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(session, tribute, providers, "new_subscription")
    actions = list(await session.scalars(select(AuditLog.action).order_by(AuditLog.id)))
    assert "payment.receive" in actions
    assert "subscription.activate" in actions
    assert "client.create" in actions


async def test_processing_the_same_webhook_twice_pays_once(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, providers, event_id) == "processed"
    assert await run(session, providers, event_id, NOW + timedelta(days=1)) == "skipped"
    assert len(await payments(session)) == 1
    assert (await sub_of(session)).expires_at == NOW + timedelta(days=30)


async def test_a_different_webhook_for_the_same_payment_does_not_extend_twice(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    assert await deliver(session, tribute, providers, "new_subscription") == "processed"
    # Другие байты тела (а значит, другой идентификатор события), тот же платёж.
    again = await deliver(session, tribute, providers, "new_subscription", note="resend")
    assert again == "processed"
    assert len(await payments(session)) == 1
    assert (await sub_of(session)).expires_at == NOW + timedelta(days=30)
    assert (await events(session)).count("subscription.activated") == 1


async def test_a_renewal_adds_days_to_the_end_of_the_paid_period(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(session, tribute, providers, "new_subscription")
    later = NOW + timedelta(days=1)
    assert await deliver(session, tribute, providers, "renewed_subscription", later) == "processed"

    assert (await sub_of(session)).expires_at == NOW + timedelta(days=60)
    assert len(await payments(session)) == 2
    assert await events(session) == [
        "subscription.activated",
        "payment.received",
        "subscription.renewed",
        "payment.received",
    ]


async def test_cancelling_keeps_the_access_until_the_end_of_the_paid_period(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(session, tribute, providers, "new_subscription")
    assert await deliver(session, tribute, providers, "cancelled_subscription") == "processed"

    sub = await sub_of(session)
    assert (sub.status, sub.auto_renew) == ("cancelled", False)
    assert sub.expires_at == NOW + timedelta(days=30)
    assert await subscriptions.client_has_access(session, sub.client_id, NOW + timedelta(days=10))
    assert "subscription.auto_renew_cancelled" in await events(session)


async def test_cancelling_for_an_unknown_client_creates_nobody(
    session: AsyncSession, providers: dict[str, PaymentProvider], tribute: TributeProvider
) -> None:
    assert await deliver(session, tribute, providers, "cancelled_subscription") == "processed"
    assert await subscriptions.find_client_by_telegram_id(session, TELEGRAM_ID) is None


async def test_a_refund_marks_the_payment_and_leaves_the_access_to_a_human(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(session, tribute, providers, "new_subscription")
    # Возврат Tribute относится к покупке цифрового товара (purchase_id), а не к подписке.
    paid = (await payments(session))[0]
    paid.external_id = REFUNDED_PURCHASE
    await session.flush()
    assert await deliver(session, tribute, providers, "digital_product_refund") == "processed"

    [payment] = await payments(session)
    assert payment.status == "refunded"
    sub = await sub_of(session)
    assert sub.status == "active"
    assert await subscriptions.client_has_access(session, sub.client_id, NOW)
    assert (await events(session)).count("payment.refunded") == 1

    # Повторный возврат другим вебхуком новых событий не порождает.
    await deliver(session, tribute, providers, "digital_product_refund", note="resend")
    assert (await events(session)).count("payment.refunded") == 1


async def test_a_refund_of_an_unknown_payment_needs_a_human(
    session: AsyncSession, providers: dict[str, PaymentProvider], tribute: TributeProvider
) -> None:
    event_id = await intake(session, tribute, webhook_body("digital_product_refund"))
    assert await run(session, providers, event_id) == "dead"
    row = await row_of(session, event_id)
    assert (row.status, "unknown payment" in (row.last_error or "")) == ("dead", True)
    assert await events(session) == ["webhook.dead_lettered"]


# --- то, что идёт не так ----------------------------------------------------------------


async def test_a_blocked_client_payment_is_recorded_but_needs_review(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
    make_client: MakeClient,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    client = await make_client(telegram_id=TELEGRAM_ID)
    await subscription_flows.set_blocked(session, client.id, True, ADMIN, NOW)

    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, providers, event_id) == "dead"

    [payment] = await payments(session)  # деньги получены и записаны
    assert (payment.status, payment.subscription_id, payment.processed_at) == (
        "succeeded",
        None,
        None,
    )
    assert await subscriptions.get_subscription(session, client.id) is None  # доступа нет
    names = await events(session)
    assert "payment.needs_review" in names
    assert "webhook.dead_lettered" in names
    assert "payment.received" not in names
    row = await row_of(session, event_id)
    assert (row.status, "access not granted" in (row.last_error or "")) == ("dead", True)


async def test_reprocessing_after_the_unblock_grants_access_without_a_second_payment(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
    make_client: MakeClient,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    client = await make_client(telegram_id=TELEGRAM_ID)
    await subscription_flows.set_blocked(session, client.id, True, ADMIN, NOW)
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, providers, event_id) == "dead"

    later = NOW + timedelta(hours=2)
    await subscription_flows.set_blocked(session, client.id, False, ADMIN, later)
    await purchase.requeue_webhook(session, event_id, ADMIN)
    assert await run(session, providers, event_id, later) == "processed"

    [payment] = await payments(session)
    assert payment.processed_at == later
    sub = await subscriptions.get_subscription(session, client.id)
    assert sub is not None
    assert (sub.status, payment.subscription_id) == ("active", sub.id)
    assert sub.expires_at == later + timedelta(days=30)


async def test_an_unknown_product_goes_dead_and_creates_nobody(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids={"tribute": {"product_ref": "9999"}})
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, providers, event_id) == "dead"
    assert "product '2001'" in ((await row_of(session, event_id)).last_error or "")
    assert await payments(session) == []
    assert await subscriptions.find_client_by_telegram_id(session, TELEGRAM_ID) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"telegram_user_id": None}, "telegram user id"),
        ({"price": None, "amount": None}, "payment fields"),
        ({"currency": None}, "payment fields"),
        ({"subscription_id": None}, "payment fields"),
    ],
    ids=["no-telegram-id", "no-amount", "no-currency", "no-subscription-id"],
)
async def test_a_payload_without_the_essentials_goes_dead_with_a_reason(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
    overrides: dict[str, Any],
    reason: str,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await intake(session, tribute, webhook_body("new_subscription", **overrides))
    assert await run(session, providers, event_id) == "dead"
    assert reason in ((await row_of(session, event_id)).last_error or "")
    assert await payments(session) == []


async def test_an_unparseable_payload_goes_dead_with_a_reason(
    session: AsyncSession, providers: dict[str, PaymentProvider], tribute: TributeProvider
) -> None:
    event_id = await intake(session, tribute, b"this is not json")
    assert await run(session, providers, event_id) == "dead"
    assert "unparseable" in ((await row_of(session, event_id)).last_error or "")


async def test_a_fractional_amount_is_not_guessed_at(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    body = webhook_body("new_subscription", price=199.5)
    event_id = await intake(session, tribute, body)
    assert await run(session, providers, event_id) == "dead"
    assert await payments(session) == []


async def test_an_event_we_do_not_need_is_closed_as_ignored(
    session: AsyncSession, providers: dict[str, PaymentProvider], tribute: TributeProvider
) -> None:
    event_id = await intake(session, tribute, webhook_body("new_donation"))
    assert await run(session, providers, event_id) == "ignored"
    assert (await row_of(session, event_id)).status == "ignored"


async def test_a_provider_that_is_not_configured_goes_dead(
    session: AsyncSession, tribute: TributeProvider
) -> None:
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    assert await run(session, {}, event_id) == "dead"


async def test_a_rejected_webhook_is_never_processed(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await intake(session, tribute, webhook_body("new_subscription"), verified=False)
    assert await run(session, providers, event_id) == "skipped"
    assert (await row_of(session, event_id)).status == "rejected"
    assert await payments(session) == []
    assert await subscriptions.find_client_by_telegram_id(session, TELEGRAM_ID) is None


async def test_an_unknown_webhook_id_is_skipped(
    session: AsyncSession, providers: dict[str, PaymentProvider]
) -> None:
    assert await run(session, providers, 999_999_999) == "skipped"


# --- сбои, ретраи, переобработка --------------------------------------------------------


async def test_a_failure_is_counted_and_the_last_one_buries_the_webhook(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    event_id = await intake(session, tribute, webhook_body("new_subscription"))

    await purchase.record_failure(session, event_id, "boom", final=False)
    row = await row_of(session, event_id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "boom")

    # failed — не тупик: повторная доставка job его обработает.
    assert await run(session, providers, event_id) == "processed"

    await purchase.record_failure(session, event_id, "late boom", final=True)
    assert (await row_of(session, event_id)).status == "processed"  # уже обработанное не трогаем


async def test_the_final_failure_marks_the_webhook_dead_and_tells_the_admin(
    session: AsyncSession, tribute: TributeProvider
) -> None:
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    await purchase.record_failure(session, event_id, "one", final=False)
    await purchase.record_failure(session, event_id, "two", final=True)
    row = await row_of(session, event_id)
    assert (row.status, row.attempts, row.last_error) == ("dead", 2, "two")
    assert await events(session) == ["webhook.dead_lettered"]


async def test_a_long_error_is_cut(session: AsyncSession, tribute: TributeProvider) -> None:
    event_id = await intake(session, tribute, webhook_body("new_subscription"))
    await purchase.record_failure(session, event_id, "x" * 10_000, final=False)
    assert len((await row_of(session, event_id)).last_error or "") == purchase.ERROR_LIMIT


async def test_reprocessing_resets_a_dead_webhook_and_is_audited(
    session: AsyncSession, make_webhook: MakeWebhook
) -> None:
    row = await make_webhook(status="dead", attempts=8, last_error="no plan")
    back = await purchase.requeue_webhook(session, row.id, ADMIN)
    assert (back.status, back.attempts, back.last_error) == ("received", 0, None)
    [entry] = list(
        await session.scalars(select(AuditLog).where(AuditLog.action == "webhook.reprocess"))
    )
    assert (entry.actor_type, entry.target_type, entry.target_id) == (
        "admin",
        "webhook",
        str(row.id),
    )


@pytest.mark.parametrize("status", ["processed", "ignored", "received", "rejected"])
async def test_only_failed_and_dead_webhooks_can_be_reprocessed(
    session: AsyncSession, make_webhook: MakeWebhook, status: str
) -> None:
    row = await make_webhook(status=status, signature_ok=status != "rejected")
    with pytest.raises(Conflict):
        await purchase.requeue_webhook(session, row.id, ADMIN)


async def test_reprocessing_an_unknown_webhook_is_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await purchase.requeue_webhook(session, 999_999_999, ADMIN)


async def test_the_sweeper_sees_only_old_received_webhooks(
    session: AsyncSession, make_webhook: MakeWebhook
) -> None:
    old = NOW - timedelta(minutes=5)
    stale = await make_webhook(status="received", received_at=old)
    await make_webhook(status="received", received_at=NOW - timedelta(seconds=10))
    await make_webhook(status="processed", received_at=old)
    await make_webhook(status="failed", received_at=old)
    await make_webhook(status="rejected", received_at=old, signature_ok=False)
    assert await purchase.stale_received(session, NOW) == [stale.id]


# --- конкуренция ------------------------------------------------------------------------


async def test_two_workers_taking_the_same_webhook_pay_once(
    committed_sessionmaker: async_sessionmaker[AsyncSession], tribute: TributeProvider
) -> None:
    async with committed_sessionmaker() as s:
        await plan_service.create_plan(
            s,
            PlanCreate(
                code="month",
                name_i18n={"ru": "Месяц", "en": "Month"},
                duration_days=30,
                device_limit=3,
                price_amount=19900,
                currency="RUB",
                provider_product_ids=PRODUCT,
            ),
        )
        event_id = await intake(s, tribute, webhook_body("new_subscription"))
        await s.commit()

    async def worker() -> str:
        async with committed_sessionmaker() as s:
            outcome = await purchase.process_webhook_event(s, event_id, NOW, {"tribute": tribute})
            await s.commit()
            return outcome

    results = await asyncio.gather(worker(), worker())
    assert sorted(results) == ["processed", "skipped"]
    async with committed_sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(Payment)) == 1


# --- доступ не короче оплаченного периода провайдера -------------------------------------


async def test_access_lasts_until_the_end_of_the_period_tribute_charged_for(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    """Календарный месяц Tribute длиннее 30 дней тарифа: без этого — сутки без доступа."""
    await make_plan(provider_product_ids=PRODUCT)
    end = "2026-11-02T12:10:29.764107373Z"  # NOW + 32 дня
    assert (
        await deliver(session, tribute, providers, "new_subscription", expires_at=end)
        == "processed"
    )

    sub = await sub_of(session)
    assert sub.expires_at == datetime(2026, 11, 2, 12, 10, 29, 764107, tzinfo=UTC)
    actions = list(await session.scalars(select(AuditLog.action).order_by(AuditLog.id)))
    assert "subscription.sync_period" in actions


async def test_a_period_that_ends_sooner_than_the_plan_never_shortens_the_access(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(
        session, tribute, providers, "new_subscription", expires_at="2026-10-05T00:00:00Z"
    )
    assert (await sub_of(session)).expires_at == NOW + timedelta(days=30)
    actions = list(await session.scalars(select(AuditLog.action)))
    assert "subscription.sync_period" not in actions


async def test_a_renewal_also_follows_the_calendar_month(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(session, tribute, providers, "new_subscription")  # конец у нас — NOW + 30 дн
    later = NOW + timedelta(days=30)  # платёж пришёл ровно в конце нашего доступа
    end = later + timedelta(days=31)  # у Tribute месяц длиннее
    assert (
        await deliver(
            session, tribute, providers, "renewed_subscription", later, expires_at=end.isoformat()
        )
        == "processed"
    )
    assert (await sub_of(session)).expires_at == end


async def test_a_nonsense_period_end_is_ignored_and_the_plan_term_applies(
    session: AsyncSession,
    providers: dict[str, PaymentProvider],
    tribute: TributeProvider,
    make_plan: MakePlan,
) -> None:
    await make_plan(provider_product_ids=PRODUCT)
    await deliver(
        session, tribute, providers, "new_subscription", expires_at="2999-01-01T00:00:00Z"
    )
    assert (await sub_of(session)).expires_at == NOW + timedelta(days=30)
