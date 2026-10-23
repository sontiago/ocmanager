from pathlib import Path

import pytest
from arq import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.core.config import Settings
from ocmanager.core.errors import NodeUnavailable
from ocmanager.flows.nodes import check_node_health, run_node_action, sync_server_cert
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node

CERT = Path("/caddy-data/server.crt")


def reloads(driver: FakeNodeDriver) -> int:
    return driver.calls.count(("reload", ()))


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


async def test_the_first_look_at_the_certificate_reloads_once(redis: ArqRedis) -> None:
    driver = FakeNodeDriver(server_cert=b"certificate-1")

    assert await sync_server_cert(redis, 1, CERT, driver) == "reloaded"
    assert driver.calls == [("read_server_cert", (CERT,)), ("reload", ())]


async def test_an_unchanged_certificate_is_left_alone(redis: ArqRedis) -> None:
    driver = FakeNodeDriver(server_cert=b"certificate-1")
    await sync_server_cert(redis, 1, CERT, driver)

    assert await sync_server_cert(redis, 1, CERT, driver) == "unchanged"
    assert reloads(driver) == 1  # второго reload нет


async def test_a_renewed_certificate_reloads_the_node(redis: ArqRedis) -> None:
    driver = FakeNodeDriver(server_cert=b"certificate-1")
    await sync_server_cert(redis, 1, CERT, driver)

    driver.server_cert = b"certificate-2"  # Caddy продлил сертификат

    assert await sync_server_cert(redis, 1, CERT, driver) == "reloaded"
    assert reloads(driver) == 2


async def test_a_failed_reload_is_retried_next_time(redis: ArqRedis) -> None:
    class FlakyDriver(FakeNodeDriver):
        failures = 1

        async def reload(self) -> None:
            if self.failures:
                self.failures -= 1
                raise NodeUnreachable("occtl is down")
            await super().reload()

    driver = FlakyDriver(server_cert=b"certificate-1")

    with pytest.raises(NodeUnreachable):
        await sync_server_cert(redis, 1, CERT, driver)
    # отпечаток не запомнен: следующий запуск повторит reload
    assert await sync_server_cert(redis, 1, CERT, driver) == "reloaded"
    assert reloads(driver) == 1


async def test_a_missing_certificate_file_is_reported_not_raised(redis: ArqRedis) -> None:
    driver = FakeNodeDriver()
    assert await sync_server_cert(redis, 1, CERT, driver) == "missing"
    assert reloads(driver) == 0


async def test_each_node_remembers_its_own_fingerprint(redis: ArqRedis) -> None:
    first, second = FakeNodeDriver(server_cert=b"c"), FakeNodeDriver(server_cert=b"c")

    await sync_server_cert(redis, 1, CERT, first)
    await sync_server_cert(redis, 2, CERT, second)

    assert reloads(first) == reloads(second) == 1
