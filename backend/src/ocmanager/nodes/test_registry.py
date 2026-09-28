from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.nodes.models import Node


async def test_ensure_local_node_is_idempotent(session: AsyncSession, settings: Settings) -> None:
    first = await registry.ensure_local_node(session, settings)
    second = await registry.ensure_local_node(session, settings)
    assert first.id == second.id
    assert await session.scalar(select(func.count()).select_from(Node)) == 1
    assert (first.name, first.driver, first.status) == (
        "local",
        "local_docker",
        "unknown",
    )


async def test_ensure_local_node_follows_vpn_host(
    session: AsyncSession, settings: Settings
) -> None:
    await registry.ensure_local_node(session, settings)
    node = await registry.ensure_local_node(
        session, settings.model_copy(update={"vpn_host": "vpn.example.com"})
    )
    assert node.public_host == "vpn.example.com"


async def test_get_active_nodes_skips_inactive(session: AsyncSession, settings: Settings) -> None:
    node = await registry.ensure_local_node(session, settings)
    assert [n.id for n in await registry.get_active_nodes(session)] == [node.id]
    node.is_active = False
    assert await registry.get_active_nodes(session) == []


async def test_driver_for_and_override(session: AsyncSession, settings: Settings) -> None:
    node = await registry.ensure_local_node(session, settings)
    driver = registry.driver_for(node, settings)
    assert isinstance(driver, LocalDockerDriver)
    assert driver.container == settings.ocserv_container
    fake = FakeNodeDriver()
    with registry.override_driver(fake):
        assert registry.driver_for(node, settings) is fake
    assert registry.driver_for(node, settings) is not fake
