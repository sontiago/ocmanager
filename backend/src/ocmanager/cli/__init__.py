"""Командная строка оператора: `uv run ocmanager --help`.

CLI — слой склейки (как flows/ и apps/): ему можно импортировать любые домены.
"""

import typer

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.cli import admin, client, device, node, pki, plan, reconcile, subscription

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(admin.app, name="admin", help="Админы панели")
app.add_typer(pki.app, name="pki", help="Удостоверяющий центр и сертификаты")
app.add_typer(node.app, name="node", help="Нода ocserv: статус, сессии, действия")
app.add_typer(client.app, name="client", help="Клиенты")
app.add_typer(plan.app, name="plan", help="Тарифы")
app.add_typer(device.app, name="device", help="Устройства клиентов")
app.add_typer(subscription.app, name="subscription", help="Подписки (dev-утилиты)")
app.command("reconcile")(reconcile.reconcile)
