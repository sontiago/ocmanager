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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from arq import ArqRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.types import Message

from ocmanager.admin import accounts
from ocmanager.admin.models import Admin
from ocmanager.apps.admin_api import create_app as create_admin_app
from ocmanager.apps.public_api import create_app as create_public_app
from ocmanager.audit.service import Actor
from ocmanager.billing import plans as plan_service
from ocmanager.billing.models import Plan
from ocmanager.billing.plans import PlanCreate
from ocmanager.core import security
from ocmanager.core.config import Settings
from ocmanager.core.db import make_engine
from ocmanager.core.redis import create_redis
from ocmanager.events import bus
from ocmanager.models import metadata
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority, create_ca
from ocmanager.subscriptions import service as subscription_service
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.state import PlanTerms
from ocmanager.tma.testing import make_init_data

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
    "OCM_INTERNAL_TOKEN": "test-internal-token-0123456789abcdef",
    "OCM_CAMOUFLAGE_SECRET": "devsecret",
    "OCM_BOT_TOKEN": "123456:test-bot-token-not-real",
    "OCM_TRIBUTE_API_KEY": "test-tribute-api-key-not-real",
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
MakeDevice = Callable[..., Awaitable[Device]]
MakeSubscription = Callable[..., Awaitable[Subscription]]


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
        return (
            await subscription_service.upsert_client(session, TelegramIdentity(**fields))
        ).client

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


@pytest.fixture(scope="session")
def test_ca() -> CertificateAuthority:
    """CA на весь прогон: RSA-3072 генерируется секунду, а не в каждом тесте."""
    return create_ca("ocmanager test CA", datetime(2026, 9, 22, 12, tzinfo=UTC))


@pytest.fixture
def make_subscription(session: AsyncSession, make_plan: MakePlan) -> MakeSubscription:
    """Живая подписка клиенту: `await make_subscription(client, days=30, now=NOW)`.
    Начало — `now`, конец — now + days."""

    async def make(client: Client, *, days: int = 30, now: datetime, **over: Any) -> Subscription:
        plan = await make_plan(duration_days=days)
        terms = PlanTerms(
            plan.id, plan.duration_days, plan.device_limit, plan.traffic_limit_bytes, False
        )
        return await subscription_service.activate(
            session, client.id, terms, now, auto_renew=over.pop("auto_renew", True)
        )

    return make


@pytest.fixture
def make_device(session: AsyncSession) -> MakeDevice:
    """Устройство без настоящего сертификата — быстрее, чем issue_device (нужен RSA)."""
    serials = itertools.count(1)

    async def make(client: Client, *, seq: int = 1, revoked: bool = False) -> Device:
        n = next(serials)
        moment = datetime(2026, 9, 22, tzinfo=UTC)
        device = Device(
            client_id=client.id,
            seq=seq,
            name=f"dev{seq}",
            platform="linux",
            ocserv_username=f"c{client.id}-d{seq}",
            cert_serial=f"{n:x}",
            cert_fingerprint="00" * 32,
            issued_at=moment,
            cert_expires_at=moment.replace(year=2027),
            revoked_at=moment if revoked else None,
        )
        session.add(device)
        await session.flush()
        return device

    return make


ADMIN_PASSWORD = "correct-horse-battery"
MakeAdmin = Callable[..., Awaitable[Admin]]


@pytest.fixture
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """bcrypt cost 12 — четверть секунды на хеш; в тестах хватает минимального."""
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    security._dummy_hash.cache_clear()


@pytest.fixture
def make_admin(session: AsyncSession, fast_bcrypt: None) -> MakeAdmin:
    """Фабрика админов: `await make_admin("alice")`, пароль — ADMIN_PASSWORD."""

    async def make(username: str = "alice", password: str = ADMIN_PASSWORD) -> Admin:
        admin = await accounts.create_admin(session, username, password, Actor.system())
        await session.flush()  # запись аудита получает id сейчас, а не при первом чтении
        return admin

    return make


@pytest.fixture
def admin_app(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    test_ca: CertificateAuthority,
) -> FastAPI:
    """Админ-API на соединении теста. Lifespan не запускается: сессии и Redis подставлены."""
    app = create_admin_app(settings)
    app.state.sessionmaker = sessionmaker
    app.state.redis = redis
    app.state.ca = test_ca  # иначе CA читался бы с диска
    return app


NewClient = Callable[[], AsyncClient]


@pytest.fixture
def new_client(admin_app: FastAPI) -> NewClient:
    """Ещё один браузер: свой набор cookie. `async with new_client() as other:`."""

    def make() -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://localhost")

    return make


@pytest.fixture
async def anon_client(new_client: NewClient) -> AsyncIterator[AsyncClient]:
    async with new_client() as client:
        yield client


@pytest.fixture
async def admin_client(anon_client: AsyncClient, make_admin: MakeAdmin) -> AsyncClient:
    """Клиент с залогиненным админом alice: cookie сохранена, X-CSRF-Token проставлен."""
    await make_admin("alice")
    r = await anon_client.post(
        "/admin/auth/login", json={"username": "alice", "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 200, r.text
    anon_client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return anon_client


TMA_TELEGRAM_ID = 7001
TmaHeaders = Callable[..., dict[str, str]]


@pytest.fixture
def public_app(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    test_ca: CertificateAuthority,
) -> FastAPI:
    """Публичный API на соединении теста. Lifespan не запускается: сессии и Redis подставлены."""
    app = create_public_app(settings)
    app.state.sessionmaker = sessionmaker
    app.state.redis = redis
    app.state.ca = test_ca
    return app


@pytest.fixture
def tma_headers(settings: Settings) -> TmaHeaders:
    """Заголовок Authorization с настоящей подписью: `tma_headers(telegram_id=5, age_s=10)`."""

    def make(
        telegram_id: int = TMA_TELEGRAM_ID,
        first_name: str = "Anna",
        language_code: str = "ru",
        age_s: int = 0,
    ) -> dict[str, str]:
        raw = make_init_data(
            settings.bot_token.get_secret_value(),
            user={"id": telegram_id, "first_name": first_name, "language_code": language_code},
            auth_date=int(datetime.now(UTC).timestamp()) - age_s,
        )
        return {"Authorization": f"tma {raw}"}

    return make


@pytest.fixture
async def public_client(public_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Клиент публичного API без заголовков: для проверки отказов и скачивания по ссылке."""
    async with AsyncClient(
        transport=ASGITransport(app=public_app), base_url="http://localhost"
    ) as client:
        yield client


@pytest.fixture
async def tma_client(public_app: FastAPI, tma_headers: TmaHeaders) -> AsyncIterator[AsyncClient]:
    """Клиент TMA: Анна с telegram_id=TMA_TELEGRAM_ID, язык ru."""
    async with AsyncClient(
        transport=ASGITransport(app=public_app),
        base_url="http://localhost",
        headers=tma_headers(),
    ) as client:
        yield client


async def read_stream_then_disconnect(
    app: FastAPI, cookie: str, *, chunks: int, path: str = "/admin/node/logs"
) -> list[bytes]:
    """httpx.ASGITransport отдаёт ответ только целиком, бесконечный поток он не вынесет.
    Поэтому приложение вызывается напрямую: клиент читает `chunks` кусков и «отключается»."""
    gone = asyncio.Event()
    received: list[bytes] = []

    async def receive() -> Message:
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            received.append(message["body"])
            if len(received) >= chunks:
                gone.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"tail=5",
        "root_path": "",
        "headers": [(b"host", b"localhost:8080"), (b"cookie", f"ocm_admin={cookie}".encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 8080),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return received
