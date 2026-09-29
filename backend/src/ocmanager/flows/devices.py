"""Склейка provisioning + audit: выпуск и отзыв устройств."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.provisioning import service
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.service import IssueResult


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
