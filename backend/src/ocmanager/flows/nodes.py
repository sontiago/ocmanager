"""Склейка nodes + audit: проверка здоровья и действия над нодой с аудитом."""

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.base import NodeDriver
from ocmanager.nodes.models import Node


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
