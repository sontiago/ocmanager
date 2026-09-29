"""Очередь отзывов: какие сертификаты уже отражены в CRL на ноде, а какие ещё нет."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.provisioning.models import Device, Revocation


@dataclass(frozen=True)
class PendingRevocation:
    id: int
    device_id: int
    username: str


async def pending_revocations(session: AsyncSession) -> list[PendingRevocation]:
    """Отзывы, ещё не попавшие в CRL. SKIP LOCKED: параллельный вызов не возьмёт те же строки."""
    rows = await session.execute(
        select(Revocation.id, Revocation.device_id, Device.ocserv_username)
        .join(Device, Device.id == Revocation.device_id)
        .where(Revocation.applied_at.is_(None))
        .order_by(Revocation.id)
        .with_for_update(of=Revocation, skip_locked=True)
    )
    return [PendingRevocation(*row) for row in rows]


async def all_revoked_serials(session: AsyncSession) -> list[tuple[int, datetime]]:
    """Все отозванные серийные номера с моментом отзыва — CRL всегда собирается целиком."""
    rows = await session.execute(
        select(Revocation.cert_serial, Revocation.revoked_at).order_by(Revocation.id)
    )
    return [(int(serial, 16), revoked_at) for serial, revoked_at in rows]


async def mark_applied(session: AsyncSession, ids: Sequence[int], now: datetime) -> None:
    if ids:
        await session.execute(
            update(Revocation).where(Revocation.id.in_(ids)).values(applied_at=now)
        )


async def applied_serials(session: AsyncSession) -> set[int]:
    """Серийные номера, которые уже должны быть в CRL на ноде (для сверки reconcile)."""
    rows = await session.scalars(
        select(Revocation.cert_serial).where(Revocation.applied_at.is_not(None))
    )
    return {int(serial, 16) for serial in rows}
