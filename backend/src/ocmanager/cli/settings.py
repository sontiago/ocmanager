from typing import Annotated

import typer

from ocmanager.cli._common import db_session, run
from ocmanager.core import settings_store

app = typer.Typer(no_args_is_help=True)


@app.command("admin-chat")
def admin_chat(
    chat_id: Annotated[int, typer.Argument(help="число из ответа бота на /whoami")],
) -> None:
    """Добавить chat id в `admin_chat_ids`: туда приходят алерты админу. Повтор безвреден."""

    async def go() -> None:
        async with db_session() as session:
            current = (await settings_store.load(session)).admin_chat_ids
            if chat_id not in current:
                await settings_store.update(session, {"admin_chat_ids": [*current, chat_id]})
            await session.commit()
            final = (await settings_store.load(session)).admin_chat_ids
        typer.echo("admin_chat_ids: " + ", ".join(str(c) for c in final))

    run(go)
