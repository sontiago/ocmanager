from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, text, true
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin


class Node(Base, TimestampMixin):
    """Нода ocserv. В этапе 1 одна — "local" (LocalDockerDriver)."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    driver: Mapped[str]
    # Только для отображения. Имя контейнера и пути драйвер берёт из Settings.
    config: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    public_host: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="unknown")
    last_seen_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(server_default=true())
    last_reconcile_at: Mapped[datetime | None]  # пишет Задача 2.8
    last_reconcile_report: Mapped[dict[str, Any] | None]  # пишет Задача 2.8

    __table_args__ = (
        CheckConstraint("status IN ('unknown', 'online', 'degraded', 'offline')", name="status"),
        CheckConstraint("driver IN ('local_docker')", name="driver"),
    )
