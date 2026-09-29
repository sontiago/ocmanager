"""Старт пробного периода."""

from dataclasses import replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.service import Actor
from ocmanager.billing import plans
from ocmanager.core import settings_store
from ocmanager.flows import subscriptions as flows
from ocmanager.subscriptions.models import Subscription


async def start_trial(
    session: AsyncSession, *, client_id: int, actor: Actor, now: datetime
) -> Subscription:
    """Условия берутся из скрытого тарифа trial, а длительность и трафик — из настроек,
    которые владелец меняет из админки без миграций. Нулевой лимит трафика — без лимита."""
    plan = await plans.get_trial_plan(session)
    runtime = await settings_store.load(session)
    terms = replace(
        flows.terms_from_plan(plan),
        duration_days=runtime.trial_days,
        traffic_limit_bytes=runtime.trial_traffic_bytes or None,
    )
    return await flows.start_trial(session, client_id, terms, actor, now)
