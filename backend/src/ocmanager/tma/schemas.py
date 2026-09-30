"""Формы ответов TMA — поле в поле с frontend/tma/src/api/types.ts.

Имена классов (`MeOut`, `PlanOut`, …) важны: по ним frontend сверяет свои типы со схемой
OpenAPI (Задача 20 плана TMA). Переименование поля ломает `test_schemas.py`, а не клиентов.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from ocmanager.billing.models import Plan
from ocmanager.core.i18n import pick
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.service import MAX_NAME_LEN, Platform
from ocmanager.subscriptions.models import Client, Subscription

Lang = Literal["ru", "en"]
SubscriptionStatus = Literal[
    "pending_payment", "trial", "active", "expired", "exhausted", "cancelled", "blocked"
]


def _iso_z(value: datetime) -> str:
    """ISO 8601 в UTC с `Z` на конце — на границе API время всегда такое (Global Constraints)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(_iso_z, return_type=str, when_used="json")]


class MeOut(BaseModel):
    telegram_id: int
    first_name: str
    username: str | None
    lang: Lang
    is_blocked: bool
    trial_available: bool

    @classmethod
    def of(cls, client: Client, *, lang: Lang, has_subscription: bool) -> "MeOut":
        return cls(
            telegram_id=client.telegram_id,
            first_name=client.first_name,
            username=client.username,
            lang=lang,
            is_blocked=client.is_blocked,
            # Пробный период — один раз и только тому, у кого ещё не было подписки.
            trial_available=(
                client.trial_used_at is None and not has_subscription and not client.is_blocked
            ),
        )


class PlanOut(BaseModel):
    code: str
    name: str
    description: str | None = None
    duration_days: int
    device_limit: int
    traffic_limit_bytes: int | None
    speed_limit_kbps: int | None
    price_amount: int
    currency: str
    is_trial: bool
    sort_order: int

    @classmethod
    def of(cls, plan: Plan, lang: Lang) -> "PlanOut":
        return cls(
            code=plan.code,
            name=pick(plan.name_i18n, lang) or plan.code,
            description=pick(plan.description_i18n, lang),
            duration_days=plan.duration_days,
            device_limit=plan.device_limit,
            traffic_limit_bytes=plan.traffic_limit_bytes,
            speed_limit_kbps=plan.speed_limit_kbps,
            price_amount=plan.price_amount,
            currency=plan.currency,
            is_trial=plan.is_trial,
            sort_order=plan.sort_order,
        )


class SubscriptionOut(BaseModel):
    id: str
    plan: PlanOut
    status: SubscriptionStatus
    started_at: UtcDatetime | None
    expires_at: UtcDatetime | None
    traffic_used_bytes: int
    traffic_limit_bytes: int | None
    traffic_period_start: UtcDatetime | None
    device_limit: int
    devices_used: int
    auto_renew: bool

    @classmethod
    def of(
        cls, sub: Subscription, plan: Plan, *, lang: Lang, devices_used: int
    ) -> "SubscriptionOut":
        return cls(
            id=str(sub.id),
            plan=PlanOut.of(plan, lang),
            status=sub.status,
            started_at=sub.started_at,
            expires_at=sub.expires_at,
            traffic_used_bytes=sub.traffic_used_bytes,
            traffic_limit_bytes=sub.traffic_limit_bytes,
            traffic_period_start=sub.traffic_period_start,
            device_limit=sub.device_limit,
            devices_used=devices_used,
            auto_renew=sub.auto_renew,
        )


class SubscriptionEnvelope(BaseModel):
    """Подписки может не быть: это 200 с `null`, а не 404 (решение №4 плана TMA)."""

    subscription: SubscriptionOut | None


class DeviceOut(BaseModel):
    id: str
    name: str
    platform: Platform
    issued_at: UtcDatetime
    cert_expires_at: UtcDatetime
    last_seen_at: UtcDatetime | None
    is_online: bool
    traffic_used_bytes: int

    @classmethod
    def of(cls, device: Device, *, is_online: bool, traffic_used_bytes: int) -> "DeviceOut":
        return cls(
            id=str(device.id),
            name=device.name,
            platform=device.platform,
            issued_at=device.issued_at,
            cert_expires_at=device.cert_expires_at,
            last_seen_at=device.last_seen_at,
            is_online=is_online,
            traffic_used_bytes=traffic_used_bytes,
        )


class CreateDeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Пробелы по краям срезает provisioning.clean_name, он же проверяет управляющие символы.
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN * 4)
    platform: Platform


class IssuedDeviceOut(BaseModel):
    device: DeviceOut
    p12_password: str
    download_url: str
    download_expires_at: UtcDatetime


class ConnectionOut(BaseModel):
    server_host: str
    gateway_url: str
