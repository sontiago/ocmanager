"""Доступ на ноде выводится из БД: allowed.list = устройства клиентов с живой
подпиской (дизайн §4.2). Функции идемпотентны — они пересчитывают список
целиком, поэтому at-least-once доставка событий безопасна."""

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.models import Node
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.state import LIVE

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AccessSync:
    added: frozenset[str]
    removed: frozenset[str]
    disconnected: frozenset[str]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.disconnected)


async def desired_usernames(session: AsyncSession, now: datetime) -> set[str]:
    """Кому сейчас можно подключаться. Условия те же, что в state.has_access:
    неотозванное устройство, клиент не заблокирован, подписка живая и не истекла
    (последнее — страховка на случай, если cron истечения отстал)."""
    rows = await session.scalars(
        select(Device.ocserv_username)
        .join(Client, Client.id == Device.client_id)
        .join(Subscription, Subscription.client_id == Device.client_id)
        .where(
            Device.revoked_at.is_(None),
            Client.is_blocked.is_(False),
            Subscription.status.in_([s.value for s in LIVE]),
            Subscription.expires_at > now,
        )
    )
    return set(rows)


@dataclass(frozen=True)
class AllowlistChange:
    added: frozenset[str]
    removed: frozenset[str]
    was_missing: bool  # файла на ноде не было


async def publish_if_changed(driver: NodeDriver, desired: set[str]) -> AllowlistChange | None:
    """Пишет allowed.list только при расхождении. None — файл уже верный."""
    current = await driver.read_allowlist()
    if current == desired:
        return None
    await driver.publish_allowlist(desired)
    return AllowlistChange(
        added=frozenset(desired - (current or set())),
        removed=frozenset((current or set()) - desired),
        was_missing=current is None,
    )


async def kick_rogue_sessions(driver: NodeDriver, desired: set[str]) -> frozenset[str]:
    """Разрывает сессии тех, кого нет в desired: только что лишённых доступа и «чужих»."""
    rogue = {s.username for s in await driver.list_sessions()} - desired
    for username in sorted(rogue):
        await driver.disconnect_user(username)
    return frozenset(rogue)


async def sync_access(
    session: AsyncSession, node: Node, driver: NodeDriver, now: datetime
) -> AccessSync:
    """Приводит allowed.list и онлайн-сессии ноды к БД. Пустая разница — ни одной записи.

    NodeUnreachable не глотается: событие вернётся в outbox и повторится, а если и это
    не поможет — сверит reconcile (Задача 2.8)."""
    desired = await desired_usernames(session, now)
    change = await publish_if_changed(driver, desired)  # None (файла нет) — тоже расхождение
    disconnected = await kick_rogue_sessions(driver, desired)
    result = AccessSync(
        added=change.added if change else frozenset(),
        removed=change.removed if change else frozenset(),
        disconnected=disconnected,
    )
    if result.changed:
        log.info(
            "access_synced",
            node_id=node.id,
            added=sorted(result.added),
            removed=sorted(result.removed),
            disconnected=sorted(result.disconnected),
        )
    return result


async def sync_all_nodes(
    session: AsyncSession, settings: Settings, now: datetime
) -> dict[int, AccessSync]:
    """Одна недоступная нода не мешает остальным; ошибка поднимается после обхода всех."""
    await registry.ensure_local_node(session, settings)
    results: dict[int, AccessSync] = {}
    first_error: NodeUnreachable | None = None
    for node in await registry.get_active_nodes(session):
        try:
            results[node.id] = await sync_access(
                session, node, registry.driver_for(node, settings), now
            )
        except NodeUnreachable as exc:
            log.warning("access_sync_node_unreachable", node_id=node.id, error=str(exc))
            first_error = first_error or exc
    if first_error is not None:
        raise first_error
    return results
