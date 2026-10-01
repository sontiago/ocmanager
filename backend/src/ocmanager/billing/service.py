"""Платежи: запись, возврат, поиск тарифа по продукту провайдера. Аудит здесь не пишется
(граница модулей) — его пишет flows/purchase.py."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Payment, Plan
from ocmanager.core.errors import NotFound


async def record_payment(
    session: AsyncSession,
    *,
    provider: str,
    external_id: str,
    client_id: int,
    plan_id: int | None,
    amount: int,
    currency: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> Payment | None:
    """Записывает платёж. None — платёж с таким (provider, external_id) уже есть.
    `ON CONFLICT DO NOTHING`: два одновременных вебхука про один платёж не дают ни дубля,
    ни ошибки — второй ждёт коммита первого и получает None."""
    stmt = (
        insert(Payment)
        .values(
            provider=provider,
            external_id=external_id,
            client_id=client_id,
            plan_id=plan_id,
            amount=amount,
            currency=currency,
            status="succeeded",
            raw_payload=dict(payload),
            received_at=now,
        )
        .on_conflict_do_nothing(index_elements=[Payment.provider, Payment.external_id])
        .returning(Payment)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_payment(session: AsyncSession, provider: str, external_id: str) -> Payment:
    payment: Payment | None = await session.scalar(
        select(Payment).where(Payment.provider == provider, Payment.external_id == external_id)
    )
    if payment is None:
        raise NotFound("payment not found")
    return payment


@dataclass(frozen=True)
class Refund:
    payment: Payment
    changed: bool  # False — платёж уже был возвращён: повтор не плодит событий


async def mark_refunded(session: AsyncSession, provider: str, external_id: str) -> Refund | None:
    """None — такого платежа нет. Доступ не трогается (П5-10): это решает человек."""
    payment: Payment | None = await session.scalar(
        select(Payment)
        .where(Payment.provider == provider, Payment.external_id == external_id)
        .with_for_update()
    )
    if payment is None:
        return None
    if payment.status == "refunded":
        return Refund(payment, changed=False)
    payment.status = "refunded"
    await session.flush()
    return Refund(payment, changed=True)


async def find_plan_by_product(
    session: AsyncSession, provider: str, product_ref: str
) -> Plan | None:
    """Тариф, привязанный к продукту: `provider_product_ids -> <провайдер> -> product_ref`.
    Неактивный тариф тоже подходит — за него уже заплатили; скрытый trial — нет."""
    plan: Plan | None = await session.scalar(
        select(Plan)
        .where(
            Plan.is_trial.is_(False),
            func.jsonb_extract_path_text(Plan.provider_product_ids, provider, "product_ref")
            == product_ref,
        )
        .order_by(Plan.id)
        .limit(1)
    )
    return plan
