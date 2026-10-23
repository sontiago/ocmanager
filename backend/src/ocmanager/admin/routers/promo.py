from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select

from ocmanager.admin.deps import CurrentAdmin
from ocmanager.admin.pagination import BigId
from ocmanager.audit import service as audit
from ocmanager.billing import promo
from ocmanager.billing.models import PromoCode, PromoRedemption
from ocmanager.core.db import SessionDep
from ocmanager.subscriptions.models import Client

router = APIRouter(prefix="/promo-codes", tags=["promo"])

GIB = 1024**3


def _units(kind: str, value: int) -> int:
    """В админке трафик — гибибайты, дни — дни: в базе байты и дни."""
    return value // GIB if kind == "traffic" else value


class PromoOut(BaseModel):
    id: int
    code: str
    kind: Literal["days", "traffic"]
    value: int  # дни или ГБ
    max_uses: int | None
    uses: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime

    @classmethod
    def of(cls, row: PromoCode) -> "PromoOut":
        return cls(
            id=row.id,
            code=row.code,
            kind=row.kind,
            value=_units(row.kind, row.value),
            max_uses=row.max_uses,
            uses=row.uses,
            expires_at=row.expires_at,
            is_active=row.is_active,
            created_at=row.created_at,
        )


class PromoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(max_length=64)]
    kind: Literal["days", "traffic"]
    value: int  # дни или ГБ
    max_uses: int | None = None
    expires_at: AwareDatetime | None = None


class PromoPatch(BaseModel):
    """Переданное поле меняется; `null` у max_uses/expires_at очищает ограничение."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    max_uses: int | None = None
    expires_at: AwareDatetime | None = None


class RedemptionOut(BaseModel):
    id: int
    client_id: int
    client_name: str
    kind: Literal["days", "traffic"]
    value: int
    redeemed_at: datetime


@router.get("")
async def list_promo_codes(ctx: CurrentAdmin, db: SessionDep) -> list[PromoOut]:
    return [PromoOut.of(p) for p in await promo.list_all(db)]


@router.post("", status_code=201)
async def create_promo_code(body: PromoCreate, ctx: CurrentAdmin, db: SessionDep) -> PromoOut:
    stored = body.value * GIB if body.kind == "traffic" else body.value
    row = await promo.create(
        db,
        code=body.code,
        kind=body.kind,
        value=stored,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
    )
    await audit.record(
        db,
        ctx.actor,
        "promo.create",
        target_type="promo",
        target_id=str(row.id),
        details={
            "code": row.code,
            "kind": row.kind,
            "value": body.value,
            "max_uses": row.max_uses,
        },
    )
    out = PromoOut.of(row)
    await db.commit()
    return out


@router.patch("/{promo_id}")
async def update_promo_code(
    promo_id: BigId, body: PromoPatch, ctx: CurrentAdmin, db: SessionDep
) -> PromoOut:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if "is_active" in changes and changes["is_active"] is None:
        del changes["is_active"]  # null у флага — не «выключить», а «не менять»
    row = await promo.update(db, promo_id, **changes)
    if changes:
        await audit.record(
            db,
            ctx.actor,
            "promo.update",
            target_type="promo",
            target_id=str(row.id),
            details={"code": row.code, "changes": {k: str(v) for k, v in changes.items()}},
        )
    out = PromoOut.of(row)
    await db.commit()
    return out


@router.get("/{promo_id}/redemptions")
async def redemptions(promo_id: BigId, ctx: CurrentAdmin, db: SessionDep) -> list[RedemptionOut]:
    await promo.get(db, promo_id)  # 404, если кода нет
    rows = await db.execute(
        select(PromoRedemption, Client.first_name)
        .join(Client, Client.id == PromoRedemption.client_id)
        .where(PromoRedemption.promo_code_id == promo_id)
        .order_by(PromoRedemption.id.desc())
    )
    return [
        RedemptionOut(
            id=r.id,
            client_id=r.client_id,
            client_name=name,
            kind=r.kind,
            value=_units(r.kind, r.value),
            redeemed_at=r.redeemed_at,
        )
        for r, name in rows
    ]
