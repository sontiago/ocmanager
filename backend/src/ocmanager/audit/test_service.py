from datetime import UTC, datetime

import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service
from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def test_record_writes_row(session: AsyncSession) -> None:
    actor = Actor(type="admin", id="1", ip="203.0.113.5")
    with time_machine.travel(NOW, tick=False):
        await service.record(
            session,
            actor,
            "device.revoke",
            target_type="device",
            target_id="42",
            details={"reason": "lost"},
        )
    await session.flush()
    row = await session.scalar(select(AuditLog))
    assert row is not None
    assert (row.actor_type, row.actor_id, str(row.ip)) == ("admin", "1", "203.0.113.5")
    assert (row.action, row.target_type, row.target_id) == (
        "device.revoke",
        "device",
        "42",
    )
    assert row.details == {"reason": "lost"}
    assert row.created_at == NOW


async def test_system_actor_defaults(session: AsyncSession) -> None:
    await service.record(session, Actor.system(), "reconcile.fix_allowlist")
    await session.flush()
    row = await session.scalar(select(AuditLog))
    assert row is not None
    assert (row.actor_type, row.actor_id, row.ip, row.details) == (
        "system",
        None,
        None,
        {},
    )


@pytest.mark.parametrize("action", ["", "revoke", "Device.revoke", "device.", "device revoke"])
async def test_invalid_action_rejected(session: AsyncSession, action: str) -> None:
    with pytest.raises(ValueError, match="invalid audit action"):
        await service.record(session, Actor.system(), action)


async def test_actor_type_constrained_in_db(session: AsyncSession) -> None:
    session.add(AuditLog(created_at=NOW, actor_type="robot", action="x.y", details={}))
    with pytest.raises(IntegrityError):
        await session.flush()
