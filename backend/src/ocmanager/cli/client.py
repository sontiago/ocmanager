from typing import Annotated

import typer

from ocmanager.cli._common import CLI_ACTOR, db_session, run
from ocmanager.flows.clients import register_client
from ocmanager.subscriptions.schemas import TelegramIdentity

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
        async with db_session() as session:
            result = await register_client(session, ident, actor=CLI_ACTOR)
            await session.commit()
        c = result.client
        typer.echo(
            f"{'создан' if result.created else 'обновлён'}: клиент {c.id}, tg={c.telegram_id}"
        )

    run(go)
