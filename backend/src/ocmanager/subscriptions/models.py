from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Identity, false
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin


class Client(Base, TimestampMixin):
    """Клиент сервиса. Появляется при первом заходе в TMA (или из CLI в dev)."""

    __tablename__ = "clients"

    # id входит в ocserv-username: c{id}-d{n}
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None]
    first_name: Mapped[str]
    lang: Mapped[str]
    trial_used_at: Mapped[datetime | None]
    is_blocked: Mapped[bool] = mapped_column(server_default=false())

    __table_args__ = (CheckConstraint("lang IN ('ru', 'en')", name="lang"),)
