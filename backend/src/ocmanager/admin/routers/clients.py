from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, or_, select

from ocmanager.admin.deps import CaDep, CurrentAdmin, FernetDep, RedisDep, commit_and_kick
from ocmanager.admin.pagination import BigId, Page, PageDep, page_of
from ocmanager.admin.queries import online_usernames, subscription_out
from ocmanager.admin.schemas import (
    ActionOut,
    ClientOut,
    DailyTrafficOut,
    DeviceOut,
    SessionRowOut,
    SubscriptionOut,
)
from ocmanager.audit import service as audit
from ocmanager.billing.models import Plan
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import NotFound
from ocmanager.flows import devices as device_flows
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.flows.grants import grant_plan
from ocmanager.nodes import traffic
from ocmanager.nodes.models import SessionLog, TrafficDaily
from ocmanager.provisioning import delivery
from ocmanager.provisioning import service as provisioning
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.service import Platform
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.state import MAX_DAYS

router = APIRouter(tags=["clients"])

ClientStatus = Literal[
    "pending_payment", "trial", "active", "expired", "exhausted", "cancelled", "blocked", "none"
]  # none — подписки нет вовсе
SESSIONS_IN_CARD = 50
TRAFFIC_DAYS = 30


class ClientRow(ClientOut):
    subscription_status: str | None
    plan_code: str | None
    expires_at: datetime | None
    devices_active: int


class ClientCard(BaseModel):
    client: ClientOut
    subscription: SubscriptionOut | None
    devices: list[DeviceOut]  # все, включая отозванные
    traffic_daily: list[DailyTrafficOut]  # за 30 дней по дням, по возрастанию
    sessions: list[SessionRowOut]  # последние 50
    payments: list[object]  # появится вместе с платежами (Фаза 5)


class GrantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str = Field(max_length=64)
    days: int | None = Field(None, ge=1, le=MAX_DAYS)


class ExtendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=MAX_DAYS)


class IssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)  # точные правила — provisioning.clean_name
    platform: Platform


class IssuedOut(BaseModel):
    device: DeviceOut
    p12_password: str
    download_path: str
    download_expires_at: datetime


