from typing import Annotated

import typer

from ocmanager.cli._common import db_session, run
from ocmanager.core.clock import utcnow
from ocmanager.flows.notify import to_admins

app = typer.Typer(no_args_is_help=True)

REASON_LIMIT = 300


@app.command("backup-failed")
def backup_failed(
    reason: Annotated[str, typer.Option(help="что пошло не так (обрезается до 300 символов)")],
) -> None:
    """Поставить админам алерт «резервная копия не создана». Вызывается скриптом бэкапа:
    сообщение уйдёт через воркер, как все остальные. За сутки приходит одно такое сообщение."""

    async def go() -> None:
        async with db_session() as session:
            queued = await to_admins(
                session,
                "backup_failed",
                {"reason": reason[:REASON_LIMIT]},
                dedupe_key=f"backup_failed:{utcnow().date().isoformat()}",
            )
            await session.commit()
        typer.echo(
            f"поставлено сообщений: {queued}" if queued else "админы не заданы: алерт не отправлен"
        )

    run(go)
