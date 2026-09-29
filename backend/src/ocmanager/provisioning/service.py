"""Выпуск и отзыв устройств. Аудит здесь не пишется: provisioning не импортирует
домен audit (граница модулей) — его пишет flows/devices.py."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, get_args

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.errors import Conflict, DeviceLimitReached, InvalidInput, NotFound
from ocmanager.events import bus
from ocmanager.events.types import DeviceIssued, DeviceRevoked
from ocmanager.provisioning.models import Device, Revocation
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.certs import issue_client_cert
from ocmanager.provisioning.pki.p12 import generate_password, pack_p12

Platform = Literal["ios", "android", "windows", "macos", "linux"]
PLATFORMS: Final = frozenset(get_args(Platform))

MAX_NAME_LEN = 40
MAX_REASON_LEN = 200
MAX_SEQ = 99_999  # последняя цифра, которую пропускает USERNAME_RE (d[1-9]\d{0,4})


@dataclass(frozen=True)
class IssueResult:
    device: Device
    p12: bytes
    password: str


@dataclass(frozen=True)
class RevokeResult:
    device: Device
    changed: bool  # False — устройство уже было отозвано


def clean_name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= MAX_NAME_LEN:
        raise InvalidInput(f"device name must be 1..{MAX_NAME_LEN} characters")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        raise InvalidInput("device name must not contain control characters")
    return name


async def count_active(session: AsyncSession, client_id: int) -> int:
    n = await session.scalar(
        select(func.count())
        .select_from(Device)
        .where(Device.client_id == client_id, Device.revoked_at.is_(None))
    )
    return int(n or 0)


async def list_devices(
    session: AsyncSession, client_id: int, *, include_revoked: bool = False
) -> list[Device]:
    stmt = select(Device).where(Device.client_id == client_id).order_by(Device.seq)
    if not include_revoked:
        stmt = stmt.where(Device.revoked_at.is_(None))
    return list(await session.scalars(stmt))


async def issue_device(
    session: AsyncSession,
    *,
    client_id: int,
    name: str,
    platform: str,
    device_limit: int,
    ca: CertificateAuthority,
    now: datetime,
) -> IssueResult:
    name = clean_name(name)
    if platform not in PLATFORMS:
        raise InvalidInput(f"unknown platform {platform!r}")
    # Рекомендательная блокировка на клиента: provisioning не знает модель Client,
    # поэтому строку клиента не заблокировать. Держится до конца транзакции.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"provisioning.devices:{client_id}"},
    )
    if await count_active(session, client_id) >= device_limit:
        raise DeviceLimitReached(f"device limit {device_limit} reached")
    last = await session.scalar(select(func.max(Device.seq)).where(Device.client_id == client_id))
    seq = (last or 0) + 1
    if seq > MAX_SEQ:
        raise Conflict("device number space exhausted")

    username = f"c{client_id}-d{seq}"
    issued = issue_client_cert(ca, username, now)
    password = generate_password()
    p12 = pack_p12(issued, ca.cert, password, friendly_name=username)
    device = Device(
        client_id=client_id,
        seq=seq,
        name=name,
        platform=platform,
        ocserv_username=username,
        cert_serial=format(issued.serial, "x"),
        cert_fingerprint=issued.fingerprint_sha256,
        issued_at=now,
        cert_expires_at=issued.not_after,
    )
    session.add(device)
    await session.flush()
    await bus.record(session, DeviceIssued(client_id=client_id, device_id=device.id))
    return IssueResult(device=device, p12=p12, password=password)


async def revoke_device(
    session: AsyncSession,
    device_id: int,
    *,
    owner_client_id: int | None,
    reason: str,
    now: datetime,
) -> RevokeResult:
    """owner_client_id задан (запрос клиента из TMA) — чужое устройство даёт NotFound,
    а не Forbidden: существование чужих устройств не раскрывается."""
    reason = reason.strip()
    if not 1 <= len(reason) <= MAX_REASON_LEN:
        raise InvalidInput(f"reason must be 1..{MAX_REASON_LEN} characters")
    device = await session.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None or (owner_client_id is not None and device.client_id != owner_client_id):
        raise NotFound("device not found")
    if device.revoked_at is not None:
        return RevokeResult(device, changed=False)
    device.revoked_at = now
    device.revocation_reason = reason
    session.add(Revocation(device_id=device.id, cert_serial=device.cert_serial, revoked_at=now))
    await session.flush()
    await bus.record(
        session,
        DeviceRevoked(
            client_id=device.client_id,
            device_id=device.id,
            username=device.ocserv_username,
        ),
    )
    return RevokeResult(device, changed=True)
