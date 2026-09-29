"""Склейка billing + audit: тарифы с аудитом."""

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing import plans
from ocmanager.billing.models import Plan
from ocmanager.billing.plans import PlanChange, PlanCreate, PlanUpdate


async def create_plan(session: AsyncSession, data: PlanCreate, actor: Actor) -> Plan:
    plan = await plans.create_plan(session, data)
    await audit.record(
        session,
        actor,
        "plan.create",
        target_type="plan",
        target_id=str(plan.id),
        details={"code": plan.code},
    )
    return plan


async def update_plan(
    session: AsyncSession, code: str, patch: PlanUpdate, actor: Actor
) -> PlanChange:
    """Аудит пишется только если что-то действительно изменилось."""
    change = await plans.update_plan(session, code, patch)
    if change.changed:
        await audit.record(
            session,
            actor,
            "plan.update",
            target_type="plan",
            target_id=str(change.plan.id),
            details={
                "code": code,
                "changed": {k: [old, new] for k, (old, new) in change.changed.items()},
            },
        )
    return change
