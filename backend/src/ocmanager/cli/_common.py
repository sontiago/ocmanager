import asyncio
import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.errors import DomainError
from ocmanager.core.logging import configure_logging
from ocmanager.events import bus
from ocmanager.flows import handlers
from ocmanager.flows import revocations as revocation_flows
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.provisioning.pki.ca import load_ca

# Действия из командной строки в аудите — от «оператора cli».
CLI_ACTOR = Actor(type="admin", id="cli")


def settings() -> Settings:
    s = get_settings()
    configure_logging(s.log_level, fmt="console")  # иначе structlog печатает и debug
    return s


def fail(message: str) -> typer.Exit:
    """`raise fail("…")` — сообщение в stderr и код выхода 1."""
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def run(coro: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Запускает корутину команды; доменные ошибки — в stderr и код 1, без трейсбека."""
    try:
        asyncio.run(coro())
    except DomainError as exc:
        raise fail(f"{exc.code}: {exc.message}") from None
    except NodeUnreachable as exc:
        raise fail(f"нода недоступна: {exc}") from None


@asynccontextmanager
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(settings().database_url)
    try:
        yield make_sessionmaker(engine)
    finally:
        await engine.dispose()


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """Сессия БД на одну команду. Коммит — в команде: без него ничего не сохранится."""
    async with db_sessionmaker() as sessionmaker, sessionmaker() as session:
        yield session


async def sync_now(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Dev-удобство: сразу довести изменения до ноды, не дожидаясь воркера — доставить
    события (allowed.list, разрыв сессий) и применить отзывы (CRL). Недоступная нода не
    ломает команду: данные уже в БД, воркер и reconcile догонят."""
    s = settings()
    handlers.register(s)
    await bus.dispatch_pending(sessionmaker)
    try:
        async with sessionmaker() as session:
            await revocation_flows.apply_revocations(session, s, load_ca(s.pki_dir), utcnow())
            await session.commit()
    except NodeUnreachable as exc:
        typer.echo(f"нода недоступна, синхронизация отложена: {exc}", err=True)


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
