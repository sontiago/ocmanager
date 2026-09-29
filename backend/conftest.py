"""Общие фикстуры бэкенда.

Тесты никогда не читают backend/.env: настройки собираются из переменных
окружения с dev-значениями по умолчанию (совпадают с docker-compose.dev.yml).
CI может переопределить любое значение переменной OCM_*.

Тесты с БД и Redis работают в отдельных базах: Postgres — `<имя>_test`
(пересоздаётся на каждый запуск pytest), Redis — БД 15 (FLUSHDB до и после
каждого теста). Dev-данные они не трогают.
"""

import asyncio
import itertools
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from arq import ArqRedis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ocmanager.billing import plans as plan_service
from ocmanager.billing.models import Plan
from ocmanager.billing.plans import PlanCreate
from ocmanager.core.config import Settings
from ocmanager.core.db import make_engine
from ocmanager.core.redis import create_redis
from ocmanager.events import bus
from ocmanager.models import metadata
from ocmanager.subscriptions import service as client_service
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.schemas import TelegramIdentity

BACKEND_DIR = Path(__file__).parent

TEST_ENV_DEFAULTS = {
    "OCM_ENV": "test",
    "OCM_DATABASE_URL": "postgresql+asyncpg://ocm:ocm@127.0.0.1:54320/ocmanager",
    "OCM_REDIS_URL": "redis://127.0.0.1:63790/0",
    "OCM_SECRET_KEY": "test-secret-key-0123456789abcdef0123",
    # Каталоги dev-стенда: их читают интеграционные тесты (tests/integration).
    # Юнит-тесты PKI и CLI подставляют tmp_path.
    "OCM_PKI_DIR": str(BACKEND_DIR.parent / ".dev" / "pki"),
    "OCM_OCSERV_STATE_DIR": str(BACKEND_DIR.parent / ".dev" / "ocserv-state"),
}
for _key, _value in TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

DB_FIXTURES = frozenset(
    {
        "db_engine",
        "db_conn",
        "sessionmaker",
        "session",
        "committed_sessionmaker",
        "redis",
    }
)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Тест, который берёт фикстуру с БД или Redis, автоматически получает маркер db."""
    for item in items:
        if DB_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.db)


def _test_database_url(url: str, suffix: str = "_test") -> str:
    u = make_url(url)
    return u.set(database=f"{u.database}{suffix}").render_as_string(hide_password=False)


def _test_redis_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/15"


@pytest.fixture(scope="session")
def settings() -> Settings:
    base = Settings(_env_file=None)
    return base.model_copy(
        update={
            "env": "test",
            "database_url": _test_database_url(base.database_url),
            "redis_url": _test_redis_url(base.redis_url),
        }
    )


async def recreate_database(url: str) -> None:
    """DROP + CREATE базы по URL. Подключается к служебной БД postgres."""
    target = make_url(url)
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    except OSError as exc:
        pytest.fail(
            f"Postgres недоступен ({exc}). Поднимите dev-инфраструктуру: make dev-up",
            pytrace=False,
        )
    finally:
        await admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logging"] = False
    return cfg


async def run_alembic(url: str, cmd: str, *args: str) -> None:
    """env.py сам вызывает asyncio.run, поэтому Alembic работает в отдельном потоке."""
    await asyncio.to_thread(getattr(command, cmd), alembic_config(url), *args)


@pytest.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    await recreate_database(settings.database_url)
    await run_alembic(settings.database_url, "upgrade", "head")
    engine = make_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_conn(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Соединение с открытой внешней транзакцией; после теста — откат."""
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()


@pytest.fixture
def sessionmaker(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий на соединении теста. `commit()` в коде под тестом
    коммитит только SAVEPOINT, всё откатывается после теста. Код, открывающий
    свои сессии (воркер, обработчики событий), видит данные теста."""
    return async_sessionmaker(
        bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
async def session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as s:
        yield s


@pytest.fixture
async def committed_sessionmaker(
    db_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Настоящие коммиты на отдельных соединениях — для тестов конкуренции
    (FOR UPDATE SKIP LOCKED). После теста все таблицы очищаются."""
    yield async_sessionmaker(db_engine, expire_on_commit=False)
    tables = ", ".join(f'"{t.name}"' for t in metadata.sorted_tables)
    if tables:
        async with db_engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[ArqRedis]:
    client = await create_redis(settings.redis_url)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture(autouse=True)
def _isolated_event_handlers() -> Iterator[None]:
    """Обработчики, зарегистрированные тестом, не утекают в соседние тесты."""
    with bus.isolated_handlers():
        yield


MakeClient = Callable[..., Awaitable[Client]]
MakePlan = Callable[..., Awaitable[Plan]]


@pytest.fixture
def make_client(session: AsyncSession) -> MakeClient:
    """Фабрика клиентов: telegram_id подбирается сам. `await make_client(first_name="Anna")`."""
    counter = itertools.count(5001)

    async def make(**over: Any) -> Client:
        fields: dict[str, Any] = {
            "telegram_id": next(counter),
            "first_name": "Test",
            "username": None,
            "language_code": "ru",
        } | over
        return (await client_service.upsert_client(session, TelegramIdentity(**fields))).client

    return make


@pytest.fixture
def make_plan(session: AsyncSession) -> MakePlan:
    """Фабрика тарифов: по умолчанию месяц на 3 устройства, код подбирается сам."""
    counter = itertools.count(1)

    async def make(**over: Any) -> Plan:
        fields: dict[str, Any] = {
            "code": f"plan{next(counter)}",
            "name_i18n": {"ru": "Тариф", "en": "Plan"},
            "duration_days": 30,
            "device_limit": 3,
            "traffic_limit_bytes": 100 * 1024**3,
            "price_amount": 19900,
            "currency": "RUB",
        } | over
        return await plan_service.create_plan(session, PlanCreate(**fields))

    return make


@pytest.fixture
async def trial_plan(session: AsyncSession) -> Plan:
    """Скрытый тариф trial. Его сеет миграция, но тесты с committed_sessionmaker
    очищают таблицы — поэтому при необходимости создаём заново."""
    name = json.dumps({"ru": "Пробный", "en": "Trial"}, ensure_ascii=False)
    await session.execute(
        text(
            "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
            " currency, is_active, is_trial)"
            " VALUES ('trial', CAST(:name AS jsonb), 3, 1, 0, 'RUB', false, true)"
            " ON CONFLICT DO NOTHING"
        ),
        {"name": name},
    )
    return await plan_service.get_trial_plan(session)
