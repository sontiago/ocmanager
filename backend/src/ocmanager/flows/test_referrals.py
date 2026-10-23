from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakeClient, MakePayment, MakePlan
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.errors import SubscriptionInactive
from ocmanager.events.models import EventOutbox
from ocmanager.flows import referrals
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client, ReferralReward
from ocmanager.subscriptions.referral import GIB, INVITEE_DAYS, INVITER_DAYS
from ocmanager.subscriptions.state import PlanTerms

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
DAY = timedelta(days=1)


def terms(plan: Any, **over: Any) -> PlanTerms:
    return PlanTerms(
        plan.id, plan.duration_days, plan.device_limit, plan.traffic_limit_bytes, False
    )


class World:
    def __init__(
        self,
        session: AsyncSession,
        make_client: MakeClient,
        make_plan: MakePlan,
        make_payment: MakePayment,
    ) -> None:
        self.session, self.make_client = session, make_client
        self.make_plan, self.make_payment = make_plan, make_payment

    async def subscribed(self, client: Client, **plan: Any) -> None:
        p = await self.make_plan(**plan)
        await subscriptions.activate(self.session, client.id, terms(p), NOW, auto_renew=True)

    async def invite(self, inviter: Client, *, subscribed: bool = True) -> Client:
        friend = await self.make_client()
        assert await subscriptions.set_referrer(self.session, friend.id, inviter.referral_code)
        if subscribed:
            await self.subscribed(friend)
        return friend

    async def pay(self, friend: Client, *, processed: bool = True) -> int:
        payment = await self.make_payment(friend, processed_at=NOW if processed else None)
        await referrals.reward_first_payment(self.session, payment.id, NOW)
        return payment.id

    async def expires(self, client: Client) -> datetime:
        sub = await subscriptions.get_subscription(self.session, client.id)
        assert sub is not None
        return sub.expires_at

    async def rewards(self, kind: str | None = None) -> list[ReferralReward]:
        q = select(ReferralReward).order_by(ReferralReward.id)
        if kind:
            q = q.where(ReferralReward.kind == kind)
        return list(await self.session.scalars(q))


@pytest.fixture
def world(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan, make_payment: MakePayment
) -> World:
    return World(session, make_client, make_plan, make_payment)


