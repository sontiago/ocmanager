import sys
from typing import Annotated

import typer

from ocmanager.admin import accounts
from ocmanager.cli._common import CLI_ACTOR, db_session, fail, run

app = typer.Typer(no_args_is_help=True)

StdinOption = Annotated[
    bool, typer.Option("--password-stdin", help="прочитать пароль из stdin, одной строкой")
]


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    return str(typer.prompt("Пароль", hide_input=True, confirmation_prompt=True))


@app.command()
def create(
    username: Annotated[str, typer.Argument(help="[a-z0-9_.-], 3..32 символа")],
    password_stdin: StdinOption = False,
) -> None:
    """Создать админа. Пароль — минимум 12 символов, не длиннее 72 байт."""
    password = read_password(password_stdin)

    async def go() -> None:
        async with db_session() as session:
            admin = await accounts.create_admin(session, username, password, CLI_ACTOR)
            await session.commit()
        typer.echo(f"создан: админ {admin.id}, {admin.username}")

    run(go)


@app.command()
def passwd(
    username: Annotated[str, typer.Argument()],
    password_stdin: StdinOption = False,
) -> None:
    """Сменить пароль (например, забытый). Все сессии этого админа закрываются."""
    password = read_password(password_stdin)

    async def go() -> None:
        async with db_session() as session:
            admin = await accounts.get_by_username(session, username)
            if admin is None:
                raise fail(f"админ {username!r} не найден")
            await accounts.set_password(session, admin, password, CLI_ACTOR)
            await session.commit()
        typer.echo(f"пароль {username} изменён, сессии закрыты")

    run(go)


@app.command("reset-totp")
def reset_totp(username: Annotated[str, typer.Argument()]) -> None:
    """Выключить TOTP админу, потерявшему телефон. Войти можно будет по одному паролю."""

    async def go() -> None:
        async with db_session() as session:
            admin = await accounts.get_by_username(session, username)
            if admin is None:
                raise fail(f"админ {username!r} не найден")
            changed = await accounts.reset_totp(session, admin, CLI_ACTOR)
            await session.commit()
        typer.echo(f"TOTP {username} выключен" if changed else f"у {username} TOTP не включён")

    run(go)


@app.command("list")
def list_() -> None:
    """Все админы."""

    async def go() -> None:
        async with db_session() as session:
            for a in await accounts.list_admins(session):
                totp = "totp" if a.totp_enabled else "-"
                state = "активен" if a.is_active else "отключён"
                last = f"{a.last_login_at:%Y-%m-%d %H:%M}Z" if a.last_login_at else "не входил"
                typer.echo(f"{a.id:>3}  {a.username:<20} {a.role:<6} {totp:<5} {state:<9} {last}")

    run(go)
