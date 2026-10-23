"""Промокоды: бонусные дни или трафик. Модуль только хранит и учитывает коды; что именно
получает клиент, применяет flows/promo.py (billing не знает про подписки)."""

import re
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import PromoCode, PromoRedemption
from ocmanager.billing.plans import MAX_DURATION_DAYS
from ocmanager.core.errors import Conflict, InvalidInput, NotFound, PromoAlreadyUsed, PromoInvalid

CODE_RE: Final = re.compile(r"^[a-z0-9_-]{3,32}$")
MAX_TRAFFIC_BYTES: Final = 10**15

Kind = Literal["days", "traffic"]

UNSET: Final[Any] = object()  # «поле не передано» — в отличие от None («очистить»)


def normalize(code: str) -> str:
    return code.strip().lower()


def _validate(kind: str, value: int, max_uses: int | None) -> None:
    if kind == "days":
        if not 1 <= value <= MAX_DURATION_DAYS:
            raise InvalidInput(f"days must be 1..{MAX_DURATION_DAYS}")
    elif kind == "traffic":
        if not 1 <= value <= MAX_TRAFFIC_BYTES:
            raise InvalidInput("traffic must be positive")
    else:
        raise InvalidInput("kind must be days or traffic")
    if max_uses is not None and max_uses < 1:
        raise InvalidInput("max_uses must be positive")


async def create(
    session: AsyncSession,
    *,
    code: str,
    kind: str,
    value: int,
    max_uses: int | None = None,
    expires_at: datetime | None = None,
) -> PromoCode:
    """`value` — дни для `days`, байты для `traffic`."""
    clean = normalize(code)
    if not CODE_RE.fullmatch(clean):
        raise InvalidInput("code must be 3..32 characters of a-z, 0-9, _ or -")
    _validate(kind, value, max_uses)
    row = PromoCode(code=clean, kind=kind, value=value, max_uses=max_uses, expires_at=expires_at)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("promo code already exists") from exc
    return row


async def get(session: AsyncSession, promo_id: int) -> PromoCode:
    row = await session.get(PromoCode, promo_id)
    if row is None:
        raise NotFound("promo code not found")
    return row


async def update(
    session: AsyncSession,
    promo_id: int,
    *,
    is_active: bool = UNSET,
    max_uses: int | None = UNSET,
    expires_at: datetime | None = UNSET,
) -> PromoCode:
    row = await get(session, promo_id)
    if is_active is not UNSET:
        row.is_active = is_active
    if max_uses is not UNSET:
        _validate(row.kind, row.value, max_uses)
        row.max_uses = max_uses
    if expires_at is not UNSET:
        row.expires_at = expires_at
    await session.flush()
    return row


async def list_all(session: AsyncSession) -> list[PromoCode]:
    return list(await session.scalars(select(PromoCode).order_by(PromoCode.id.desc())))


async def redemptions(session: AsyncSession, promo_id: int) -> list[PromoRedemption]:
    return list(
        await session.scalars(
            select(PromoRedemption)
            .where(PromoRedemption.promo_code_id == promo_id)
            .order_by(PromoRedemption.id)
        )
    )


async def claim(session: AsyncSession, client_id: int, code: str, now: datetime) -> PromoCode:
    """Резервирует использование кода за клиентом. Строка кода блокируется: два клиента не
    выберут последнее использование одновременно. Исключения не раскрывают причину отказа,
    кроме «уже использовали» — клиенту это полезно и не помогает перебору."""
    row = await session.scalar(
        select(PromoCode).where(PromoCode.code == normalize(code)).with_for_update()
    )
    if row is None or not row.is_active:
        raise PromoInvalid("invalid promo code")
    if row.expires_at is not None and row.expires_at < now:
        raise PromoInvalid("invalid promo code")
    already = await session.scalar(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_code_id == row.id, PromoRedemption.client_id == client_id
        )
    )
    if already is not None:
        raise PromoAlreadyUsed("promo code already used")
    if row.max_uses is not None and row.uses >= row.max_uses:
        raise PromoInvalid("invalid promo code")
    session.add(
        PromoRedemption(promo_code_id=row.id, client_id=client_id, kind=row.kind, value=row.value)
    )
    row.uses += 1
    await session.flush()
    return row