async def test_the_first_payment_rewards_both_sides(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friend = await world.invite(inviter)
    before_inviter, before_friend = await world.expires(inviter), await world.expires(friend)

    await world.pay(friend)

    assert await world.expires(inviter) == before_inviter + INVITER_DAYS * DAY
    assert await world.expires(friend) == before_friend + INVITEE_DAYS * DAY
    [reward] = await world.rewards("base")
    assert (reward.inviter_id, reward.invitee_id) == (inviter.id, friend.id)
    assert (reward.days, reward.invitee_days, reward.status) == (
        INVITER_DAYS,
        INVITEE_DAYS,
        "applied",
    )
    assert reward.applied_at is not None
    names = list(await world.session.scalars(select(EventOutbox.name)))
    assert "referral.rewarded" in names


async def test_only_the_first_payment_counts(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friend = await world.invite(inviter)
    await world.pay(friend)
    after_first = await world.expires(inviter)
    await world.pay(friend)  # продление: уже не «первый платёж»
    assert await world.expires(inviter) == after_first
    assert len(await world.rewards("base")) == 1


async def test_the_same_payment_is_rewarded_once(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friend = await world.invite(inviter)
    payment_id = await world.pay(friend)
    await referrals.reward_first_payment(world.session, payment_id, NOW)  # повторная доставка
    assert len(await world.rewards("base")) == 1
    assert await world.expires(inviter) == NOW + (30 + INVITER_DAYS) * DAY


async def test_a_client_without_a_referrer_changes_nothing(world: World) -> None:
    friend = await world.make_client()
    await world.subscribed(friend)
    await world.pay(friend)
    assert await world.rewards() == []


async def test_an_unprocessed_payment_is_not_rewarded(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friend = await world.invite(inviter)
    await world.pay(friend, processed=False)  # платёж записан, доступ не выдан
    assert await world.rewards() == []


async def test_an_inviter_without_a_subscription_waits_for_one(world: World) -> None:
    inviter = await world.make_client()  # подписки нет
    friend = await world.invite(inviter)
    await world.pay(friend)
    [reward] = await world.rewards("base")
    assert (reward.status, reward.applied_at, reward.days) == ("pending", None, INVITER_DAYS)

    await world.subscribed(inviter)
    await referrals.apply_pending(world.session, inviter.id, NOW)
    assert await world.expires(inviter) == NOW + (30 + INVITER_DAYS) * DAY
    [reward] = await world.rewards("base")
    assert reward.status == "applied"
    assert reward.applied_at is not None
    await referrals.apply_pending(world.session, inviter.id, NOW)  # второй раз — ничего
    assert await world.expires(inviter) == NOW + (30 + INVITER_DAYS) * DAY


async def test_a_blocked_inviter_waits_instead_of_failing(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    await subscriptions.set_blocked(world.session, inviter.id, True, NOW)
    friend = await world.invite(inviter)
    await world.pay(friend)
    [reward] = await world.rewards("base")
    assert reward.status == "pending"


async def test_the_monthly_cap_stops_the_inviter_days_but_not_the_friend_days(
    world: World,
) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    before = await world.expires(inviter)
    friends = [await world.invite(inviter) for _ in range(11)]
    for friend in friends:
        await world.pay(friend)
    rewards = await world.rewards("base")
    assert [r.status for r in rewards].count("capped") == 1
    assert rewards[-1].status == "capped"
    assert rewards[-1].days == 0
    assert rewards[-1].invitee_days == INVITEE_DAYS  # другу дни всё равно начислены
    tier_days = 30  # третий платящий друг
    assert await world.expires(inviter) == before + (10 * INVITER_DAYS + tier_days) * DAY


async def test_rewards_older_than_a_month_do_not_count_against_the_cap(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    for friend in [await world.invite(inviter) for _ in range(10)]:
        await world.pay(friend)
    old = NOW - 31 * DAY
    for reward in await world.rewards("base"):
        reward.created_at = old
    await world.session.flush()
    await world.pay(await world.invite(inviter))
    assert (await world.rewards("base"))[-1].status == "applied"


async def test_the_third_friend_gives_the_first_tier_once(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friends = [await world.invite(inviter) for _ in range(4)]
    for friend in friends[:2]:
        await world.pay(friend)
    assert await world.rewards("tier") == []
    before = await world.expires(inviter)

    await world.pay(friends[2])
    [tier] = await world.rewards("tier")
    assert (tier.tier, tier.days, tier.status) == (3, 30, "applied")
    assert await world.expires(inviter) == before + (INVITER_DAYS + 30) * DAY
    assert "referral.tier_reached" in list(await world.session.scalars(select(EventOutbox.name)))

    await world.pay(friends[3])  # четвёртый друг уровень не повторяет
    assert len(await world.rewards("tier")) == 1


async def test_the_fifth_friend_adds_a_device_for_good(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter, device_limit=2)
    for friend in [await world.invite(inviter) for _ in range(5)]:
        await world.pay(friend)
    sub = await subscriptions.get_subscription(world.session, inviter.id)
    assert sub is not None
    assert sub.device_limit == 3
    assert (await subscriptions.get_client(world.session, inviter.id)).bonus_devices == 1


async def test_the_tenth_friend_adds_traffic_for_good(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter, traffic_limit_bytes=100 * GIB)
    for friend in [await world.invite(inviter) for _ in range(10)]:
        await world.pay(friend)
    sub = await subscriptions.get_subscription(world.session, inviter.id)
    assert sub is not None
    assert sub.traffic_limit_bytes == 200 * GIB
    fresh = await subscriptions.get_client(world.session, inviter.id)
    assert fresh.bonus_traffic_bytes == 100 * GIB


async def test_capped_friends_still_count_for_the_tiers(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friends = [await world.invite(inviter) for _ in range(12)]
    for friend in friends:
        await world.pay(friend)
    assert {t.tier for t in await world.rewards("tier")} == {3, 5, 10}


async def test_rewards_and_tiers_are_audited(world: World) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    for friend in [await world.invite(inviter) for _ in range(3)]:
        await world.pay(friend)
    actions = list(await world.session.scalars(select(AuditLog.action)))
    assert actions.count("referral.reward") == 3
    assert actions.count("referral.tier") == 1
    count = await world.session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "referral.reward")
    )
    assert count == 3


async def test_terms_for_a_client_include_the_permanent_perks(world: World) -> None:
    client = await world.make_client()
    await subscriptions.add_perks(
        world.session, client.id, devices=1, traffic_bytes=100 * GIB, now=NOW
    )
    plan = await world.make_plan(device_limit=2, traffic_limit_bytes=50 * GIB)
    t = await referrals.terms_for_client(world.session, plan, client.id)
    assert (t.device_limit, t.traffic_limit_bytes) == (3, 150 * GIB)
    unlimited = await world.make_plan(traffic_limit_bytes=None)
    assert (
        await referrals.terms_for_client(world.session, unlimited, client.id)
    ).traffic_limit_bytes is None


async def test_a_subscription_failure_for_the_friend_does_not_lose_the_reward_record(
    world: World,
) -> None:
    inviter = await world.make_client()
    await world.subscribed(inviter)
    friend = await world.invite(inviter, subscribed=False)  # у друга нет подписки
    with pytest.raises(SubscriptionInactive):
        await world.pay(friend)
    assert await world.rewards() == []  # откатилось целиком: событие повторится
