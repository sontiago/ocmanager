from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, false, true
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin


class Admin(Base, TimestampMixin):
    """Учётная запись админки. Роль одна — `owner` (решение №17); колонка нужна этапу 2."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(server_default="owner")
    # Секрет TOTP лежит зашифрованным (Fernet от SECRET_KEY): дамп БД одним не даёт вторых факторов.
    totp_secret: Mapped[str | None]
    totp_enabled: Mapped[bool] = mapped_column(server_default=false())
    last_login_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(server_default=true())

    __table_args__ = (CheckConstraint("role IN ('owner')", name="role"),)


class AdminSession(Base):
    """Серверная сессия (решение №18): в cookie только токен, в БД — его sha256."""

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    csrf_token: Mapped[str]
    created_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]

    __table_args__ = (Index("ix_admin_sessions_admin_id", "admin_id"),)
