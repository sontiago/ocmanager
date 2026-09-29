import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakeClient, MakePlan
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.errors import (
    InvalidTransition,
    NotFound,
    SubscriptionInactive,
    TrialAlreadyUsed,
)
from ocmanager.events.models import EventOutbox
from ocmanager.subscriptions import service
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.state import PlanTerms

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)


def terms(plan: Any) -> PlanTerms:
    """Условия из тарифа, созданного фабрикой conftest. Тип Any: subscriptions
    не импортирует billing (граница модулей), даже в тестах."""
    return PlanTerms(
        plan.id,
        plan.duration_days,
        plan.device_limit,
        plan.traffic_limit_bytes,
        plan.is_trial,
    )


async def events(session: AsyncSession) -> list[tuple[str, int]]:
    rows = await session.scalars(select(EventOutbox).order_by(EventOutbox.id))
    return [(r.name, r.payload["client_id"]) for r in rows]


async def test_start_trial(session: AsyncSession, make_client: MakeClient, trial_plan: Any) -> None:
    client = await make_client()
    sub = await service.start_trial(session, client.id, terms(trial_plan), NOW)
    assert (sub.status, sub.expires_at, sub.plan_is_trial) == (
        "trial",
        NOW + 3 * DAY,
        True,
    )
    assert client.trial_used_at == NOW
    assert await events(session) == [("subscription.activated", client.id)]


async def test_second_trial_is_refused(
    session: AsyncSession, make_client: MakeClient, trial_plan: Any
) -> None:
    client = await make_client()
    await service.start_trial(session, client.id, terms(trial_plan), NOW)
    with pytest.raises(TrialAlreadyUsed):
        await service.start_trial(session, client.id, terms(trial_plan), NOW + DAY)
    assert len(await events(session)) == 1


async def test_trial_is_not_given_to_someone_who_already_paid(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan, trial_plan: Any
) -> None:
    client = await make_client()
    await service.activate(session, client.id, terms(await make_plan()), NOW, auto_renew=True)
    with pytest.raises(InvalidTransition):
        await service.start_trial(session, client.id, terms(trial_plan), NOW)
    assert client.trial_used_at is None  # неудачная попытка не сжигает trial


