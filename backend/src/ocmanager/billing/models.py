from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    UniqueConstraint,
    func,
    text,
    true,
)
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


WEBHOOK_STATUSES = ("received", "processed", "ignored", "failed", "dead", "rejected")


class WebhookEvent(Base):
    """Вебхук провайдера в том виде, в каком он пришёл. Сначала сохраняется сырым и получает 200,
    обработка идёт из воркера: любой баг в бизнес-логике не превращается в шторм повторов."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str]
    external_event_id: Mapped[str]
    signature_ok: Mapped[bool]
    payload: Mapped[dict[str, Any]]  # JSONB; {} — тело не JSON-объект или подпись неверна
    raw_body: Mapped[bytes] = mapped_column(LargeBinary)  # точные байты: по ним считалась подпись
    status: Mapped[str] = mapped_column(server_default="received")
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_webhook_events_provider_external_event_id",
        ),
        CheckConstraint(
            "status IN ('" + "', '".join(WEBHOOK_STATUSES) + "')",
            name="status",
        ),
        # Подметальщик и админка ищут по статусу и давности.
        Index("ix_webhook_events_status_received", "status", "received_at"),
    )


class Payment(Base):
    """Деньги, полученные от провайдера. История платежей не удаляется и не правится, кроме
    статуса при возврате. UNIQUE(provider, external_id) — второй барьер идемпотентности."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    provider: Mapped[str]
    external_id: Mapped[str]
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    amount: Mapped[int] = mapped_column(BigInteger)  # минорные единицы
    currency: Mapped[str]
    status: Mapped[str]
    raw_payload: Mapped[dict[str, Any]]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Доступ выдан, платёж зачтён. NULL — записан, но не зачтён (заблокированный клиент): П5-13.
    processed_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_payments_provider_external_id"),
        CheckConstraint("status IN ('succeeded', 'refunded')", name="status"),
        CheckConstraint("amount >= 0", name="amount"),
        Index("ix_payments_client_received", "client_id", "received_at"),
    )
