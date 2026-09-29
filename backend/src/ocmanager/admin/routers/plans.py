from typing import Annotated

from fastapi import APIRouter, Path

from ocmanager.admin.deps import CurrentAdmin
from ocmanager.admin.schemas import PlanOut
from ocmanager.billing import plans
from ocmanager.billing.plans import PlanCreate, PlanUpdate
from ocmanager.core.db import SessionDep
from ocmanager.flows import plans as plan_flows

router = APIRouter(tags=["plans"])

PlanCode = Annotated[str, Path(max_length=64)]


@router.get("/plans")
async def list_plans(ctx: CurrentAdmin, db: SessionDep) -> list[PlanOut]:
    """Все тарифы, включая неактивные и скрытый trial."""
    return [PlanOut.model_validate(p) for p in await plans.list_all(db)]


@router.post("/plans", status_code=201)
async def create_plan(body: PlanCreate, ctx: CurrentAdmin, db: SessionDep) -> PlanOut:
    plan = await plan_flows.create_plan(db, body, ctx.actor)
    out = PlanOut.model_validate(plan)
    await db.commit()
    return out


@router.patch("/plans/{code}")
async def update_plan(
    code: PlanCode, body: PlanUpdate, ctx: CurrentAdmin, db: SessionDep
) -> PlanOut:
    """Меняются только переданные поля. Код и признак trial не меняются вообще: поля `is_trial`
    в схеме нет, лишнее поле — 422. Уже купленные подписки хранят свой снимок условий,
    поэтому правка тарифа их не трогает; `is_active=false` лишь прячет тариф из каталога."""
    change = await plan_flows.update_plan(db, code, body, ctx.actor)
    out = PlanOut.model_validate(change.plan)
    await db.commit()
    return out
