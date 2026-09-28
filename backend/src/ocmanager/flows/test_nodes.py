import pytest
from arq import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.core.config import Settings
from ocmanager.core.errors import NodeUnavailable
from ocmanager.flows.nodes import check_node_health, run_node_action
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node


@pytest.fixture
async def node(session: AsyncSession, settings: Settings) -> Node:
    return await registry.ensure_local_node(session, settings)


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


async def test_status_change_is_audited_once(
    session: AsyncSession, node: Node, redis: ArqRedis
) -> None:
    fake = FakeNodeDriver()
    await check_node_health(session, node, fake, redis)
    await check_node_health(session, node, fake, redis)
    [row] = await audit_rows(session)
    assert (row.actor_type, row.action, row.target_id) == (
        "system",
        "node.status_changed",
        str(node.id),
    )
    assert row.details == {"old": "unknown", "new": "online", "error": None}


async def test_action_is_audited(session: AsyncSession, node: Node) -> None:
    fake = FakeNodeDriver()
    fake.add_session("c1-d1")
    await run_node_action(
        session, node, fake, "disconnect_user", Actor("admin", "cli"), username="c1-d1"
    )
    [row] = await audit_rows(session)
    assert (row.actor_type, row.actor_id, row.action) == (
        "admin",
        "cli",
        "node.disconnect_user",
    )
    assert row.details == {"username": "c1-d1"}


async def test_failed_action_is_not_audited(session: AsyncSession, node: Node) -> None:
    with pytest.raises(NodeUnavailable):
        await run_node_action(
            session,
            node,
            FakeNodeDriver(container_state="exited"),
            "reload",
            Actor.system(),
        )
    assert await audit_rows(session) == []