async def test_activate_then_renew_events_and_dates(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan()
    first = await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    assert (first.status, first.expires_at, first.auto_renew) == (
        "active",
        NOW + 30 * DAY,
        True,
    )
    renewed = await service.renew(session, client.id, terms(plan), NOW + 10 * DAY)
    assert renewed.id == first.id  # одна строка на клиента
    assert renewed.expires_at == NOW + 60 * DAY
    assert await events(session) == [
        ("subscription.activated", client.id),
        ("subscription.renewed", client.id),
    ]


async def test_activate_records_provider(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan()
    sub = await service.activate(
        session,
        client.id,
        terms(plan),
        NOW,
        auto_renew=True,
        provider="tribute",
        external_subscription_id="sub_77",
    )
    assert (sub.provider, sub.external_subscription_id) == ("tribute", "sub_77")


async def test_extend_days_on_expired_revives_access(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=1)
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    await service.expire_due(session, NOW + 2 * DAY)
    assert not await service.client_has_access(session, client.id, NOW + 2 * DAY)
    sub = await service.extend_days(session, client.id, 5, NOW + 2 * DAY)
    assert (sub.status, sub.expires_at, sub.auto_renew) == (
        "cancelled",
        NOW + 7 * DAY,
        False,
    )
    assert await service.client_has_access(session, client.id, NOW + 2 * DAY)
    assert (await events(session))[-1] == ("subscription.activated", client.id)


async def test_extend_days_needs_a_subscription(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    with pytest.raises(InvalidTransition):
        await service.extend_days(session, client.id, 5, NOW)


async def test_cancel_auto_renew_event_only_on_change(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan()
    assert not await service.cancel_auto_renew(session, client.id)  # подписки нет
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    assert await service.cancel_auto_renew(session, client.id)
    sub = await service.get_subscription(session, client.id)
    assert sub is not None
    assert (sub.status, sub.auto_renew) == ("cancelled", False)
    assert not await service.cancel_auto_renew(session, client.id)  # повтор
    assert [e for e, _ in await events(session)].count("subscription.auto_renew_cancelled") == 1


async def test_expire_due_touches_only_overdue_live_subscriptions(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    short, long = await make_plan(duration_days=1), await make_plan(duration_days=30)
    a, b, c = await make_client(), await make_client(), await make_client()
    await service.activate(session, a.id, terms(short), NOW, auto_renew=True)
    await service.activate(session, b.id, terms(long), NOW, auto_renew=True)
    await service.activate(session, c.id, terms(short), NOW, auto_renew=False)
    await service.cancel_auto_renew(session, c.id)  # cancelled тоже живая
    assert sorted(await service.expire_due(session, NOW + 2 * DAY)) == sorted([a.id, c.id])
    assert await service.expire_due(session, NOW + 2 * DAY) == []
    sub_b = await service.get_subscription(session, b.id)
    assert sub_b is not None
    assert sub_b.status == "active"
    names = [e for e, _ in await events(session)]
    assert names.count("subscription.expired") == 2


async def test_expire_now_closes_a_live_subscription_once(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=30)
    assert not await service.expire_now(session, client.id, NOW)  # подписки нет
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    assert await service.expire_now(session, client.id, NOW + DAY)
    sub = await service.get_subscription(session, client.id)
    assert sub is not None
    assert (sub.status, sub.expires_at) == ("expired", NOW + DAY)
    assert not await service.client_has_access(session, client.id, NOW + DAY)
    assert not await service.expire_now(session, client.id, NOW + DAY)  # повтор — ничего
    assert [e for e, _ in await events(session)].count("subscription.expired") == 1


async def test_expire_due_boundary_is_inclusive(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=1)
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    assert await service.expire_due(session, NOW + DAY - timedelta(seconds=1)) == []
    assert await service.expire_due(session, NOW + DAY) == [client.id]


async def test_expire_due_handles_more_than_one_batch(
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "EXPIRY_BATCH", 2)
    plan = await make_plan(duration_days=1)
    ids = []
    for _ in range(5):
        c = await make_client()
        ids.append(c.id)
        await service.activate(session, c.id, terms(plan), NOW, auto_renew=True)
    assert sorted(await service.expire_due(session, NOW + 2 * DAY)) == sorted(ids)


async def test_block_and_unblock(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan()
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    assert await service.set_blocked(session, client.id, True, NOW)
    sub = await service.get_subscription(session, client.id)
    assert sub is not None
    assert sub.status == "blocked"
    assert not await service.client_has_access(session, client.id, NOW)
    assert not await service.set_blocked(session, client.id, True, NOW)  # повтор — ничего
    assert await service.set_blocked(session, client.id, False, NOW + DAY)
    assert sub.status == "active"
    assert await service.client_has_access(session, client.id, NOW + DAY)
    assert [e for e, _ in await events(session)][-2:] == [
        "client.blocked",
        "client.unblocked",
    ]


async def test_unblock_after_expiry_leaves_it_expired(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=1)
    await service.activate(session, client.id, terms(plan), NOW, auto_renew=True)
    await service.set_blocked(session, client.id, True, NOW)
    await service.set_blocked(session, client.id, False, NOW + 5 * DAY)
    sub = await service.get_subscription(session, client.id)
    assert sub is not None
    assert sub.status == "expired"


async def test_blocking_a_client_without_subscription(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    assert await service.set_blocked(session, client.id, True, NOW)
    assert client.is_blocked
    assert await service.get_subscription(session, client.id) is None


async def test_blocked_client_gets_nothing(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan, trial_plan: Any
) -> None:
    client, plan = await make_client(), await make_plan()
    await service.set_blocked(session, client.id, True, NOW)
    for call in (
        service.start_trial(session, client.id, terms(trial_plan), NOW),
        service.activate(session, client.id, terms(plan), NOW, auto_renew=True),
        service.renew(session, client.id, terms(plan), NOW),
        service.extend_days(session, client.id, 3, NOW),
    ):
        with pytest.raises(SubscriptionInactive) as info:
            await call
        assert info.value.status == 403
    assert await events(session) == [("client.blocked", client.id)]


async def test_unknown_client(session: AsyncSession, make_plan: MakePlan) -> None:
    plan = await make_plan()
    with pytest.raises(NotFound):
        await service.activate(session, 999_999, terms(plan), NOW, auto_renew=True)
    with pytest.raises(NotFound):
        await service.client_has_access(session, 999_999, NOW)


async def test_no_subscription_no_access(session: AsyncSession, make_client: MakeClient) -> None:
    client = await make_client()
    assert not await service.client_has_access(session, client.id, NOW)


async def seed(
    sm: async_sessionmaker[AsyncSession], *, telegram_id: int, code: str, days: int
) -> tuple[int, PlanTerms]:
    """Клиент и тариф с настоящими коммитами (для тестов на блокировки)."""
    async with sm() as s, s.begin():
        client = Client(telegram_id=telegram_id, first_name="A", lang="ru")
        s.add(client)
        await s.flush()
        plan_id = await s.scalar(
            text(
                "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
                " currency) VALUES (:code, '{}', :days, 1, 1, 'RUB') RETURNING id"
            ),
            {"code": code, "days": days},
        )
        assert plan_id is not None
        return client.id, PlanTerms(plan_id, days, 1, None, False)


async def test_parallel_renewals_do_not_lose_days(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Блокировка клиента: два одновременных продления складываются, а не затирают друг друга."""
    client_id, t = await seed(committed_sessionmaker, telegram_id=1, code="m1", days=30)
    async with committed_sessionmaker() as s, s.begin():
        await service.activate(s, client_id, t, NOW, auto_renew=True)

    async def renew() -> None:
        async with committed_sessionmaker() as s, s.begin():
            await service.renew(s, client_id, t, NOW)

    await asyncio.gather(renew(), renew())
    async with committed_sessionmaker() as s:
        sub = await service.get_subscription(s, client_id)
        assert sub is not None
        assert sub.expires_at == NOW + 90 * DAY  # 30 (activate) + 30 + 30


async def test_expiry_does_not_swallow_a_concurrent_renewal(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Продление держит блокировку: expire_due пропускает эту подписку (SKIP LOCKED)."""
    client_id, t = await seed(committed_sessionmaker, telegram_id=2, code="d1", days=1)
    async with committed_sessionmaker() as s, s.begin():
        await service.activate(s, client_id, t, NOW, auto_renew=True)

    later = NOW + 2 * DAY
    async with committed_sessionmaker() as renewing, renewing.begin():
        await service.renew(renewing, client_id, t, later)  # блокировка удерживается
        async with committed_sessionmaker() as expiring, expiring.begin():
            assert await service.expire_due(expiring, later) == []  # строка занята — пропущена
    async with committed_sessionmaker() as s:
        sub = await service.get_subscription(s, client_id)
        assert sub is not None
        assert (sub.status, sub.expires_at) == ("active", later + DAY)
