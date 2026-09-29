from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin


class Device(Base, TimestampMixin):
    """Устройство = сертификат = ocserv-username (решение №2: ссылается на клиента)."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    seq: Mapped[int]  # номер у клиента; отозванные номера не переиспользуются
    name: Mapped[str]
    platform: Mapped[str]
    ocserv_username: Mapped[str] = mapped_column(unique=True)  # c{client_id}-d{seq}
    cert_serial: Mapped[str] = mapped_column(unique=True)  # hex
    cert_fingerprint: Mapped[str]
    issued_at: Mapped[datetime]
    cert_expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revocation_reason: Mapped[str | None]
    last_seen_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("client_id", "seq", name="uq_devices_client_id_seq"),
        CheckConstraint(
            "platform IN ('ios', 'android', 'windows', 'macos', 'linux')",
            name="platform",
        ),
        Index("ix_devices_client_id", "client_id"),
    )


class Revocation(Base):
    """Отзыв, который ещё надо отразить в CRL на ноде. applied_at IS NULL — не отражён."""

    __tablename__ = "revocations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), unique=True)
    cert_serial: Mapped[str]
    revoked_at: Mapped[datetime]
    applied_at: Mapped[datetime | None]

    __table_args__ = (
        Index("ix_revocations_pending", "id", postgresql_where=text("applied_at IS NULL")),
    )
