import pytest
from arq import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.core.errors import InvalidInput, NodeUnavailable
from ocmanager.events.models import EventOutbox
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node


@pytest.fixture
async def node(session: AsyncSession, settings: Settings) -> Node:
    return await registry.ensure_local_node(session, settings)


async def events(session: AsyncSession) -> list[tuple[str, dict[str, object]]]:
    rows = await session.scalars(select(EventOutbox).order_by(EventOutbox.id))
    return [(r.name, r.payload) for r in rows]


async def test_online(session: AsyncSession, node: Node, redis: ArqRedis) -> None:
    fake = FakeNodeDriver()
    fake.add_session("c1-d1")
    result = await service.check_health(session, node, fake, redis)
    assert result.health.state == "online"
    assert result.health.active_sessions == 1
    assert result.changed
    assert node.status == "online"
    assert node.last_seen_at is not None


async def test_offline_when_container_not_running(
    session: AsyncSession, node: Node, redis: ArqRedis
) -> None:
    result = await service.check_health(
        session, node, FakeNodeDriver(container_state="exited"), redis
    )
    assert result.health.state == "offline"
    assert result.health.error == "container exited"
    assert node.last_seen_at is None


async def test_degraded_when_occtl_silent(
    session: AsyncSession, node: Node, redis: ArqRedis
) -> None:
    result = await service.check_health(session, node, FakeNodeDriver(occtl_ok=False), redis)
    assert result.health.state == "degraded"
    assert result.health.container_state == "running"


async def test_event_only_on_change(session: AsyncSession, node: Node, redis: ArqRedis) -> None:
    fake = FakeNodeDriver()
    await service.check_health(session, node, fake, redis)
    second = await service.check_health(session, node, fake, redis)
    assert not second.changed
    fake.container_state = "exited"
    await service.check_health(session, node, fake, redis)
    assert await events(session) == [
        (
            "node.status_changed",
            {"node_id": node.id, "old": "unknown", "new": "online"},
        ),
        (
            "node.status_changed",
            {"node_id": node.id, "old": "online", "new": "offline"},
        ),
    ]


async def test_cache_roundtrip(session: AsyncSession, node: Node, redis: ArqRedis) -> None:
    assert await service.cached_health(redis, node.id) is None
    assert await service.cached_online_usernames(redis, node.id) is None
    fake = FakeNodeDriver()
    fake.add_session("c2-d1")
    fake.add_session("c1-d1")
    result = await service.check_health(session, node, fake, redis)
    assert await service.cached_health(redis, node.id) == result.health
    assert await service.cached_online_usernames(redis, node.id) == {"c1-d1", "c2-d1"}
    assert 0 < await redis.ttl(service.health_key(node.id)) <= service.CACHE_TTL_S


async def test_run_action_restart() -> None:
    fake = FakeNodeDriver()
    await service.run_action(fake, "restart")
    assert ("container_action", ("restart",)) in fake.calls


async def test_run_action_disconnect_user() -> None:
    fake = FakeNodeDriver()
    fake.add_session("c1-d1")
    await service.run_action(fake, "disconnect_user", username="c1-d1")
    assert fake.sessions == []


@pytest.mark.parametrize(
    ("action", "username"),
    [
        ("disconnect_user", None),
        ("disconnect_user", "-rf"),
        ("rm -rf /", None),
        ("exec", None),
    ],
)
async def test_run_action_invalid_input(action: str, username: str | None) -> None:
    fake = FakeNodeDriver()
    with pytest.raises(InvalidInput):
        await service.run_action(fake, action, username=username)
    assert [c for c in fake.calls if c[0] != "probe"] == []


async def test_run_action_unreachable_becomes_node_unavailable() -> None:
    with pytest.raises(NodeUnavailable):
        await service.run_action(FakeNodeDriver(container_state="missing"), "reload")


def test_every_action_is_registered() -> None:
    assert set(service.ACTIONS) == {
        "reload",
        "start",
        "stop",
        "restart",
        "disconnect_user",
    }
