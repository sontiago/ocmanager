"""Чтения, которые нужны нескольким разделам админки."""

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.schemas import SubscriptionOut
from ocmanager.billing.models import Plan
from ocmanager.nodes import registry, service
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Subscription


async def online_usernames(db: AsyncSession, redis: Redis) -> set[str] | None:
    """Кто подключён по кэшу, который раз в минуту обновляет воркер. None — кэша нет ни у
    одной ноды (воркер не работает или нода лежит): «не подключён» и «не знаем» — разные вещи."""
    known: list[set[str]] = []
    for node in await registry.get_active_nodes(db):
        online = await service.cached_online_usernames(redis, node.id)
        if online is not None:
            known.append(online)
    return set().union(*known) if known else None


async def count_active_devices(db: AsyncSession, client_id: int) -> int:
    n = await db.scalar(
        select(func.count())
        .select_from(Device)
        .where(Device.client_id == client_id, Device.revoked_at.is_(None))
    )
    return int(n or 0)


async def subscription_out(db: AsyncSession, sub: Subscription) -> SubscriptionOut:
    plan = await db.get(Plan, sub.plan_id)
    assert plan is not None  # внешний ключ
    return SubscriptionOut.of(
        sub,
        plan_code=plan.code,
        plan_name=plan.name_i18n,
        devices_active=await count_active_devices(db, sub.client_id),
    )
