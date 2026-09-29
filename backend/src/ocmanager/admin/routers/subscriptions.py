from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select

from ocmanager.admin.deps import CurrentAdmin, RedisDep, commit_and_kick
from ocmanager.admin.pagination import BigId, Page, PageDep, page_of
from ocmanager.admin.schemas import ActionOut
from ocmanager.billing.models import Plan
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.state import LIVE, MAX_DAYS

router = APIRouter(tags=["subscriptions"])

SubStatus = Literal[
    "pending_payment", "trial", "active", "expired", "exhausted", "cancelled", "blocked"
]


class SubscriptionRow(BaseModel):
    client_id: int
    telegram_id: int
    username: str | None
    first_name: str
    status: str
    plan_code: str
    plan_is_trial: bool
    started_at: datetime
    expires_at: datetime
    auto_renew: bool
    traffic_used_bytes: int
    traffic_limit_bytes: int | None


@router.get("/subscriptions")
async def list_subscriptions(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    status: SubStatus | None = None,
    plan: Annotated[str | None, Query(max_length=64)] = None,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=MAX_DAYS)] = None,
) -> Page[SubscriptionRow]:
    """`expiring_within_days=3` — живые подписки, что закончатся в ближайшие 3 суток (и те,
    чей срок уже вышел, но cron истечения ещё не успел их закрыть), ближайшие первыми."""
    conds: list[ColumnElement[bool]] = []
    if status is not None:
        conds.append(Subscription.status == status)
    if plan is not None:
        conds.append(Plan.code == plan)
    if expiring_within_days is not None:
        conds.append(Subscription.status.in_([s.value for s in LIVE]))
        conds.append(Subscription.expires_at <= utcnow() + timedelta(days=expiring_within_days))

    base = (
        select(Subscription, Client, Plan.code)
        .join(Client, Client.id == Subscription.client_id)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(*conds)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    order = (
        Subscription.expires_at.asc()
        if expiring_within_days is not None
        else Subscription.expires_at.desc()
    )
    rows = await db.execute(
        base.order_by(order, Subscription.id).limit(page.limit).offset(page.offset)
    )
    items = [
        SubscriptionRow(
            client_id=client.id,
            telegram_id=client.telegram_id,
            username=client.username,
            first_name=client.first_name,
            status=sub.status,
            plan_code=plan_code,
            plan_is_trial=sub.plan_is_trial,
            started_at=sub.started_at,
            expires_at=sub.expires_at,
            auto_renew=sub.auto_renew,
            traffic_used_bytes=sub.traffic_used_bytes,
            traffic_limit_bytes=sub.traffic_limit_bytes,
        )
        for sub, client, plan_code in rows
    ]
    return page_of(items, int(total or 0), page)


@router.post("/subscriptions/{client_id}/cancel-auto-renew")
async def cancel_auto_renew(client_id: BigId, ctx: CurrentAdmin, db: SessionDep) -> ActionOut:
    changed = await subscription_flows.cancel_auto_renew(db, client_id, ctx.actor)
    await db.commit()
    return ActionOut(changed=changed)


@router.post("/subscriptions/{client_id}/expire")
async def expire(client_id: BigId, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep) -> ActionOut:
    """Немедленно закрыть доступ — для злоупотреблений. Устройства остаются, вернуть
    доступ можно выдачей или продлением. Обработчик события уберёт клиента с ноды."""
    changed = await subscription_flows.expire_now(db, client_id, ctx.actor, utcnow())
    await commit_and_kick(db, redis)
    return ActionOut(changed=changed)
