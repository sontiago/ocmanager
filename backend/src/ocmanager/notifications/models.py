from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base

RECIPIENT_TYPES = ("client", "admin")
MESSAGE_STATUSES = ("pending", "sent", "failed", "undeliverable")


class OutboxMessage(Base):
    """Исходящее сообщение в Telegram. Кладётся обработчиками событий в транзакции доставки
    события, отправляется задачей воркера (tasks.py): сбой Telegram не откатывает
    доменные события."""

    __tablename__ = "outbox_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_type: Mapped[str]
    chat_id: Mapped[int] = mapped_column(BigInteger)
    template_key: Mapped[str]
    lang: Mapped[str]
    payload: Mapped[dict[str, Any]]
    # Защита от дублей: событие, дошедшее до обработчика дважды, не шлёт второе сообщение.
    # Уникален в паре с chat_id (П6-2): один алерт — по сообщению на каждого админа.
    dedupe_key: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default=text("0"), default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    send_after: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    last_error: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint("chat_id", "dedupe_key", name="uq_outbox_messages_chat_id_dedupe_key"),
        CheckConstraint(
            "recipient_type IN ('" + "', '".join(RECIPIENT_TYPES) + "')", name="recipient_type"
        ),
        CheckConstraint("status IN ('" + "', '".join(MESSAGE_STATUSES) + "')", name="status"),
        CheckConstraint("lang IN ('ru', 'en')", name="lang"),
        # Доставка ищет только ждущие сообщения — индекс остаётся маленьким.
        Index(
            "ix_outbox_messages_pending",
            "send_after",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
    )
