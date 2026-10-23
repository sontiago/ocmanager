from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakeClient, MakePlan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing import promo
from ocmanager.core.errors import (
    NotApplicable,
    PromoAlreadyUsed,
    PromoInvalid,
    SubscriptionInactive,
)
from ocmanager.events.models import EventOutbox
from ocmanager.flows import promo as flows
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.state import PlanTerms

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
DAY = timedelta(days=1)


def me(client_id: int) -> Actor:
    return Actor("client", str(client_id))


def terms(plan: Any) -> PlanTerms:
    return PlanTerms(
        plan.id, plan.duration_days, plan.device_limit, plan.traffic_limit_bytes, False
    )


async def subscribed(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan, **plan: Any
) -> int:
    client = await make_client()
    p = await make_plan(**plan)
    await subscriptions.activate(session, client.id, terms(p), NOW, auto_renew=True)
    return client.id


async def test_a_days_code_extends_the_subscription_and_is_audited(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan, duration_days=30)
    await promo.create(session, code="bonus14", kind="days", value=14)

    result = await flows.redeem(session, client_id, "BONUS14", me(client_id), NOW)

    assert (result.kind, result.value) == ("days", 14)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.expires_at == NOW + 44 * DAY
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "promo.redeem"))
    assert audit is not None
    assert audit.target_id == str(client_id)
    assert audit.details == {"code": "bonus14", "kind": "days", "value": 14}


async def test_a_traffic_code_raises_the_limit(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan, traffic_limit_bytes=1000)
    await promo.create(session, code="gbcode", kind="traffic", value=500)
    await flows.redeem(session, client_id, "gbcode", me(client_id), NOW)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.traffic_limit_bytes == 1500


async def test_a_traffic_code_revives_an_exhausted_client(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan, traffic_limit_bytes=1000)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    sub.traffic_used_bytes = 1000
    await subscriptions.enforce_quota(session, client_id, NOW)
    await promo.create(session, code="gbcode", kind="traffic", value=500)
    await flows.redeem(session, client_id, "gbcode", me(client_id), NOW)
    assert await subscriptions.client_has_access(session, client_id, NOW)
    names = list(await session.scalars(select(EventOutbox.name)))
    assert "traffic.reset" in names


async def test_a_failed_redeem_does_not_consume_the_code(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()  # подписки нет
    created = await promo.create(session, code="nosub", kind="days", value=5, max_uses=1)
    with pytest.raises(SubscriptionInactive):
        await flows.redeem(session, client.id, "nosub", me(client.id), NOW)
    await session.refresh(created)
    assert created.uses == 0
    assert await promo.redemptions(session, created.id) == []


async def test_a_traffic_code_on_an_unlimited_plan_is_not_consumed(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan, traffic_limit_bytes=None)
    created = await promo.create(session, code="gbcode", kind="traffic", value=500)
    with pytest.raises(NotApplicable):
        await flows.redeem(session, client_id, "gbcode", me(client_id), NOW)
    await session.refresh(created)
    assert created.uses == 0


async def test_an_unknown_code_changes_nothing(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan)
    with pytest.raises(PromoInvalid):
        await flows.redeem(session, client_id, "nope", me(client_id), NOW)
    assert not list(
        await session.scalars(select(AuditLog).where(AuditLog.action == "promo.redeem"))
    )


async def test_the_same_code_twice_is_refused(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client_id = await subscribed(session, make_client, make_plan)
    await promo.create(session, code="once", kind="days", value=1)
    await flows.redeem(session, client_id, "once", me(client_id), NOW)
    with pytest.raises(PromoAlreadyUsed):
        await flows.redeem(session, client_id, "once", me(client_id), NOW)
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.expires_at == NOW + 31 * DAY  # второй раз дни не добавились
