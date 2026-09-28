"""Здоровье ноды и действия над ней.

Аудит здесь не пишется: nodes не импортирует домен audit (граница модулей).
Его пишет flows/nodes.py по результату этих функций.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal, get_args

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.core.errors import InvalidInput, NodeUnavailable
from ocmanager.events import bus
from ocmanager.events.types import NodeStatusChanged
from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.models import Node
from ocmanager.nodes.occtl.parser import OcctlParseError

NodeState = Literal["online", "degraded", "offline"]
NodeAction = Literal["reload", "start", "stop", "restart", "disconnect_user"]

# Кэш для api-public, у которого нет доступа к Docker. Cron обновляет его
# раз в минуту; TTL с запасом на два пропуска.
CACHE_TTL_S = 180


def health_key(node_id: int) -> str:
    return f"node:{node_id}:health"


def online_key(node_id: int) -> str:
    return f"node:{node_id}:online"


@dataclass(frozen=True)
class NodeHealth:
    node_id: int
    state: NodeState
    container_state: str
    active_sessions: int
    checked_at: datetime
    error: str | None

    def to_json(self) -> str:
        return json.dumps({**asdict(self), "checked_at": self.checked_at.isoformat()})

    @classmethod
    def from_json(cls, raw: str | bytes) -> "NodeHealth":
        data: dict[str, Any] = json.loads(raw)
        data["checked_at"] = datetime.fromisoformat(data["checked_at"])
        return cls(**data)


@dataclass(frozen=True)
class HealthCheck:
    health: NodeHealth
    previous: str  # статус ноды до проверки

    @property
    def changed(self) -> bool:
        return self.previous != self.health.state


async def check_health(
    session: AsyncSession, node: Node, driver: NodeDriver, redis: Redis
) -> HealthCheck:
    """Контейнер не running → offline; running, но occtl молчит → degraded;
    иначе online. Смена статуса — событие NodeStatusChanged. Коммит — у вызывающего."""
    now = utcnow()
    probe = await driver.probe()
    online: list[str] = []
    error: str | None = None
    if probe.container_state != "running":
        state: NodeState = "offline"
        error = f"container {probe.container_state}"
    elif probe.ocserv is None:
        state = "degraded"
        error = "occtl not responding"
    else:
        try:
            online = sorted({s.username for s in await driver.list_sessions()})
            state = "online"
        except (NodeUnreachable, OcctlParseError) as exc:
            state, error = "degraded", str(exc)[:300]

    health = NodeHealth(node.id, state, probe.container_state, len(online), now, error)
    await redis.set(health_key(node.id), health.to_json(), ex=CACHE_TTL_S)
    await redis.set(online_key(node.id), json.dumps(online), ex=CACHE_TTL_S)

    previous = node.status
    if state != "offline":
        node.last_seen_at = now
    if previous != state:
        node.status = state
        await bus.record(session, NodeStatusChanged(node_id=node.id, old=previous, new=state))
    return HealthCheck(health, previous)


async def cached_health(redis: Redis, node_id: int) -> NodeHealth | None:
    raw = await redis.get(health_key(node_id))
    return None if raw is None else NodeHealth.from_json(raw)


async def cached_online_usernames(redis: Redis, node_id: int) -> set[str] | None:
    raw = await redis.get(online_key(node_id))
    return None if raw is None else set(json.loads(raw))


async def _disconnect(driver: NodeDriver, username: str | None) -> None:
    if not username:
        raise InvalidInput("disconnect_user requires username")
    try:
        await driver.disconnect_user(username)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from None


# Реестр действий: произвольная команда на ноде невозможна по построению.
ACTIONS: dict[str, Callable[[NodeDriver, str | None], Awaitable[None]]] = {
    "reload": lambda d, _: d.reload(),
    "start": lambda d, _: d.container_action("start"),
    "stop": lambda d, _: d.container_action("stop"),
    "restart": lambda d, _: d.container_action("restart"),
    "disconnect_user": _disconnect,
}
assert set(ACTIONS) == set(get_args(NodeAction))


async def run_action(driver: NodeDriver, action: str, *, username: str | None = None) -> None:
    """action — строка, потому что приходит из админки мимо типов."""
    handler = ACTIONS.get(action)
    if handler is None:
        raise InvalidInput(f"unknown node action {action!r}")
    try:
        await handler(driver, username)
    except NodeUnreachable as exc:
        raise NodeUnavailable(str(exc)) from exc
