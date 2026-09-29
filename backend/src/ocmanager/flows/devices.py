"""Склейка provisioning + audit: выпуск и отзыв устройств."""

from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core.errors import SubscriptionInactive
from ocmanager.provisioning import delivery, service
from ocmanager.provisioning.delivery import DeliveryTicket
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.service import IssueResult
from ocmanager.subscriptions import service as subscriptions


async def issue_device(
    session: AsyncSession,
    *,
    client_id: int,
    name: str,
    platform: str,
    device_limit: int,
    ca: CertificateAuthority,
    actor: Actor,
    now: datetime,
) -> IssueResult:
    result = await service.issue_device(
        session,
        client_id=client_id,
        name=name,
        platform=platform,
        device_limit=device_limit,
        ca=ca,
        now=now,
    )
    d = result.device
    # В аудит — только описание устройства. Пароль и .p12 туда не попадают никогда.
    await audit.record(
        session,
        actor,
        "device.issue",
        target_type="device",
        target_id=str(d.id),
        details={
            "client_id": client_id,
            "name": d.name,
            "platform": d.platform,
            "username": d.ocserv_username,
        },
    )
    return result


async def revoke_device(
    session: AsyncSession,
    device_id: int,
    *,
    owner_client_id: int | None,
    reason: str,
    actor: Actor,
    now: datetime,
) -> Device:
    result = await service.revoke_device(
        session, device_id, owner_client_id=owner_client_id, reason=reason, now=now
    )
    if result.changed:
        d = result.device
        await audit.record(
            session,
            actor,
            "device.revoke",
            target_type="device",
            target_id=str(d.id),
            details={
                "client_id": d.client_id,
                "username": d.ocserv_username,
                "reason": d.revocation_reason,
            },
        )
    return result.device


async def device_limit_for(session: AsyncSession, client_id: int, now: datetime) -> int:
    """Сколько устройств можно держать сейчас. Заблокирован — 403, доступа нет — 409:
    ровно то, что TMA показывает как «подписка неактивна»."""
    client = await subscriptions.get_client(session, client_id)
    if client.is_blocked:
        raise SubscriptionInactive("client is blocked", blocked=True)
    sub = await subscriptions.get_subscription(session, client_id)
    if sub is None or not await subscriptions.client_has_access(session, client_id, now):
        raise SubscriptionInactive("no active subscription")
    return sub.device_limit


@dataclass(frozen=True)
class IssuedDeviceBundle:
    device: Device
    password: str
    ticket: DeliveryTicket


async def issue_for_client(
    session: AsyncSession,
    redis: Redis,
    *,
    client_id: int,
    name: str,
    platform: str,
    ca: CertificateAuthority,
    fernet: Fernet,
    actor: Actor,
    now: datetime,
) -> IssuedDeviceBundle:
    """Выпуск устройства клиенту с выдачей .p12 по одноразовой ссылке.

    Не зависит от доступности ноды (спека §12): сертификат живёт в БД, а allowlist
    догонит событие DeviceIssued или reconcile."""
    limit = await device_limit_for(session, client_id, now)
    result = await issue_device(
        session,
        client_id=client_id,
        name=name,
        platform=platform,
        device_limit=limit,
        ca=ca,
        actor=actor,
        now=now,
    )
    ticket = await delivery.put_p12(
        redis, fernet, result.p12, filename=f"{result.device.ocserv_username}.p12", now=now
    )
    return IssuedDeviceBundle(device=result.device, password=result.password, ticket=ticket)


async def revoke_for_client(
    session: AsyncSession, *, client_id: int, device_id: int, actor: Actor, now: datetime
) -> None:
    await revoke_device(
        session,
        device_id,
        owner_client_id=client_id,
        reason="revoked by client",
        actor=actor,
        now=now,
    )
