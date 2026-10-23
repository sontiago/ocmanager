"""Реферальная программа: награды за первую оплату друга, уровни, отложенные дни.
Правила и числа — subscriptions/referral.py и спека 2026-10-23-promo-referrals-design."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Payment, Plan
from ocmanager.core.errors import InvalidTransition, SubscriptionInactive
from ocmanager.events import bus
from ocmanager.events.types import ReferralRewarded, ReferralTierReached
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client, ReferralReward
from ocmanager.subscriptions.referral import (
    INVITEE_DAYS,
    INVITER_DAYS,
    MONTHLY_CAP,
    parse_start_param,
    tiers_reached,
)
from ocmanager.subscriptions.state import PlanTerms

CAP_WINDOW = timedelta(days=30)
SYSTEM = Actor.system()


async def terms_for_client(session: AsyncSession, plan: Plan, client_id: int) -> PlanTerms:
    """Условия тарифа плюс постоянные бонусы клиента: так уровни не сгорают при продлении.
    Безлимитный по трафику тариф остаётся безлимитным."""
    client = await subscriptions.get_client(session, client_id)
    limit = plan.traffic_limit_bytes
    return PlanTerms(
        plan_id=plan.id,
        duration_days=plan.duration_days,
        device_limit=plan.device_limit + client.bonus_devices,
        traffic_limit_bytes=None if limit is None else limit + client.bonus_traffic_bytes,
        is_trial=plan.is_trial,
    )


async def _give_days(session: AsyncSession, client_id: int, days: int, now: datetime) -> bool:
    """Дни к подписке. False — сейчас нельзя (нет подписки, клиент заблокирован): награда
    подождёт, а не уронит обработку платежа."""
    try:
        async with session.begin_nested():
            await subscriptions.extend_days(session, client_id, days, now)
    except (InvalidTransition, SubscriptionInactive):
        return False
    return True


async def reward_first_payment(session: AsyncSession, payment_id: int, now: datetime) -> None:
    """Обработчик PaymentReceived. Идемпотентен: награда привязана к платежу уникальным
    индексом, а «первый» определяется по самому раннему зачтённому платежу друга."""
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.processed_at is None or payment.status != "succeeded":
        return
    friend = await subscriptions.get_client(session, payment.client_id)
    if friend.referred_by is None:
        return
    first_id = await session.scalar(
        select(func.min(Payment.id)).where(
            Payment.client_id == friend.id,
            Payment.processed_at.is_not(None),
            Payment.status == "succeeded",
        )
    )
    if first_id != payment.id or await subscriptions.reward_exists_for_payment(session, payment.id):
        return

    inviter_id = friend.referred_by
    async with session.begin_nested():  # всё или ничего: событие повторится целиком
        # Потолок и уровни считаются по журналу: без блокировки пригласившего два платежа его
        # друзей, пришедшие одновременно, оба увидели бы «девять из десяти». Порядок блокировок
        # безопасен: referred_by всегда указывает на более старого клиента, колец нет.
        await session.scalar(select(Client.id).where(Client.id == inviter_id).with_for_update())
        if await subscriptions.get_subscription(session, friend.id) is None:
            raise SubscriptionInactive("the friend has no subscription to reward")
        await subscriptions.extend_days(session, friend.id, INVITEE_DAYS, now)

        capped = await subscriptions.recent_base_rewards(session, inviter_id, now - CAP_WINDOW) >= (
            MONTHLY_CAP
        )
        days = 0 if capped else INVITER_DAYS
        applied = capped or await _give_days(session, inviter_id, days, now)
        reward = await subscriptions.add_reward(
            session,
            inviter_id=inviter_id,
            invitee_id=friend.id,
            payment_id=payment.id,
            kind="base",
            days=days,
            invitee_days=INVITEE_DAYS,
            status="capped" if capped else ("applied" if applied else "pending"),
            applied_at=now if applied else None,
        )
        await audit.record(
            session,
            SYSTEM,
            "referral.reward",
            target_type="client",
            target_id=str(inviter_id),
            details={
                "invitee_id": friend.id,
                "payment_id": payment.id,
                "inviter_days": days,
                "invitee_days": INVITEE_DAYS,
                "status": reward.status,
            },
        )
        await bus.record(session, ReferralRewarded(reward_id=reward.id))
        await _reward_tiers(session, inviter_id, friend.id, payment.id, now)


async def _reward_tiers(
    session: AsyncSession, inviter_id: int, invitee_id: int, payment_id: int, now: datetime
) -> None:
    friends = await subscriptions.paying_friends(session, inviter_id)
    for tier in tiers_reached(friends):
        if await subscriptions.tier_rewarded(session, inviter_id, tier.friends):
            continue
        if tier.devices or tier.traffic_bytes:
            await subscriptions.add_perks(
                session, inviter_id, devices=tier.devices, traffic_bytes=tier.traffic_bytes, now=now
            )
        applied = tier.days == 0 or await _give_days(session, inviter_id, tier.days, now)
        reward = await subscriptions.add_reward(
            session,
            inviter_id=inviter_id,
            invitee_id=invitee_id,
            payment_id=payment_id,
            kind="tier",
            tier=tier.friends,
            days=tier.days,
            devices=tier.devices,
            traffic_bytes=tier.traffic_bytes,
            status="applied" if applied else "pending",
            applied_at=now if applied else None,
        )
        await audit.record(
            session,
            SYSTEM,
            "referral.tier",
            target_type="client",
            target_id=str(inviter_id),
            details={
                "tier": tier.friends,
                "days": tier.days,
                "devices": tier.devices,
                "traffic_bytes": tier.traffic_bytes,
            },
        )
        await bus.record(session, ReferralTierReached(reward_id=reward.id))


async def apply_pending(session: AsyncSession, client_id: int, now: datetime) -> int:
    """Дни наград, которые ждали подписку. Вызывается при активации и продлении. Возвращает
    число начисленных дней."""
    rows: list[ReferralReward] = [
        r for r in await subscriptions.pending_rewards(session, client_id) if r.days > 0
    ]
    total = sum(r.days for r in rows)
    if total == 0 or not await _give_days(session, client_id, total, now):
        return 0
    for row in rows:
        row.status, row.applied_at = "applied", now
    await session.flush()
    return total


async def attach(session: AsyncSession, client_id: int, start_param: str | None) -> bool:
    """Привязывает нового клиента к пригласившему по start-параметру (`ref_<код>`). Вызывать
    только в момент создания клиента: уже существующего перепривязать нельзя. Мусор, неизвестный
    код и собственный код молча игнорируются."""
    code = parse_start_param(start_param)
    if code is None or not await subscriptions.set_referrer(session, client_id, code):
        return False
    client = await subscriptions.get_client(session, client_id)
    await audit.record(
        session,
        Actor("client", str(client_id)),
        "referral.attach",
        target_type="client",
        target_id=str(client_id),
        details={"inviter_id": client.referred_by},
    )
    return True
