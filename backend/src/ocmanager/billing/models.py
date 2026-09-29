from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin


class Plan(Base, TimestampMixin):
    """Тариф. Тариф с is_trial — скрытый: не в каталоге, нужен только для старта trial."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB)
    description_i18n: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    duration_days: Mapped[int]
    device_limit: Mapped[int]
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)  # None = безлимит
    speed_limit_kbps: Mapped[int | None]
    price_amount: Mapped[int] = mapped_column(BigInteger)  # минорные единицы
    currency: Mapped[str]
    provider_product_ids: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    is_trial: Mapped[bool] = mapped_column(server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))

    __table_args__ = (
        CheckConstraint("duration_days > 0", name="duration_days"),
        CheckConstraint("device_limit > 0", name="device_limit"),
        CheckConstraint("price_amount >= 0", name="price_amount"),
        CheckConstraint("traffic_limit_bytes IS NULL OR traffic_limit_bytes > 0", name="traffic"),
        # Не больше одного trial-тарифа: частичный уникальный индекс по is_trial.
        Index(
            "uq_plans_single_trial",
            "is_trial",
            unique=True,
            postgresql_where=text("is_trial"),
        ),
    )
