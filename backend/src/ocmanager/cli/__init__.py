"""Командная строка оператора: `uv run ocmanager --help`.

CLI — слой склейки (как flows/ и apps/): ему можно импортировать любые домены.
"""

import typer

from ocmanager.cli import client, node, pki, plan

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(pki.app, name="pki", help="Удостоверяющий центр и сертификаты")
app.add_typer(node.app, name="node", help="Нода ocserv: статус, сессии, действия")
app.add_typer(client.app, name="client", help="Клиенты")
app.add_typer(plan.app, name="plan", help="Тарифы")
