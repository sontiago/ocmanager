from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.flows.clients import register_client
from ocmanager.subscriptions.schemas import TelegramIdentity

IDENT = TelegramIdentity(5001, "Anna", "anna", "ru")


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


async def test_creation_is_audited_once_as_the_client(session: AsyncSession) -> None:
    result = await register_client(session, IDENT)
    await register_client(session, IDENT)
    [row] = await audit_rows(session)
    assert (row.actor_type, row.actor_id) == ("client", str(result.client.id))
    assert (row.action, row.target_id) == ("client.create", str(result.client.id))
    assert row.details == {"telegram_id": 5001}


async def test_explicit_actor(session: AsyncSession) -> None:
    await register_client(session, IDENT, actor=Actor("admin", "cli"))
    [row] = await audit_rows(session)
    assert (row.actor_type, row.actor_id) == ("admin", "cli")
