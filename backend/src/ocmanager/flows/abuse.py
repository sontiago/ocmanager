"""Подозрение на злоупотребление: алерты админу. Только сигнал в Telegram, доступ не режется —
решает человек. Правила выключаются нулевым порогом в настройках."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.flows.notify import gib, to_admins, who
from ocmanager.nodes.models import SessionLog, TrafficDaily
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions import service as subscriptions

log = structlog.get_logger(__name__)

WINDOW = timedelta(hours=24)
GIB = 1024**3


async def detect(session: AsyncSession, now: datetime) -> int:
    """Проверяет оба правила и ставит алерты в очередь. Возвращает число поставленных сообщений.
    Повторный запуск в тот же день безопасен: на каждого нарушителя ключ дедупликации свой."""
    runtime = await settings_store.load(session)
    if not runtime.admin_chat_ids:
        return 0
    day = now.astimezone(UTC).date()
    queued = 0
    if runtime.abuse_daily_traffic_gb > 0:
        queued += await _heavy_clients(session, day, runtime.abuse_daily_traffic_gb)
    if runtime.abuse_devices_per_ip > 0:
        queued += await _shared_ips(session, now, day, runtime.abuse_devices_per_ip)
    return queued


async def _heavy_clients(session: AsyncSession, day, limit_gb: int) -> int:  # type: ignore[no-untyped-def]
    """Трафик клиента за сегодняшние сутки UTC по всем его устройствам не меньше порога."""
    total = func.sum(TrafficDaily.bytes_in + TrafficDaily.bytes_out)
    rows = await session.execute(
        select(Device.client_id, total)
        .join(Device, Device.ocserv_username == TrafficDaily.username)
        .where(TrafficDaily.day == day)
        .group_by(Device.client_id)
        .having(total >= limit_gb * GIB)
        .order_by(Device.client_id)
    )
    queued = 0
    for client_id, used in rows.all():
        client = await subscriptions.get_client(session, client_id)
        queued += await to_admins(
            session,
            "abuse_traffic",
            {"client": who(client), "traffic": gib(int(used)), "limit": f"{limit_gb} GB"},
            dedupe_key=f"abuse_traffic:client:{client_id}:{day.isoformat()}",
        )
    return queued


async def _shared_ips(session: AsyncSession, now: datetime, day, limit: int) -> int:  # type: ignore[no-untyped-def]
    """С одного адреса за 24 часа выходило не меньше `limit` разных устройств: перепродажа
    доступа или ключ, розданный многим. Семья за одним роутером укладывается в порог."""
    devices = func.count(func.distinct(SessionLog.username))
    rows = await session.execute(
        select(SessionLog.client_ip, devices, func.count(func.distinct(Device.client_id)))
        .join(Device, Device.ocserv_username == SessionLog.username)
        .where(SessionLog.last_polled_at >= now - WINDOW, SessionLog.client_ip.is_not(None))
        .group_by(SessionLog.client_ip)
        .having(devices >= limit)
        .order_by(SessionLog.client_ip)
    )
    queued = 0
    for ip, n_devices, n_clients in rows.all():
        queued += await to_admins(
            session,
            "abuse_shared_ip",
            {"ip": ip, "devices": int(n_devices), "clients": int(n_clients)},
            dedupe_key=f"abuse_shared_ip:{ip}:{day.isoformat()}",
        )
    return queued
