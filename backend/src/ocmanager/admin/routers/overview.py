from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from ocmanager.admin.deps import CurrentAdmin, RedisDep
from ocmanager.admin.schemas import AuditRow, HealthOut, NodeOut
from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.nodes import registry, service
from ocmanager.nodes.models import TrafficDaily
from ocmanager.subscriptions.models import Subscription
from ocmanager.subscriptions.state import LIVE, Status

router = APIRouter(tags=["overview"])

EXPIRING_DAYS = 3
RECENT_AUDIT = 20


class TrafficOut(BaseModel):
    from_day: date
    to_day: date
    bytes_in: int
    bytes_out: int


class OverviewOut(BaseModel):
    node: NodeOut | None  # None — ноды в БД ещё нет
    health: HealthOut | None  # из кэша воркера
    active_sessions: int | None  # оттуда же; None — кэша нет
    traffic: TrafficOut  # сегодня и вчера по UTC: суточные итоги, а не скользящие 24 часа
    subscriptions_by_status: dict[str, int]  # все статусы, включая нулевые
    expiring_soon: int  # живые подписки, что закончатся за EXPIRING_DAYS суток
    recent_audit: list[AuditRow]
    last_reconcile: dict[str, Any] | None  # отчёт последней сверки как есть
    revenue: None = None  # выручка — Фаза 5


@router.get("/overview")
async def overview(ctx: CurrentAdmin, db: SessionDep, redis: RedisDep) -> OverviewOut:
    """Всё, что видно с первого экрана. Работает на пустой базе: нулями, а не ошибкой."""
    now = utcnow()
    nodes = await registry.get_active_nodes(db)
    node = nodes[0] if nodes else None  # в этапе 1 нода одна
    cached = None if node is None else await service.cached_health(redis, node.id)

    first_day = now.date() - timedelta(days=1)
    rx, tx = (
        await db.execute(
            select(
                func.coalesce(func.sum(TrafficDaily.bytes_in), 0),
                func.coalesce(func.sum(TrafficDaily.bytes_out), 0),
            ).where(TrafficDaily.day >= first_day)
        )
    ).one()

    by_status = dict.fromkeys((s.value for s in Status), 0)
    for status, count in await db.execute(
        select(Subscription.status, func.count()).group_by(Subscription.status)
    ):
        by_status[status] = count
    expiring = await db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(
            Subscription.status.in_([s.value for s in LIVE]),
            Subscription.expires_at <= now + timedelta(days=EXPIRING_DAYS),
        )
    )
    recent = await db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(RECENT_AUDIT)
    )
    return OverviewOut(
        node=None if node is None else NodeOut.of(node),
        health=None if cached is None else HealthOut.of(cached),
        active_sessions=None if cached is None else cached.active_sessions,
        traffic=TrafficOut(
            from_day=first_day, to_day=now.date(), bytes_in=int(rx), bytes_out=int(tx)
        ),
        subscriptions_by_status=by_status,
        expiring_soon=int(expiring or 0),
        recent_audit=[AuditRow.of(a) for a in recent],
        last_reconcile=None if node is None else node.last_reconcile_report,
    )
