from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.plans import PlanCreate, PlanUpdate
from ocmanager.flows import plans

ADMIN = Actor("admin", "7", "203.0.113.5")

DATA = PlanCreate(
    code="m1",
    name_i18n={"ru": "Месяц", "en": "Month"},
    duration_days=30,
    device_limit=3,
    price_amount=19900,
    currency="RUB",
)


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


async def test_create_is_audited(session: AsyncSession) -> None:
    plan = await plans.create_plan(session, DATA, ADMIN)
    [row] = await audit_rows(session)
    assert (row.actor_type, row.actor_id, row.action) == ("admin", "7", "plan.create")
    assert (row.target_type, row.target_id) == ("plan", str(plan.id))
    assert row.details == {"code": "m1"}


async def test_update_audit_carries_the_diff(session: AsyncSession) -> None:
    await plans.create_plan(session, DATA, ADMIN)
    await plans.update_plan(session, "m1", PlanUpdate(price_amount=24900), ADMIN)
    _, row = await audit_rows(session)
    assert row.action == "plan.update"
    assert row.details == {"code": "m1", "changed": {"price_amount": [19900, 24900]}}


async def test_noop_update_writes_no_audit(session: AsyncSession) -> None:
    await plans.create_plan(session, DATA, ADMIN)
    await plans.update_plan(session, "m1", PlanUpdate(price_amount=19900), ADMIN)
    assert len(await audit_rows(session)) == 1  # только create
