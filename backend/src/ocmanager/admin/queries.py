"""Чтения, которые нужны нескольким разделам админки."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.schemas import SubscriptionOut
from ocmanager.billing.models import Plan
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Subscription


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
