"""Какие ноды есть и каким драйвером с ними говорить."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.nodes.driver.base import NodeDriver
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.nodes.models import Node

LOCAL_NODE = "local"

_override: NodeDriver | None = None


async def ensure_local_node(session: AsyncSession, settings: Settings) -> Node:
    """Строка единственной ноды этапа 1. Идемпотентно и безопасно при гонке
    (ON CONFLICT). public_host подтягивается из Settings. Коммит — у вызывающего."""
    await session.execute(
        insert(Node)
        .values(
            name=LOCAL_NODE,
            driver="local_docker",
            public_host=settings.vpn_host,
            config={"container": settings.ocserv_container},
        )
        .on_conflict_do_nothing(index_elements=[Node.name])
    )
    node = await session.scalar(select(Node).where(Node.name == LOCAL_NODE))
    assert node is not None
    node.public_host = settings.vpn_host
    return node


async def get_active_nodes(session: AsyncSession) -> list[Node]:
    return list(await session.scalars(select(Node).where(Node.is_active).order_by(Node.id)))


def local_driver(settings: Settings) -> NodeDriver:
    """Драйвер единственной ноды без похода в БД (CLI sessions/allow)."""
    return _override if _override is not None else LocalDockerDriver.from_settings(settings)


def driver_for(node: Node, settings: Settings) -> NodeDriver:
    if node.driver == "local_docker":
        return local_driver(settings)
    raise ValueError(f"unknown node driver {node.driver!r}")


@contextmanager
def override_driver(driver: NodeDriver) -> Iterator[None]:
    """Только для тестов: driver_for возвращает переданный драйвер."""
    global _override
    previous, _override = _override, driver
    try:
        yield
    finally:
        _override = previous
