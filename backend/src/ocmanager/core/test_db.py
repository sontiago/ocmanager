from datetime import datetime

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.db import Base, SessionDep


async def test_session_sees_own_writes(session: AsyncSession) -> None:
    await session.execute(text("CREATE TEMP TABLE t (x int)"))
    await session.execute(text("INSERT INTO t VALUES (1)"))
    assert (await session.execute(text("SELECT count(*) FROM t"))).scalar_one() == 1


async def test_migrations_applied(session: AsyncSession) -> None:
    version = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version is not None


async def test_database_timezone_is_utc(session: AsyncSession) -> None:
    now = await session.scalar(text("SELECT now()"))
    assert isinstance(now, datetime)
    assert now.utcoffset() is not None


def test_datetime_columns_are_timestamptz() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone, f"{table.name}.{column.name} без timezone"


def make_app(sessionmaker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    app.state.sessionmaker = sessionmaker

    @app.post("/insert")
    async def insert(session: SessionDep, commit: bool = False, fail: bool = False) -> None:
        await session.execute(text("INSERT INTO t VALUES (1)"))
        await session.flush()
        if fail:
            raise RuntimeError("boom")
        if commit:
            await session.commit()

    return app


async def count_rows(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as s:
        return int((await s.execute(text("SELECT count(*) FROM t"))).scalar_one())


async def post(app: FastAPI, url: str) -> int:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return (await client.post(url)).status_code


async def test_get_session_keeps_explicit_commit(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        await s.execute(text("CREATE TEMP TABLE t (x int)"))
        await s.commit()
    assert await post(make_app(sessionmaker), "/insert?commit=true") == 200
    assert await count_rows(sessionmaker) == 1


async def test_get_session_discards_uncommitted_work(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        await s.execute(text("CREATE TEMP TABLE t (x int)"))
        await s.commit()
    app = make_app(sessionmaker)
    assert await post(app, "/insert") == 200
    assert await post(app, "/insert?fail=true") == 500
    assert await count_rows(sessionmaker) == 0
