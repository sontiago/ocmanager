"""Отзыв сертификатов на ноде: CRL перестраивается пачкой, а не на каждый отзыв."""

from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core.config import Settings
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.provisioning import revocations
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.crl import build_crl

log = structlog.get_logger(__name__)


async def apply_revocations(
    session: AsyncSession, settings: Settings, ca: CertificateAuthority, now: datetime
) -> int:
    """Возвращает число применённых отзывов. Нет ожидающих — ничего не делает.

    Отметка applied_at ставится только если все ноды приняли новый CRL; иначе
    NodeUnreachable поднимается после обхода всех нод, а следующий запуск повторит."""
    pending = await revocations.pending_revocations(session)
    if not pending:
        return 0
    await registry.ensure_local_node(session, settings)  # без нод отзыв «применился» бы вхолостую
    crl = build_crl(ca, await revocations.all_revoked_serials(session), now)
    first_error: NodeUnreachable | None = None
    for node in await registry.get_active_nodes(session):
        driver = registry.driver_for(node, settings)
        try:
            await driver.publish_crl(crl)
            await driver.reload()
            for item in pending:
                await driver.disconnect_user(item.username)
        except NodeUnreachable as exc:
            log.warning("revocation_node_unreachable", node_id=node.id, error=str(exc))
            first_error = first_error or exc
    if first_error is not None:
        raise first_error
    await revocations.mark_applied(session, [p.id for p in pending], now)
    await audit.record(
        session,
        Actor.system(),
        "revocation.apply",
        details={"count": len(pending), "usernames": sorted(p.username for p in pending)},
    )
    return len(pending)


async def refresh_crl(
    session: AsyncSession, settings: Settings, ca: CertificateAuthority, now: datetime
) -> None:
    """Раз в сутки публикует свежий CRL с новым next_update даже без новых отзывов:
    просроченный CRL заставил бы ocserv отвергнуть все сертификаты (решение №10)."""
    await registry.ensure_local_node(session, settings)
    crl = build_crl(ca, await revocations.all_revoked_serials(session), now)
    for node in await registry.get_active_nodes(session):
        await registry.driver_for(node, settings).publish_crl(crl)
