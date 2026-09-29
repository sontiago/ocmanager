"""Обработчики доменных событий. Регистрируются явно — `register(settings)` при
старте воркера, а не при импорте: иначе любой тест, импортировавший модуль,
получил бы боевые обработчики в глобальном реестре шины."""

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events import bus
from ocmanager.events.types import (
    ClientBlocked,
    ClientUnblocked,
    DeviceIssued,
    DeviceRevoked,
    SubscriptionActivated,
    SubscriptionExpired,
    SubscriptionRenewed,
)
from ocmanager.flows.access import sync_all_nodes

ACCESS_EVENTS = (
    SubscriptionActivated,
    SubscriptionRenewed,
    SubscriptionExpired,
    ClientBlocked,
    ClientUnblocked,
    DeviceIssued,
    DeviceRevoked,
)


def register(settings: Settings) -> None:
    """Вызывается один раз на процесс воркера."""

    @bus.on(*ACCESS_EVENTS)
    async def sync_node_access(_: object, session: AsyncSession) -> None:
        # Событие говорит лишь «что-то изменилось»: список пересчитывается целиком.
        await sync_all_nodes(session, settings, utcnow())
