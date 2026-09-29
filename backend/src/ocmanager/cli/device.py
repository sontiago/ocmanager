from pathlib import Path
from typing import Annotated

import typer

from ocmanager.cli._common import (
    CLI_ACTOR,
    db_sessionmaker,
    refuse_in_production,
    run,
    settings,
    sync_now,
    write_file,
)
from ocmanager.cli.client import client_by_telegram_id
from ocmanager.core.clock import utcnow
from ocmanager.flows import devices
from ocmanager.provisioning import service
from ocmanager.provisioning.pki.ca import load_ca

app = typer.Typer(no_args_is_help=True)

SyncOption = Annotated[bool, typer.Option("--sync/--no-sync", help="сразу обновить ноду")]


@app.command()
def issue(
    telegram_id: Annotated[int, typer.Argument(help="Telegram ID клиента")],
    name: Annotated[str, typer.Option(help="название устройства")],
    platform: Annotated[str, typer.Option(help="ios | android | windows | macos | linux")],
    out: Annotated[Path, typer.Option("--out", help="куда записать .p12")],
    sync: SyncOption = True,
) -> None:
    """Только dev: выпустить устройство и записать .p12 в файл. В проде .p12 на диск не
    пишется — его отдаёт одноразовая ссылка (TMA). Пароль печатается один раз."""
    s = settings()
    refuse_in_production(s)

    async def go() -> None:
        now = utcnow()
        async with db_sessionmaker() as sessionmaker:
            async with sessionmaker() as session:
                client = await client_by_telegram_id(session, telegram_id)
                limit = await devices.device_limit_for(session, client.id, now)
                result = await devices.issue_device(
                    session,
                    client_id=client.id,
                    name=name,
                    platform=platform,
                    device_limit=limit,
                    ca=load_ca(s.pki_dir),
                    actor=CLI_ACTOR,
                    now=now,
                )
                write_file(out, result.p12, 0o600)
                await session.commit()
            if sync:
                await sync_now(sessionmaker)
        d = result.device
        typer.echo(f"device:   {d.id}")
        typer.echo(f"username: {d.ocserv_username}")
        typer.echo(f"password: {result.password}")
        typer.echo(f"file:     {out}")

    run(go)


@app.command()
def revoke(
    device_id: Annotated[int, typer.Argument()],
    sync: SyncOption = True,
) -> None:
    """Отозвать устройство: allowed.list, разрыв сессии и CRL."""

    async def go() -> None:
        async with db_sessionmaker() as sessionmaker:
            async with sessionmaker() as session:
                device = await devices.revoke_device(
                    session,
                    device_id,
                    owner_client_id=None,
                    reason="revoked from cli",
                    actor=CLI_ACTOR,
                    now=utcnow(),
                )
                await session.commit()
            if sync:
                await sync_now(sessionmaker)
        typer.echo(f"{device.ocserv_username}: отозвано")

    run(go)


@app.command("list")
def list_(telegram_id: Annotated[int, typer.Argument(help="Telegram ID клиента")]) -> None:
    """Устройства клиента, включая отозванные."""

    async def go() -> None:
        async with db_sessionmaker() as sessionmaker, sessionmaker() as session:
            client = await client_by_telegram_id(session, telegram_id)
            for d in await service.list_devices(session, client.id, include_revoked=True):
                state = f"отозвано {d.revoked_at:%Y-%m-%d}" if d.revoked_at else "активно"
                typer.echo(f"{d.id:>5}  {d.ocserv_username:<14} {d.platform:<8} {d.name}  {state}")

    run(go)
