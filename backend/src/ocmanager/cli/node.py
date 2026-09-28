import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.service import Actor
from ocmanager.cli._common import fail, refuse_in_production, settings
from ocmanager.core.config import Settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.errors import DomainError
from ocmanager.core.redis import create_redis
from ocmanager.flows.nodes import check_node_health, run_node_action
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.models import Node

app = typer.Typer(no_args_is_help=True)

CLI_ACTOR = Actor(type="admin", id="cli")


@dataclass
class NodeContext:
    settings: Settings
    session: AsyncSession
    node: Node
    driver: NodeDriver


@asynccontextmanager
async def node_context() -> AsyncIterator[NodeContext]:
    """Сессия БД и строка ноды. Коммит — в команде."""
    s = settings()
    engine = make_engine(s.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            node = await registry.ensure_local_node(session, s)
            yield NodeContext(s, session, node, registry.driver_for(node, s))
    finally:
        await engine.dispose()


def run(coro: Callable[[], Coroutine[Any, Any, None]]) -> None:
    try:
        asyncio.run(coro())
    except DomainError as exc:
        raise fail(f"{exc.code}: {exc.message}") from None
    except NodeUnreachable as exc:
        raise fail(f"нода недоступна: {exc}") from None


@app.command()
def status() -> None:
    """Проверяет ноду, как cron воркера: статус в БД и кэш в Redis."""

    async def go() -> None:
        async with node_context() as ctx:
            redis = await create_redis(ctx.settings.redis_url)
            try:
                health = await check_node_health(ctx.session, ctx.node, ctx.driver, redis)
                await ctx.session.commit()
            finally:
                await redis.aclose()
        typer.echo(
            f"{health.state}  container={health.container_state}  "
            f"sessions={health.active_sessions}"
            + (f"  error={health.error}" if health.error else "")
        )

    run(go)


@app.command()
def sessions() -> None:
    """Активные сессии (occtl show users)."""

    async def go() -> None:
        driver = registry.local_driver(settings())
        for x in await driver.list_sessions():
            typer.echo(
                f"{x.session_id:>6}  {x.username:<16} {x.vpn_ip or '-':<15} "
                f"in={x.bytes_in} out={x.bytes_out} since={x.connected_at:%Y-%m-%d %H:%M}Z"
            )

    run(go)


def _action(name: str, username: str | None = None) -> None:
    async def go() -> None:
        async with node_context() as ctx:
            await run_node_action(
                ctx.session, ctx.node, ctx.driver, name, CLI_ACTOR, username=username
            )
            await ctx.session.commit()
        typer.echo(f"{name}: ok")

    run(go)


@app.command()
def reload() -> None:
    """occtl reload."""
    _action("reload")


@app.command()
def restart() -> None:
    """docker restart контейнера ноды."""
    _action("restart")


@app.command()
def start() -> None:
    """docker start контейнера ноды."""
    _action("start")


@app.command()
def stop() -> None:
    """docker stop контейнера ноды."""
    _action("stop")


@app.command()
def disconnect(
    username: Annotated[str, typer.Argument(help="например c9001-d1")],
) -> None:
    """Разорвать сессии пользователя (occtl disconnect user)."""
    _action("disconnect_user", username)


@app.command()
def allow(
    usernames: Annotated[list[str], typer.Argument(help="полный новый список")],
) -> None:
    """Только dev: записать allowed.list руками. В проде его пишет только flows.access."""
    s = settings()
    refuse_in_production(s)

    async def go() -> None:
        driver = registry.local_driver(s)
        try:
            await driver.publish_allowlist(usernames)
        except ValueError as exc:
            raise fail(str(exc)) from None
        typer.echo(f"allowed.list: {', '.join(sorted(set(usernames)))}")

    run(go)
