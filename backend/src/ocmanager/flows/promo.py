"""Склейка billing (коды) + subscriptions (что получает клиент) + audit."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing import promo
from ocmanager.core.errors import NotApplicable, PromoInvalid, SubscriptionInactive
from ocmanager.subscriptions import service as subscriptions


@dataclass(frozen=True)
class Redeemed:
    kind: str  # days | traffic
    value: int  # дни или байты


async def redeem(
    session: AsyncSession, client_id: int, code: str, actor: Actor, now: datetime
) -> Redeemed:
    """Погашает промокод. Резервирование и применение — в одной вложенной транзакции: если
    применить нельзя, код не расходуется.

    Порядок защищает от подбора кодов. Сначала проверяется право клиента на любой промокод
    (подписка есть, не заблокирован) — отказ одинаков для действующего и выдуманного кода.
    Отказы после резервирования (трафик без лимита, истёкшая подписка) выглядят как
    «недействительный код»: по ним нельзя отличить настоящий код."""
    client = await subscriptions.get_client(session, client_id)
    if client.is_blocked:
        raise SubscriptionInactive("no active subscription", blocked=True)
    if await subscriptions.get_subscription(session, client_id) is None:
        raise SubscriptionInactive("no active subscription")
    try:
        async with session.begin_nested():
            row = await promo.claim(session, client_id, code, now)
            if row.kind == "days":
                await subscriptions.extend_days(session, client_id, row.value, now)
            else:
                await subscriptions.grant_traffic(session, client_id, row.value, now)
    except (SubscriptionInactive, NotApplicable) as exc:
        raise PromoInvalid("invalid promo code") from exc
    await audit.record(
        session,
        actor,
        "promo.redeem",
        target_type="client",
        target_id=str(client_id),
        details={"code": row.code, "kind": row.kind, "value": row.value},
    )
    return Redeemed(kind=row.kind, value=row.value)
