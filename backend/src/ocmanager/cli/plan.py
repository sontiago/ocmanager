from typing import Annotated

import typer
from pydantic import ValidationError

from ocmanager.billing import plans
from ocmanager.billing.plans import PlanCreate
from ocmanager.cli._common import CLI_ACTOR, db_session, fail, run
from ocmanager.flows import plans as plan_flows

app = typer.Typer(no_args_is_help=True)

GIB = 1024**3


@app.command()
def create(
    code: Annotated[str, typer.Option(help="латиницей, например m1")],
    name_ru: Annotated[str, typer.Option()],
    name_en: Annotated[str, typer.Option()],
    days: Annotated[int, typer.Option(help="срок действия")],
    devices: Annotated[int, typer.Option(help="лимит устройств")],
    price: Annotated[int, typer.Option(help="в минорных единицах: 19900 = 199.00")],
    currency: Annotated[str, typer.Option()] = "RUB",
    traffic_gib: Annotated[int | None, typer.Option(help="без значения — безлимит")] = None,
    sort_order: Annotated[int, typer.Option()] = 0,
) -> None:
    """Создать тариф."""
    try:
        data = PlanCreate(
            code=code,
            name_i18n={"ru": name_ru, "en": name_en},
            duration_days=days,
            device_limit=devices,
            traffic_limit_bytes=None if traffic_gib is None else traffic_gib * GIB,
            price_amount=price,
            currency=currency,
            sort_order=sort_order,
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise fail(f"{'.'.join(map(str, first['loc']))}: {first['msg']}") from None

    async def go() -> None:
        async with db_session() as session:
            plan = await plan_flows.create_plan(session, data, CLI_ACTOR)
            await session.commit()
        typer.echo(f"тариф {plan.code} создан")

    run(go)


@app.command("list")
def list_() -> None:
    """Все тарифы, включая скрытые."""

    async def go() -> None:
        async with db_session() as session:
            for p in await plans.list_all(session):
                flags = ("trial " if p.is_trial else "") + ("" if p.is_active else "выключен")
                typer.echo(
                    f"{p.code:<12} {p.duration_days:>4} дн  устройств {p.device_limit}  "
                    f"{p.price_amount / 100:.2f} {p.currency}  {flags}".rstrip()
                )

    run(go)
