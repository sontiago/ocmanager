"""Склейка billing (коды) + subscriptions (что получает клиент) + audit."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing import promo
from ocmanager.core.errors import SubscriptionInactive
from ocmanager.subscriptions import service as subscriptions


@dataclass(frozen=True)
class Redeemed:
    kind: str  # days | traffic
    value: int  # дни или байты


async def redeem(
    session: AsyncSession, client_id: int, code: str, actor: Actor, now: datetime
) -> Redeemed:
    """Погашает промокод. Резервирование и применение — в одной вложенной транзакции: если
    у клиента нет подходящей подписки, код не расходуется."""
    async with session.begin_nested():
        row = await promo.claim(session, client_id, code, now)
        if row.kind == "days":
            if await subscriptions.get_subscription(session, client_id) is None:
                raise SubscriptionInactive("no active subscription")
            await subscriptions.extend_days(session, client_id, row.value, now)
        else:
            await subscriptions.grant_traffic(session, client_id, row.value, now)
    await audit.record(
        session,
        actor,
        "promo.redeem",
        target_type="client",
        target_id=str(client_id),
        details={"code": row.code, "kind": row.kind, "value": row.value},
    )
    return Redeemed(kind=row.kind, value=row.value)
