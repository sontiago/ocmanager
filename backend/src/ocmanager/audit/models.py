from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base


class AuditLog(Base):
    """Каждое действие admin / system / client, меняющее состояние (дизайн §11)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime]
    actor_type: Mapped[str]
    actor_id: Mapped[str | None]
    ip: Mapped[str | None] = mapped_column(INET)
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint("actor_type IN ('admin', 'system', 'client')", name="actor_type"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_target", "target_type", "target_id", "created_at"),
    )
