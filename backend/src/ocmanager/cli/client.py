from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.cli._common import CLI_ACTOR, db_sessionmaker, fail, run, sync_now
from ocmanager.core.clock import utcnow
from ocmanager.flows.clients import register_client
from ocmanager.flows.grants import grant_plan
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.service import find_client_by_telegram_id

app = typer.Typer(no_args_is_help=True)


@app.command()
def add(
    telegram_id: Annotated[int, typer.Option(help="Telegram ID клиента")],
    first_name: Annotated[str, typer.Option(help="имя")],
    username: Annotated[str | None, typer.Option(help="@username без @")] = None,
    lang: Annotated[str, typer.Option(help="ru или en")] = "ru",
) -> None:
    """Только dev: клиент без Telegram. В проде клиентов создаёт TMA при первом заходе."""

    async def go() -> None:
        ident = TelegramIdentity(telegram_id, first_name, username, lang)
        async with db_sessionmaker() as sessionmaker, sessionmaker() as session:
            result = await register_client(session, ident, actor=CLI_ACTOR)
            await session.commit()
        c = result.client
        typer.echo(
            f"{'создан' if result.created else 'обновлён'}: клиент {c.id}, tg={c.telegram_id}"
        )

    run(go)


async def client_by_telegram_id(session: AsyncSession, telegram_id: int) -> Client:
    client = await find_client_by_telegram_id(session, telegram_id)
    if client is None:
        raise fail(f"клиент с telegram_id={telegram_id} не найден")
    return client


@app.command()
def grant(
    telegram_id: Annotated[int, typer.Argument(help="Telegram ID клиента")],
    plan_code: Annotated[str, typer.Argument(help="код тарифа, например m1")],
    days: Annotated[int | None, typer.Option(help="вместо срока тарифа")] = None,
    sync: Annotated[bool, typer.Option("--sync/--no-sync", help="сразу обновить ноду")] = True,
) -> None:
    """Выдать тариф вручную: без оплаты и автопродления. Повторная выдача продлевает."""

    async def go() -> None:
        async with db_sessionmaker() as sessionmaker:
            async with sessionmaker() as session:
                client = await client_by_telegram_id(session, telegram_id)
                sub = await grant_plan(
                    session,
                    client_id=client.id,
                    plan_code=plan_code,
                    actor=CLI_ACTOR,
                    now=utcnow(),
                    days=days,
                )
                await session.commit()
            if sync:
                await sync_now(sessionmaker)
        typer.echo(f"клиент {client.id}: {sub.status} до {sub.expires_at:%Y-%m-%d %H:%M}Z")

    run(go)
