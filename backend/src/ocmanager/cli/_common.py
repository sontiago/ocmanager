import os
from pathlib import Path

import typer

from ocmanager.core.config import Settings, get_settings
from ocmanager.core.logging import configure_logging


def settings() -> Settings:
    s = get_settings()
    configure_logging(s.log_level, fmt="console")  # иначе structlog печатает и debug
    return s


def fail(message: str) -> typer.Exit:
    """`raise fail("…")` — сообщение в stderr и код выхода 1."""
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def refuse_in_production(s: Settings) -> None:
    if s.env == "production":
        raise fail("команда только для dev: OCM_ENV=production")


def write_file(path: Path, data: bytes, mode: int) -> None:
    """Перезаписывает файл; права выставляются до записи содержимого."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