def _like(term: str) -> str:
    """Спецсимволы LIKE — обычные символы: поиск по `%` не должен находить всех."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/clients")
async def list_clients(
    ctx: CurrentAdmin,
    db: SessionDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=64)] = None,
    status: ClientStatus | None = None,
    blocked: bool | None = None,
) -> Page[ClientRow]:
    conds: list[ColumnElement[bool]] = []
    if q and (term := q.strip().removeprefix("@")):
        clauses: list[ColumnElement[bool]] = [
            Client.username.ilike(_like(term), escape="\\"),
            Client.first_name.ilike(_like(term), escape="\\"),
        ]
        # 18 цифр всегда влезают в BIGINT; длиннее — это не telegram_id.
        if term.isascii() and term.isdigit() and len(term) <= 18:
            clauses.append(Client.telegram_id == int(term))
        conds.append(or_(*clauses))
    if status == "none":
        conds.append(Subscription.id.is_(None))
    elif status is not None:
        conds.append(Subscription.status == status)
    if blocked is not None:
        conds.append(Client.is_blocked.is_(blocked))

    joined = Client.__table__.outerjoin(Subscription, Subscription.client_id == Client.id)
    total = await db.scalar(select(func.count()).select_from(joined).where(*conds))
    active_devices = (
        select(func.count())
        .where(Device.client_id == Client.id, Device.revoked_at.is_(None))
        .correlate(Client)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(
            Client,
            Subscription.status,
            Subscription.expires_at,
            Plan.code,
            active_devices,
        )
        .outerjoin(Subscription, Subscription.client_id == Client.id)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .where(*conds)
        .order_by(Client.created_at.desc(), Client.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [
        ClientRow(
            **ClientOut.of(client).model_dump(),
            subscription_status=sub_status,
            plan_code=plan_code,
            expires_at=expires_at,
            devices_active=int(n),
        )
        for client, sub_status, expires_at, plan_code, n in rows
    ]
    return page_of(items, int(total or 0), page)


@router.get("/clients/{client_id}")
async def client_card(
    client_id: BigId, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> ClientCard:
    now = utcnow()
    client = await subscriptions.get_client(db, client_id)
    sub = await subscriptions.get_subscription(db, client_id)
    devices = await provisioning.list_devices(db, client_id, include_revoked=True)
    names = [d.ocserv_username for d in devices]

    since = sub.traffic_period_start if sub else now - timedelta(days=TRAFFIC_DAYS)
    used = await traffic.usage_since(db, names, since)
    online = await online_usernames(db, redis)

    first_day = (now - timedelta(days=TRAFFIC_DAYS - 1)).date()
    daily = await db.execute(
        select(
            TrafficDaily.day,
            func.sum(TrafficDaily.bytes_in),
            func.sum(TrafficDaily.bytes_out),
        )
        .where(TrafficDaily.username.in_(names), TrafficDaily.day >= first_day)
        .group_by(TrafficDaily.day)
        .order_by(TrafficDaily.day)
    )
    sessions = await db.scalars(
        select(SessionLog)
        .where(SessionLog.username.in_(names))
        .order_by(SessionLog.started_at.desc(), SessionLog.id.desc())
        .limit(SESSIONS_IN_CARD)
    )
    return ClientCard(
        client=ClientOut.of(client),
        subscription=None if sub is None else await subscription_out(db, sub),
        devices=[
            DeviceOut.of(
                d,
                is_online=None if online is None else d.ocserv_username in online,
                traffic_bytes=used[d.ocserv_username],
            )
            for d in devices
        ],
        traffic_daily=[
            DailyTrafficOut(day=day, bytes_in=int(rx), bytes_out=int(tx)) for day, rx, tx in daily
        ],
        sessions=[SessionRowOut.of(s) for s in sessions],
        payments=[],
    )


async def _set_blocked(
    client_id: int, blocked: bool, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> ActionOut:
    changed = await subscription_flows.set_blocked(db, client_id, blocked, ctx.actor, utcnow())
    await commit_and_kick(db, redis)
    return ActionOut(changed=changed)


@router.post("/clients/{client_id}/block")
async def block(client_id: BigId, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep) -> ActionOut:
    return await _set_blocked(client_id, True, ctx, db, redis)


@router.post("/clients/{client_id}/unblock")
async def unblock(
    client_id: BigId, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> ActionOut:
    return await _set_blocked(client_id, False, ctx, db, redis)


@router.post("/clients/{client_id}/grant")
async def grant(
    client_id: BigId, body: GrantBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> SubscriptionOut:
    """«Выдать вручную»: тариф без оплаты и без автопродления."""
    sub = await grant_plan(
        db,
        client_id=client_id,
        plan_code=body.plan_code,
        actor=ctx.actor,
        now=utcnow(),
        days=body.days,
    )
    out = await subscription_out(db, sub)
    await commit_and_kick(db, redis)
    return out


@router.post("/clients/{client_id}/extend")
async def extend(
    client_id: BigId, body: ExtendBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> SubscriptionOut:
    sub = await subscription_flows.extend_days(db, client_id, body.days, ctx.actor, utcnow())
    out = await subscription_out(db, sub)
    await commit_and_kick(db, redis)
    return out


@router.post("/clients/{client_id}/devices")
async def issue_device(
    client_id: BigId,
    body: IssueBody,
    response: Response,
    ctx: CurrentAdmin,
    db: SessionDep,
    redis: RedisDep,
    ca: CaDep,
    fernet: FernetDep,
) -> IssuedOut:
    """Те же проверки подписки и лимита, что и из TMA: ключ клиенту без доступа не выдать —
    сначала `grant`. Пароль и ссылка отдаются один раз."""
    now = utcnow()
    bundle = await device_flows.issue_for_client(
        db,
        redis,
        client_id=client_id,
        name=body.name,
        platform=body.platform,
        ca=ca,
        fernet=fernet,
        actor=ctx.actor,
        now=now,
    )
    await commit_and_kick(db, redis)
    response.headers["Cache-Control"] = "no-store"
    return IssuedOut(
        device=DeviceOut.of(bundle.device, is_online=False, traffic_bytes=0),
        p12_password=bundle.password,
        download_path=f"/admin/downloads/{bundle.ticket.token}",
        download_expires_at=bundle.ticket.expires_at,
    )


@router.get("/downloads/{token}")
async def download_p12(
    token: Annotated[str, Path(min_length=16, max_length=128)],
    ctx: CurrentAdmin,
    db: SessionDep,
    redis: RedisDep,
    fernet: FernetDep,
) -> Response:
    """`.p12` один раз: повторный запрос — 404, как и просроченная ссылка."""
    taken = await delivery.take_p12(redis, fernet, token)
    if taken is None:
        raise NotFound("link expired or already used")
    filename, data = taken
    await audit.record(db, ctx.actor, "device.download", details={"filename": filename})
    await db.commit()
    return Response(
        data,
        media_type="application/x-pkcs12",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
