from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base


class EventOutbox(Base):
    """Доменные события, записанные в той же транзакции, что и изменение.
    Доставляет events.bus.dispatch_pending из воркера."""

    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str]
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    available_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(server_default=text("0"), default=0)
    last_error: Mapped[str | None]
    dispatched_at: Mapped[datetime | None]

    __table_args__ = (
        Index(
            "ix_event_outbox_pending",
            "available_at",
            "id",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )
