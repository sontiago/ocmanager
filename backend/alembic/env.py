import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from ocmanager.core.config import get_settings
from ocmanager.core.db import make_engine
from ocmanager.core.logging import configure_logging
from ocmanager.models import metadata

config = context.config
target_metadata = metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    return str(url) if url else get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = make_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if config.attributes.get("configure_logging", True):
    configure_logging("INFO", fmt="console")

if context.is_offline_mode():
    raise SystemExit("offline-режим (--sql) не поддерживается")
asyncio.run(_run_online())
