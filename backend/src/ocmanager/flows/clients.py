"""Склейка subscriptions + audit: регистрация клиента."""

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.subscriptions import service
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.service import UpsertResult


async def register_client(
    session: AsyncSession, ident: TelegramIdentity, *, actor: Actor | None = None
) -> UpsertResult:
    """Создаёт или обновляет клиента. В аудит попадает только создание;
    по умолчанию действует сам клиент (заход в TMA), в dev — оператор из CLI."""
    result = await service.upsert_client(session, ident)
    if result.created:
        await audit.record(
            session,
            actor or Actor(type="client", id=str(result.client.id)),
            "client.create",
            target_type="client",
            target_id=str(result.client.id),
            details={"telegram_id": ident.telegram_id},
        )
    return result
