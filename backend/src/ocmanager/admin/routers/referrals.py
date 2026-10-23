from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from ocmanager.admin.deps import CurrentAdmin
from ocmanager.admin.pagination import Page, PageDep, page_of
from ocmanager.billing.models import Payment
from ocmanager.core.db import SessionDep
from ocmanager.subscriptions.models import Client, ReferralReward
from ocmanager.subscriptions.referral import TIERS

router = APIRouter(prefix="/referrals", tags=["referrals"])


class TierStat(BaseModel):
    friends: int
    reached: int  # сколько пригласивших достигли уровня


class ReferralStats(BaseModel):
    invited: int  # клиентов, пришедших по ссылке
    paying: int  # из них оплативших
    conversion_percent: int
    days_given: int  # зачисленные дни: пригласившим (applied) и приглашённым
    devices_given: int
    traffic_bytes_given: int
    tiers: list[TierStat]


@router.get("/stats")
async def stats(ctx: CurrentAdmin, db: SessionDep) -> ReferralStats:
    invited = int(
        await db.scalar(
            select(func.count()).select_from(Client).where(Client.referred_by.is_not(None))
        )
        or 0
    )
    base = ReferralReward.kind == "base"
    paying = int(await db.scalar(select(func.count()).select_from(ReferralReward).where(base)) or 0)
    inviter_days = await db.scalar(
        select(func.coalesce(func.sum(ReferralReward.days), 0)).where(
            ReferralReward.status == "applied"
        )
    )
    invitee_days = await db.scalar(
        select(func.coalesce(func.sum(ReferralReward.invitee_days), 0)).where(base)
    )
    devices = await db.scalar(select(func.coalesce(func.sum(ReferralReward.devices), 0)))
    traffic = await db.scalar(select(func.coalesce(func.sum(ReferralReward.traffic_bytes), 0)))
    reached = {
        tier: int(count)
        for tier, count in await db.execute(
            select(ReferralReward.tier, func.count())
            .where(ReferralReward.kind == "tier")
            .group_by(ReferralReward.tier)
        )
    }
    return ReferralStats(
        invited=invited,
        paying=paying,
        conversion_percent=round(paying * 100 / invited) if invited else 0,
        days_given=int(inviter_days or 0) + int(invitee_days or 0),
        devices_given=int(devices or 0),
        traffic_bytes_given=int(traffic or 0),
        tiers=[TierStat(friends=t.friends, reached=reached.get(t.friends, 0)) for t in TIERS],
    )


class RewardRow(BaseModel):
    id: int
    created_at: datetime
    inviter_id: int
    inviter_name: str
    invitee_id: int
    invitee_name: str
    kind: Literal["base", "tier"]
    tier: int | None
    days: int
    invitee_days: int
    devices: int
    traffic_bytes: int
    status: Literal["applied", "pending", "capped"]
    payment_id: int
    payment_status: str  # refunded — награда за возвращённый платёж: решает админ


@router.get("/rewards")
async def rewards(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    inviter_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
) -> Page[RewardRow]:
    inviter, invitee = aliased(Client), aliased(Client)
    conds = [] if inviter_id is None else [ReferralReward.inviter_id == inviter_id]
    total = await db.scalar(select(func.count()).select_from(ReferralReward).where(*conds))
    rows = await db.execute(
        select(ReferralReward, inviter.first_name, invitee.first_name, Payment.status)
        .join(inviter, inviter.id == ReferralReward.inviter_id)
        .join(invitee, invitee.id == ReferralReward.invitee_id)
        .join(Payment, Payment.id == ReferralReward.payment_id)
        .where(*conds)
        .order_by(ReferralReward.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [
        RewardRow(
            id=r.id,
            created_at=r.created_at,
            inviter_id=r.inviter_id,
            inviter_name=inviter_name,
            invitee_id=r.invitee_id,
            invitee_name=invitee_name,
            kind=r.kind,
            tier=r.tier,
            days=r.days,
            invitee_days=r.invitee_days,
            devices=r.devices,
            traffic_bytes=r.traffic_bytes,
            status=r.status,
            payment_id=r.payment_id,
            payment_status=payment_status,
        )
        for r, inviter_name, invitee_name, payment_status in rows
    ]
    return page_of(items, int(total or 0), page)
