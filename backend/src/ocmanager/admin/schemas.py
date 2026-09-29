"""Формы ответов админ-API, общие для нескольких разделов."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from ocmanager.nodes.models import SessionLog
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Client, Subscription


class ActionOut(BaseModel):
    changed: bool  # False — команда ничего не изменила (уже было так)


class ClientOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str
    lang: str
    is_blocked: bool
    trial_used_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, c: Client) -> "ClientOut":
        return cls(
            id=c.id,
            telegram_id=c.telegram_id,
            username=c.username,
            first_name=c.first_name,
            lang=c.lang,
            is_blocked=c.is_blocked,
            trial_used_at=c.trial_used_at,
            created_at=c.created_at,
        )


class SubscriptionOut(BaseModel):
    status: str
    plan_code: str
    plan_name_i18n: dict[str, str]
    plan_is_trial: bool
    started_at: datetime
    expires_at: datetime
    auto_renew: bool
    device_limit: int
    devices_active: int
    # Тариф с меньшим лимитом устройств не отзывает лишние (решение №19): админ видит превышение.
    over_device_limit: bool
    traffic_limit_bytes: int | None
    traffic_used_bytes: int
    traffic_period_start: datetime
    provider: str | None

    @classmethod
    def of(
        cls, sub: Subscription, *, plan_code: str, plan_name: dict[str, str], devices_active: int
    ) -> "SubscriptionOut":
        return cls(
            status=sub.status,
            plan_code=plan_code,
            plan_name_i18n=plan_name,
            plan_is_trial=sub.plan_is_trial,
            started_at=sub.started_at,
            expires_at=sub.expires_at,
            auto_renew=sub.auto_renew,
            device_limit=sub.device_limit,
            devices_active=devices_active,
            over_device_limit=devices_active > sub.device_limit,
            traffic_limit_bytes=sub.traffic_limit_bytes,
            traffic_used_bytes=sub.traffic_used_bytes,
            traffic_period_start=sub.traffic_period_start,
            provider=sub.provider,
        )


class DeviceOut(BaseModel):
    id: int
    client_id: int
    seq: int
    name: str
    platform: str
    username: str  # ocserv-username: c{client}-d{seq}
    issued_at: datetime
    cert_expires_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    last_seen_at: datetime | None
    is_online: bool | None  # None — кэш состояния ноды пуст, сказать нельзя
    traffic_bytes: int  # за расчётный период подписки

    @classmethod
    def of(cls, d: Device, *, is_online: bool | None, traffic_bytes: int) -> "DeviceOut":
        return cls(
            id=d.id,
            client_id=d.client_id,
            seq=d.seq,
            name=d.name,
            platform=d.platform,
            username=d.ocserv_username,
            issued_at=d.issued_at,
            cert_expires_at=d.cert_expires_at,
            revoked_at=d.revoked_at,
            revocation_reason=d.revocation_reason,
            last_seen_at=d.last_seen_at,
            is_online=is_online,
            traffic_bytes=traffic_bytes,
        )


class SessionRowOut(BaseModel):
    id: int
    username: str
    started_at: datetime
    ended_at: datetime | None  # None — сессия открыта или оборвалась без отчёта
    duration_sec: int
    client_ip: str | None
    vpn_ip: str | None
    bytes_in: int  # RX сервера = upload клиента
    bytes_out: int

    @classmethod
    def of(cls, s: SessionLog) -> "SessionRowOut":
        end = s.ended_at or s.last_polled_at
        return cls(
            id=s.id,
            username=s.username,
            started_at=s.started_at,
            ended_at=s.ended_at,
            # Часы ноды могут опережать наши: отрицательной длительности не бывает.
            duration_sec=max(0, int((end - s.started_at).total_seconds())),
            client_ip=s.client_ip,
            vpn_ip=s.vpn_ip,
            bytes_in=s.bytes_in,
            bytes_out=s.bytes_out,
        )


class DailyTrafficOut(BaseModel):
    day: date
    bytes_in: int
    bytes_out: int


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name_i18n: dict[str, str]
    description_i18n: dict[str, str] | None
    duration_days: int
    device_limit: int
    traffic_limit_bytes: int | None
    speed_limit_kbps: int | None
    price_amount: int
    currency: str
    provider_product_ids: dict[str, Any]
    is_active: bool
    is_trial: bool
    sort_order: int
