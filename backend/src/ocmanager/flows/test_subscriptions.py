from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakePlan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.core.errors import SubscriptionInactive, TrialAlreadyUsed
from ocmanager.flows import subscriptions as flow

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)
ADMIN = Actor("admin", "7", "203.0.113.5")


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


def test_terms_from_plan_copies_the_snapshot() -> None:
    plan = Plan(id=4, duration_days=30, device_limit=3, traffic_limit_bytes=None, is_trial=False)
    terms = flow.terms_from_plan(plan)
    assert (terms.plan_id, terms.duration_days, terms.device_limit) == (4, 30, 3)
    assert (terms.traffic_limit_bytes, terms.is_trial) == (None, False)


async def test_every_change_is_audited_against_the_client(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan()
    terms = flow.terms_from_plan(plan)
    await flow.activate(session, client.id, terms, ADMIN, NOW, auto_renew=True)
    await flow.renew(session, client.id, terms, ADMIN, NOW)
    await flow.extend_days(session, client.id, 5, ADMIN, NOW)
    assert await flow.cancel_auto_renew(session, client.id, ADMIN)
    assert await flow.set_blocked(session, client.id, True, ADMIN, NOW)
    assert await flow.set_blocked(session, client.id, False, ADMIN, NOW)
    rows = await audit_rows(session)
    assert [r.action for r in rows] == [
        "subscription.activate",
        "subscription.renew",
        "subscription.extend",
        "subscription.cancel_auto_renew",
        "client.block",
        "client.unblock",
    ]
    assert {(r.actor_type, r.actor_id, r.target_type, r.target_id) for r in rows} == {
        ("admin", "7", "client", str(client.id))
    }
    extend = rows[2]
    assert extend.details["days"] == 5
    assert extend.details["expires_at"] == (NOW + 65 * DAY).isoformat()


async def test_noops_write_no_audit(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    assert not await flow.cancel_auto_renew(session, client.id, ADMIN)  # подписки нет
    assert not await flow.set_blocked(session, client.id, False, ADMIN, NOW)  # не был заблокирован
    assert await audit_rows(session) == []


async def test_failed_change_writes_no_audit(
    session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    client = await make_client()
    terms = flow.terms_from_plan(trial_plan)
    await flow.start_trial(session, client.id, terms, ADMIN, NOW)
    with pytest.raises(TrialAlreadyUsed):
        await flow.start_trial(session, client.id, terms, ADMIN, NOW)
    await flow.set_blocked(session, client.id, True, ADMIN, NOW)
    with pytest.raises(SubscriptionInactive):
        await flow.extend_days(session, client.id, 1, ADMIN, NOW)
    assert [r.action for r in await audit_rows(session)] == [
        "subscription.start_trial",
        "client.block",
    ]


async def test_expiry_is_audited_as_the_system(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(duration_days=1)
    await flow.activate(session, client.id, flow.terms_from_plan(plan), ADMIN, NOW, auto_renew=True)
    assert await flow.expire_due(session, NOW + 2 * DAY) == [client.id]
    assert await flow.expire_due(session, NOW + 2 * DAY) == []
    *_, row = await audit_rows(session)
    assert (row.actor_type, row.actor_id) == ("system", None)
    assert (row.action, row.target_id) == ("subscription.expire", str(client.id))
