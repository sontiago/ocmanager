"""Склейка nodes + audit: проверка здоровья и действия над нодой с аудитом."""

import asyncio
import hashlib
from pathlib import Path
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.base import NodeDriver
from ocmanager.nodes.models import Node

SERVER_CERT_FINGERPRINT_KEY = "ocm:server_cert:{node_id}"


async def check_node_health(
    session: AsyncSession, node: Node, driver: NodeDriver, redis: Redis
) -> service.NodeHealth:
    result = await service.check_health(session, node, driver, redis)
    if result.changed:
        await audit.record(
            session,
            Actor.system(),
            "node.status_changed",
            target_type="node",
            target_id=str(node.id),
            details={
                "old": result.previous,
                "new": result.health.state,
                "error": result.health.error,
            },
        )
    return result.health


async def run_node_action(
    session: AsyncSession,
    node: Node,
    driver: NodeDriver,
    action: str,
    actor: Actor,
    *,
    username: str | None = None,
) -> None:
    """Аудит только успешного действия; ошибка уходит вызывающему как DomainError."""
    await service.run_action(driver, action, username=username)
    await audit.record(
        session,
        actor,
        f"node.{action}",
        target_type="node",
        target_id=str(node.id),
        details={"username": username} if username else {},
    )


async def online_usernames(db: AsyncSession, redis: Redis) -> set[str] | None:
    """Кто подключён по кэшу, который раз в минуту обновляет воркер. None — кэша нет ни у
    одной ноды (воркер не работает или нода лежит): «не подключён» и «не знаем» — разные вещи."""
    known: list[set[str]] = []
    for node in await registry.get_active_nodes(db):
        online = await service.cached_online_usernames(redis, node.id)
        if online is not None:
            known.append(online)
    return set().union(*known) if known else None


async def sync_server_cert(
    redis: Redis, node_id: int, path: Path, driver: NodeDriver
) -> Literal["unchanged", "reloaded", "missing"]:
    """Серверный сертификат ocserv выпускает и продлевает Caddy; ocserv держит прочитанный при
    старте. Смена файла без reload тихо ломает подключения через 60–90 дней, поэтому воркер
    сверяет отпечаток с запомненным и при отличии просит ocserv перечитать сертификат.

    Отпечаток запоминается только после успешного reload: сбой повторится при следующем запуске.
    Пустой Redis даёт один лишний reload — он не обрывает сессии и дешевле пропущенного."""
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        return "missing"
    fingerprint = hashlib.sha256(data).hexdigest()
    key = SERVER_CERT_FINGERPRINT_KEY.format(node_id=node_id)
    known = await redis.get(key)
    if isinstance(known, bytes):
        known = known.decode()
    if known == fingerprint:
        return "unchanged"
    await driver.reload()
    await redis.set(key, fingerprint)
    return "reloaded"
