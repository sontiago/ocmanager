from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, or_, select

from ocmanager.admin.deps import CurrentAdmin, RedisDep, commit_and_kick
from ocmanager.admin.pagination import BigId, Page, PageDep, like_pattern, page_of
from ocmanager.admin.schemas import SessionRowOut
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import NodeUnavailable, NotFound
from ocmanager.flows import devices as device_flows
from ocmanager.flows.nodes import online_usernames
from ocmanager.nodes.models import SessionLog
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.service import MAX_REASON_LEN, Platform
from ocmanager.subscriptions.models import Client

router = APIRouter(tags=["devices"])


class DeviceRow(BaseModel):
    id: int
    client_id: int
    telegram_id: int
    client_name: str
    seq: int
    name: str
    platform: str
    username: str
    issued_at: datetime
    cert_expires_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    last_seen_at: datetime | None
    is_online: bool | None  # None — кэш состояния ноды пуст

    @classmethod
    def of(cls, d: Device, c: Client, *, online: set[str] | None) -> "DeviceRow":
        return cls(
            id=d.id,
            client_id=d.client_id,
            telegram_id=c.telegram_id,
            client_name=c.first_name,
            seq=d.seq,
            name=d.name,
            platform=d.platform,
            username=d.ocserv_username,
            issued_at=d.issued_at,
            cert_expires_at=d.cert_expires_at,
            revoked_at=d.revoked_at,
            revocation_reason=d.revocation_reason,
            last_seen_at=d.last_seen_at,
            is_online=None if online is None else d.ocserv_username in online,
        )


class RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LEN)


@router.get("/devices")
async def list_devices(
    ctx: CurrentAdmin,
    db: SessionDep,
    redis: RedisDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=64)] = None,
    platform: Platform | None = None,
    revoked: bool | None = None,
    online: bool | None = None,
) -> Page[DeviceRow]:
    """`online` — по кэшу состояния ноды, который раз в минуту обновляет воркер. Если кэша
    нет, фильтровать нечем, и это честный отказ, а не «никто не подключён»."""
    known = await online_usernames(db, redis)
    conds: list[ColumnElement[bool]] = []
    if q and (term := q.strip()):
        clauses: list[ColumnElement[bool]] = [
            Device.ocserv_username.ilike(like_pattern(term), escape="\\"),
            Device.name.ilike(like_pattern(term), escape="\\"),
        ]
        if term.isascii() and term.isdigit() and len(term) <= 18:
            clauses.append(Client.telegram_id == int(term))
        conds.append(or_(*clauses))
    if platform is not None:
        conds.append(Device.platform == platform)
    if revoked is not None:
        conds.append(Device.revoked_at.is_not(None) if revoked else Device.revoked_at.is_(None))
    if online is not None:
        if known is None:
            raise NodeUnavailable("node state is unknown: no cached status (is the worker up?)")
        conds.append(
            Device.ocserv_username.in_(known) if online else Device.ocserv_username.not_in(known)
        )

    base = select(Device, Client).join(Client, Client.id == Device.client_id).where(*conds)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.execute(base.order_by(Device.id.desc()).limit(page.limit).offset(page.offset))
    items = [DeviceRow.of(d, c, online=known) for d, c in rows]
    return page_of(items, int(total or 0), page)


@router.post("/devices/{device_id}/revoke")
async def revoke_device(
    device_id: BigId, body: RevokeBody, ctx: CurrentAdmin, db: SessionDep, redis: RedisDep
) -> DeviceRow:
    """Отзыв необратим: сертификат уходит в CRL, номер устройства не переиспользуется.
    Повторный вызов ничего не меняет и возвращает то же устройство."""
    device = await device_flows.revoke_device(
        db, device_id, owner_client_id=None, reason=body.reason, actor=ctx.actor, now=utcnow()
    )
    client = await db.get(Client, device.client_id)
    assert client is not None  # внешний ключ
    row = DeviceRow.of(device, client, online=await online_usernames(db, redis))
    await commit_and_kick(db, redis)
    return row


@router.get("/devices/{device_id}/sessions")
async def device_sessions(
    device_id: BigId, ctx: CurrentAdmin, db: SessionDep, page: PageDep
) -> Page[SessionRowOut]:
    device = await db.get(Device, device_id)
    if device is None:
        raise NotFound("device not found")
    where = SessionLog.username == device.ocserv_username
    total = await db.scalar(select(func.count()).select_from(SessionLog).where(where))
    rows = await db.scalars(
        select(SessionLog)
        .where(where)
        .order_by(SessionLog.started_at.desc(), SessionLog.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return page_of([SessionRowOut.of(s) for s in rows], int(total or 0), page)
