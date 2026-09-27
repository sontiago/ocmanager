import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow

# <домен>.<глагол>[.<уточнение>]: device.issue, subscription.extend, reconcile.fix_allowlist
ACTION_RE = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")


@dataclass(frozen=True)
class Actor:
    type: Literal["admin", "system", "client"]
    id: str | None = None
    ip: str | None = None

    @classmethod
    def system(cls) -> "Actor":
        return cls(type="system")


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Пишет запись аудита в транзакции вызывающего: откат действия
    откатывает и запись о нём. details — только JSON-скаляры и id, без секретов."""
    if not ACTION_RE.fullmatch(action):
        raise ValueError(f"invalid audit action {action!r}")
    session.add(
        AuditLog(
            created_at=utcnow(),
            actor_type=actor.type,
            actor_id=actor.id,
            ip=actor.ip,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )
