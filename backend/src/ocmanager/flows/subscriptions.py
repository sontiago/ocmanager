"""Склейка subscriptions + audit: каждое изменение подписки пишется в аудит.

Все записи аудита подписки нацелены на клиента (target_type="client"):
в админке история клиента — одна лента.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing.models import Plan
from ocmanager.subscriptions import service
from ocmanager.subscriptions.models import Subscription
from ocmanager.subscriptions.state import PlanTerms


def terms_from_plan(plan: Plan) -> PlanTerms:
    """Снимок условий тарифа для автомата подписки (subscriptions не знает billing)."""
    return PlanTerms(
        plan_id=plan.id,
        duration_days=plan.duration_days,
        device_limit=plan.device_limit,
        traffic_limit_bytes=plan.traffic_limit_bytes,
        is_trial=plan.is_trial,
    )


async def _record(
    session: AsyncSession, actor: Actor, action: str, client_id: int, **details: Any
) -> None:
    await audit.record(
        session,
        actor,
        action,
        target_type="client",
        target_id=str(client_id),
        details=details,
    )


def _sub_details(sub: Subscription) -> dict[str, Any]:
    return {
        "plan_id": sub.plan_id,
        "status": sub.status,
        "expires_at": sub.expires_at.isoformat(),
        "auto_renew": sub.auto_renew,
    }


async def start_trial(
    session: AsyncSession, client_id: int, terms: PlanTerms, actor: Actor, now: datetime
) -> Subscription:
    sub = await service.start_trial(session, client_id, terms, now)
    await _record(session, actor, "subscription.start_trial", client_id, **_sub_details(sub))
    return sub


async def activate(
    session: AsyncSession,
    client_id: int,
    terms: PlanTerms,
    actor: Actor,
    now: datetime,
    *,
    auto_renew: bool,
    provider: str | None = None,
    external_subscription_id: str | None = None,
) -> Subscription:
    sub = await service.activate(
        session,
        client_id,
        terms,
        now,
        auto_renew=auto_renew,
        provider=provider,
        external_subscription_id=external_subscription_id,
    )
    await _record(session, actor, "subscription.activate", client_id, **_sub_details(sub))
    return sub


async def renew(
    session: AsyncSession,
    client_id: int,
    terms: PlanTerms,
    actor: Actor,
    now: datetime,
    *,
    provider: str | None = None,
    external_subscription_id: str | None = None,
) -> Subscription:
    sub = await service.renew(
        session,
        client_id,
        terms,
        now,
        provider=provider,
        external_subscription_id=external_subscription_id,
    )
    await _record(session, actor, "subscription.renew", client_id, **_sub_details(sub))
    return sub


async def extend_days(
    session: AsyncSession, client_id: int, days: int, actor: Actor, now: datetime
) -> Subscription:
    sub = await service.extend_days(session, client_id, days, now)
    await _record(session, actor, "subscription.extend", client_id, days=days, **_sub_details(sub))
    return sub


async def cancel_auto_renew(session: AsyncSession, client_id: int, actor: Actor) -> bool:
    changed = await service.cancel_auto_renew(session, client_id)
    if changed:
        await _record(session, actor, "subscription.cancel_auto_renew", client_id)
    return changed


async def expire_due(session: AsyncSession, now: datetime) -> list[int]:
    """Истечение по расписанию: действует система, строка аудита — на каждого клиента."""
    client_ids = await service.expire_due(session, now)
    for client_id in client_ids:
        await _record(session, Actor.system(), "subscription.expire", client_id)
    return client_ids


async def expire_now(session: AsyncSession, client_id: int, actor: Actor, now: datetime) -> bool:
    changed = await service.expire_now(session, client_id, now)
    if changed:
        await _record(session, actor, "subscription.expire", client_id, forced=True)
    return changed


async def set_blocked(
    session: AsyncSession, client_id: int, blocked: bool, actor: Actor, now: datetime
) -> bool:
    changed = await service.set_blocked(session, client_id, blocked, now)
    if changed:
        await _record(session, actor, "client.block" if blocked else "client.unblock", client_id)
    return changed
