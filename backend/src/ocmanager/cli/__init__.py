"""Командная строка оператора: `uv run ocmanager --help`.

CLI — слой склейки (как flows/ и apps/): ему можно импортировать любые домены.
"""

import typer

from ocmanager.cli import pki

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(pki.app, name="pki", help="Удостоверяющий центр и сертификаты")
