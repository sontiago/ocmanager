from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    false,
    text,
    true,
)
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


class SessionLog(Base):
    """Сессия VPN. Ключ — username, а не device_id (решение №3): nodes не знает про устройства."""

    __tablename__ = "session_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    username: Mapped[str]
    # ID из occtl уникален лишь в пределах жизни процесса ocserv: ключ — вместе с started_at.
    ocserv_session_id: Mapped[str]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    client_ip: Mapped[str | None]
    vpn_ip: Mapped[str | None]
    # Последние учтённые кумулятивные счётчики сессии: от них считается следующая дельта.
    bytes_in: Mapped[int] = mapped_column(BigInteger)
    bytes_out: Mapped[int] = mapped_column(BigInteger)
    last_polled_at: Mapped[datetime]
    final_received: Mapped[bool] = mapped_column(server_default=false())  # пришёл disconnect-хук

    __table_args__ = (
        UniqueConstraint(
            "node_id", "ocserv_session_id", "started_at", name="uq_session_log_node_session"
        ),
        Index("ix_session_log_open", "node_id", postgresql_where=text("ended_at IS NULL")),
        Index("ix_session_log_username", "username", "started_at"),
    )


class TrafficSample(Base):
    """Прирост трафика между двумя опросами. Хранится traffic_retention_days."""

    __tablename__ = "traffic_samples"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    username: Mapped[str]
    ts: Mapped[datetime]
    bytes_in_delta: Mapped[int] = mapped_column(BigInteger)
    bytes_out_delta: Mapped[int] = mapped_column(BigInteger)
    duration_sec: Mapped[int]

    __table_args__ = (
        Index("ix_traffic_samples_username_ts", "username", "ts"),
        Index("ix_traffic_samples_ts", "ts"),
    )


class TrafficDaily(Base):
    """Суточные итоги, хранятся бессрочно."""

    __tablename__ = "traffic_daily"

    username: Mapped[str] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    bytes_in: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    bytes_out: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    duration_sec: Mapped[int] = mapped_column(server_default=text("0"))
