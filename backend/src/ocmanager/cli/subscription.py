from datetime import timedelta
from typing import Annotated

import typer

from ocmanager.cli._common import (
    db_sessionmaker,
    fail,
    refuse_in_production,
    run,
    settings,
    sync_now,
)
from ocmanager.cli.client import client_by_telegram_id
from ocmanager.core.clock import utcnow
from ocmanager.flows import subscriptions as flows
from ocmanager.subscriptions import service

app = typer.Typer(no_args_is_help=True)


@app.command("expire-now")
def expire_now(
    telegram_id: Annotated[int, typer.Argument(help="Telegram ID клиента")],
    sync: Annotated[bool, typer.Option("--sync/--no-sync", help="сразу обновить ноду")] = True,
) -> None:
    """Только dev: сдвинуть конец подписки на секунду в прошлое и запустить истечение."""
    refuse_in_production(settings())

    async def go() -> None:
        now = utcnow()
        async with db_sessionmaker() as sessionmaker:
            async with sessionmaker() as session:
                client = await client_by_telegram_id(session, telegram_id)
                sub = await service.get_subscription(session, client.id)
                if sub is None:
                    raise fail("у клиента нет подписки")
                sub.expires_at = now - timedelta(seconds=1)
                await flows.expire_due(session, now)
                await session.commit()
            if sync:
                await sync_now(sessionmaker)
        typer.echo(f"клиент {client.id}: подписка истекла")

    run(go)
