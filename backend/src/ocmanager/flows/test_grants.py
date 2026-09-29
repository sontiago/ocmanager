from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakePlan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.core.errors import InvalidInput, NotFound
from ocmanager.flows import grants
from ocmanager.subscriptions.state import MAX_DAYS

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)
ADMIN = Actor("admin", "cli")


async def test_grant_gives_a_month_without_auto_renew(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client, plan = await make_client(), await make_plan(code="m1")
    sub = await grants.grant_plan(
        session, client_id=client.id, plan_code="m1", actor=ADMIN, now=NOW
    )
    assert (sub.status, sub.auto_renew, sub.plan_id) == ("active", False, plan.id)
    assert sub.expires_at == NOW + 30 * DAY
    assert (sub.provider, sub.external_subscription_id) == (None, None)


async def test_days_override_the_plan_duration(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    sub = await grants.grant_plan(
        session, client_id=client.id, plan_code="m1", actor=ADMIN, now=NOW, days=7
    )
    assert sub.expires_at == NOW + 7 * DAY


async def test_granting_again_extends_from_the_current_end(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    for _ in range(2):
        sub = await grants.grant_plan(
            session, client_id=client.id, plan_code="m1", actor=ADMIN, now=NOW
        )
    assert sub.expires_at == NOW + 60 * DAY


async def test_inactive_plans_can_still_be_granted_by_an_operator(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="special", is_active=False)
    sub = await grants.grant_plan(
        session, client_id=client.id, plan_code="special", actor=ADMIN, now=NOW
    )
    assert sub.status == "active"


@pytest.mark.parametrize("days", [0, -1, MAX_DAYS + 1, 999_999_999])
async def test_non_positive_or_absurd_days_are_refused(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan, days: int
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    with pytest.raises(InvalidInput):
        await grants.grant_plan(
            session, client_id=client.id, plan_code="m1", actor=ADMIN, now=NOW, days=days
        )


async def test_trial_plan_cannot_be_granted(
    session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    with pytest.raises(InvalidInput):
        await grants.grant_plan(
            session, client_id=(await make_client()).id, plan_code="trial", actor=ADMIN, now=NOW
        )


async def test_unknown_plan_and_unknown_client(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    with pytest.raises(NotFound):
        await grants.grant_plan(
            session, client_id=client.id, plan_code="nope", actor=ADMIN, now=NOW
        )
    with pytest.raises(NotFound):
        await grants.grant_plan(session, client_id=999_999, plan_code="m1", actor=ADMIN, now=NOW)


async def test_grant_is_audited_with_the_operator(
    session: AsyncSession, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    await grants.grant_plan(session, client_id=client.id, plan_code="m1", actor=ADMIN, now=NOW)
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "subscription.activate"))
    assert row is not None
    assert (row.actor_type, row.actor_id, row.target_id) == ("admin", "cli", str(client.id))
    assert row.details["auto_renew"] is False
