"""Reconcile — самовосстановление ноды (дизайн §4.3).

Источник истины — Postgres. Раз в 5 минут состояние ноды сверяется с ним:
allowed.list, чужие сессии, CRL. Всё найденное чинится и записывается в аудит
как дрейф — расхождение означает, что событие потерялось или кто-то правил ноду руками.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog
from cryptography import x509
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.flows import access
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.models import Node
from ocmanager.nodes.occtl.parser import OcctlParseError
from ocmanager.provisioning import revocations
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.crl import build_crl

log = structlog.get_logger(__name__)

DriftKind = Literal[
    "allowlist_missing",
    "allowlist_diff",
    "rogue_session",
    "crl_missing",
    "crl_diff",
    "crl_expiring",
]

# CRL, до конца которого меньше этого срока, перевыпускается заранее: просроченный CRL
# заставил бы ocserv отвергнуть все сертификаты (решение №10). Ежедневный cron
# refresh_crl держит запас 6+ дней, так что срабатывание здесь — признак сбоя cron.
CRL_MIN_REMAINING = timedelta(days=3)


@dataclass(frozen=True)
class Drift:
    kind: DriftKind
    details: dict[str, Any]


@dataclass(frozen=True)
class ReconcileReport:
    node_id: int
    started_at: datetime
    finished_at: datetime
    drifts: tuple[Drift, ...]
    error: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "drifts": [{"kind": d.kind, "details": d.details} for d in self.drifts],
            "error": self.error,
        }


async def _check_crl(
    session: AsyncSession, driver: NodeDriver, ca: CertificateAuthority, now: datetime
) -> tuple[list[Drift], bool]:
    """Сравнение по содержимому, а не по байтам: подпись и last_update меняются при каждой
    сборке. Возвращает найденные дрейфы и признак «CRL опубликован заново» (нужен reload).

    «Ожидаемый» набор — только уже применённые отзывы: новые ещё ждут cron apply_revocations,
    и это не дрейф. Но публикуется всегда полный набор, чтобы отозванное не потерялось."""
    published = await driver.read_crl()
    expected = await revocations.applied_serials(session)
    drifts: list[Drift] = []
    if published is None:
        drifts.append(Drift("crl_missing", {"reason": "absent"}))
    else:
        try:
            crl = x509.load_pem_x509_crl(published)
        except ValueError:
            drifts.append(Drift("crl_missing", {"reason": "unreadable"}))
        else:
            actual = {r.serial_number for r in crl}
            everything = {serial for serial, _ in await revocations.all_revoked_serials(session)}
            missing, extra = expected - actual, actual - everything
            if missing or extra:
                drifts.append(
                    Drift(
                        "crl_diff",
                        {
                            "missing": sorted(format(s, "x") for s in missing),
                            "unknown": sorted(format(s, "x") for s in extra),
                        },
                    )
                )
            next_update = crl.next_update_utc
            if next_update is None or next_update < now + CRL_MIN_REMAINING:
                drifts.append(
                    Drift(
                        "crl_expiring",
                        {"next_update": None if next_update is None else next_update.isoformat()},
                    )
                )
    if not drifts:
        return [], False
    fresh = build_crl(ca, await revocations.all_revoked_serials(session), now)
    await driver.publish_crl(fresh)
    return drifts, True


async def reconcile_node(
    session: AsyncSession,
    node: Node,
    driver: NodeDriver,
    ca: CertificateAuthority,
    now: datetime,
) -> ReconcileReport:
    """Сверяет и чинит одну ноду. Сбои ноды не бросаются, а попадают в отчёт (`error`):
    сверка — фоновая задача, у неё нет вызывающего, которому можно вернуть ошибку."""
    drifts: list[Drift] = []
    error: str | None = None
    probe = await driver.probe()
    if probe.container_state != "running":
        # На лежащей ноде нечего чинить; тревогу уже поднял check_nodes.
        error = f"container {probe.container_state}"
    else:
        try:
            desired = await access.desired_usernames(session, now)
            change = await access.publish_if_changed(driver, desired)
            if change is not None and change.was_missing:
                drifts.append(Drift("allowlist_missing", {"added": sorted(change.added)}))
            elif change is not None:
                drifts.append(
                    Drift(
                        "allowlist_diff",
                        {"added": sorted(change.added), "removed": sorted(change.removed)},
                    )
                )
            crl_drifts, republished = await _check_crl(session, driver, ca, now)
            drifts += crl_drifts
            if republished:
                await driver.reload()
            rogue = await access.kick_rogue_sessions(driver, desired)
            if rogue:
                drifts.append(Drift("rogue_session", {"usernames": sorted(rogue)}))
        except (NodeUnreachable, OcctlParseError) as exc:
            error = str(exc)[:300]  # файлы могли быть исправлены до сбоя — дрейфы уже в списке

    report = ReconcileReport(
        node_id=node.id,
        started_at=now,
        finished_at=utcnow(),
        drifts=tuple(drifts),
        error=error,
    )
    node.last_reconcile_at = report.finished_at
    node.last_reconcile_report = report.to_json()
    for drift in drifts:
        await audit.record(
            session,
            Actor.system(),
            f"reconcile.{drift.kind}",
            target_type="node",
            target_id=str(node.id),
            details=drift.details,
        )
    if drifts or error:
        log.warning(
            "reconcile_found_drift",
            node_id=node.id,
            drifts=[d.kind for d in drifts],
            error=error,
        )
    return report


async def reconcile_all(
    session: AsyncSession, settings: Settings, ca: CertificateAuthority, now: datetime
) -> list[ReconcileReport]:
    await registry.ensure_local_node(session, settings)
    return [
        await reconcile_node(session, node, registry.driver_for(node, settings), ca, now)
        for node in await registry.get_active_nodes(session)
    ]
