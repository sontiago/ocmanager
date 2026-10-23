from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base, TimestampMixin
from ocmanager.subscriptions.referral import new_referral_code


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
    # Реферальная программа: свой код, кто пригласил, постоянные бонусы уровней (spec 2026-10-23).
    referral_code: Mapped[str] = mapped_column(unique=True, default=new_referral_code)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    bonus_devices: Mapped[int] = mapped_column(server_default=text("0"))
    bonus_traffic_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("lang IN ('ru', 'en')", name="lang"),
        CheckConstraint("bonus_devices >= 0 AND bonus_traffic_bytes >= 0", name="bonuses"),
        Index("ix_clients_referred_by", "referred_by"),
    )


class ReferralReward(Base):
    """Журнал наград. Базовая награда — одна на платёж приглашённого, уровень — один на
    пригласившего; уникальность обеспечивают частичные индексы, а не код."""

    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    invitee_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    kind: Mapped[str]  # base | tier
    tier: Mapped[int | None]  # для tier: порог числа друзей (3, 5, 10)
    days: Mapped[int] = mapped_column(server_default=text("0"))  # пригласившему
    invitee_days: Mapped[int] = mapped_column(server_default=text("0"))  # приглашённому (base)
    devices: Mapped[int] = mapped_column(server_default=text("0"))
    traffic_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    status: Mapped[str]  # applied | pending | capped
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    applied_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("kind IN ('base', 'tier')", name="kind"),
        CheckConstraint("status IN ('applied', 'pending', 'capped')", name="status"),
        Index(
            "ux_referral_base_payment",
            "payment_id",
            unique=True,
            postgresql_where=text("kind = 'base'"),
        ),
        Index(
            "ux_referral_tier",
            "inviter_id",
            "tier",
            unique=True,
            postgresql_where=text("kind = 'tier'"),
        ),
        Index("ix_referral_rewards_inviter", "inviter_id", "created_at"),
    )


class Subscription(Base, TimestampMixin):
    """Подписка клиента. Одна строка на клиента (решение №1): покупка, продление
    и trial→active меняют её, а история денег живёт в payments."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), unique=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str]
    # Снимок тарифа на момент покупки: правка тарифа не меняет купленное.
    plan_is_trial: Mapped[bool] = mapped_column(server_default=false())
    started_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    auto_renew: Mapped[bool] = mapped_column(server_default=false())
    device_limit: Mapped[int]
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    traffic_period_start: Mapped[datetime]
    provider: Mapped[str | None]
    external_subscription_id: Mapped[str | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment', 'trial', 'active', 'expired', 'exhausted',"
            " 'cancelled', 'blocked')",
            name="status",
        ),
        CheckConstraint("device_limit > 0", name="device_limit"),
        CheckConstraint("traffic_used_bytes >= 0", name="traffic_used"),
        # Cron истечения ищет только живые подписки — индекс маленький.
        Index(
            "ix_subscriptions_live_expiry",
            "expires_at",
            postgresql_where=text("status IN ('trial', 'active', 'cancelled')"),
        ),
    )
