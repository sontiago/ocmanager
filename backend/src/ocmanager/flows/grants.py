"""Ручная выдача тарифа — из админки и CLI. Без оплаты и без автопродления."""

from dataclasses import replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.service import Actor
from ocmanager.billing import plans
from ocmanager.core.errors import InvalidInput
from ocmanager.flows import subscriptions as flows
from ocmanager.subscriptions.models import Subscription
from ocmanager.subscriptions.state import MAX_DAYS


async def grant_plan(
    session: AsyncSession,
    *,
    client_id: int,
    plan_code: str,
    actor: Actor,
    now: datetime,
    days: int | None = None,
) -> Subscription:
    """`days` заменяет длительность тарифа. Скрытый тариф trial выдаётся только
    через start_trial: у него свои правила (один раз на клиента)."""
    plan = await plans.get_by_code(session, plan_code)
    if plan.is_trial:
        raise InvalidInput("the trial plan is started with start_trial, not granted")
    terms = flows.terms_from_plan(plan)
    if days is not None:
        if not 0 < days <= MAX_DAYS:
            raise InvalidInput(f"days must be 1..{MAX_DAYS}")
        terms = replace(terms, duration_days=days)
    return await flows.activate(session, client_id, terms, actor, now, auto_renew=False)
