"""Нагрузочные проверки этапа 2 (спека §13): сбор трафика при 500 активных сессиях и время
ответа админки на графиках за год.

    make dev-up
    make test-load

Не входят в `make check`: нужны Postgres и Redis и занимают десятки секунд. Бюджеты времени —
запас в несколько раз над измеренным на ноутбуке разработчика; на медленной машине их можно
растянуть: `OCM_LOAD_BUDGET_SCALE=3 make test-load`.
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import MakePlan
from httpx import AsyncClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Payment
from ocmanager.core.config import Settings
from ocmanager.flows import traffic as traffic_flows
from ocmanager.nodes import registry, traffic
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import SessionLog, TrafficDaily
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions.models import Client, Subscription
from ocmanager.subscriptions.referral import new_referral_code

pytestmark = pytest.mark.load

SESSIONS = 500
YEAR = 365
PAYMENTS = 5000
SCALE = float(os.environ.get("OCM_LOAD_BUDGET_SCALE", "1"))
CHUNK = 10_000
GIB = 1024**3
NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)

# Бюджеты, секунды. Первый опрос создаёт 500 строк сессий и сэмплов, остальные обновляют их.
BUDGET_COLLECT = 5 * SCALE
BUDGET_USAGE = 10 * SCALE
BUDGET_ENDPOINT = 1 * SCALE


@contextmanager
def timed(label: str, budget: float, report: list[str]) -> Iterator[None]:
    start = time.perf_counter()
    yield
    took = time.perf_counter() - start
    report.append(f"{label}: {took:.2f} s (бюджет {budget:.0f} s)")
    assert took <= budget, f"{label}: {took:.2f} s при бюджете {budget:.0f} s"


async def analyze(session: AsyncSession) -> None:
    """Статистика планировщика, как её держит autovacuum на живой базе. Сразу после массовой
    вставки в транзакцию её нет, и Postgres выбирает планы для «пустых» таблиц."""
    for table in (
        "clients",
        "subscriptions",
        "devices",
        "traffic_daily",
        "payments",
        "session_log",
    ):
        await session.execute(text(f"ANALYZE {table}"))


async def seed_population(session: AsyncSession, make_plan: MakePlan) -> list[str]:
    """500 клиентов с живой подпиской и по одному устройству. Возвращает имена пользователей."""
    plan = await make_plan(traffic_limit_bytes=1000 * GIB)
    clients = [
        Client(
            telegram_id=10_000 + i, first_name=f"C{i}", lang="ru", referral_code=new_referral_code()
        )
        for i in range(SESSIONS)
    ]
    session.add_all(clients)
    await session.flush()
    session.add_all(
        Subscription(
            client_id=c.id,
            plan_id=plan.id,
            status="active",
            plan_is_trial=False,
            started_at=NOW - timedelta(days=5),
            expires_at=NOW + timedelta(days=25),
            auto_renew=True,
            device_limit=3,
            traffic_limit_bytes=1000 * GIB,
            traffic_used_bytes=0,
            traffic_period_start=NOW - timedelta(days=5),
        )
        for c in clients
    )
    devices = [
        Device(
            client_id=c.id,
            seq=1,
            name="d",
            platform="linux",
            ocserv_username=f"c{c.id}-d1",
            cert_serial=f"{c.id:x}",
            cert_fingerprint="00",
            issued_at=NOW - timedelta(days=5),
            cert_expires_at=NOW + timedelta(days=300),
        )
        for c in clients
    ]
    session.add_all(devices)
    await session.flush()
    return [d.ocserv_username for d in devices]


async def test_traffic_collection_with_500_active_sessions(
    session: AsyncSession, settings: Settings, make_plan: MakePlan
) -> None:
    report: list[str] = []
    usernames = await seed_population(session, make_plan)
    node = await registry.ensure_local_node(session, settings)
    fake = FakeNodeDriver()
    for i, username in enumerate(usernames):
        fake.add_session(
            username,
            bytes_in=(i + 1) * 1_000_000,
            bytes_out=(i + 1) * 500_000,
            session_id=str(i),
            connected_at=NOW - timedelta(hours=1),
        )

    # Первый опрос: все 500 сессий новые.
    with timed("опрос нод, 500 новых сессий", BUDGET_COLLECT, report):
        result = await traffic.collect(session, node.id, fake.sessions, NOW)
    assert (result.seen, result.opened) == (SESSIONS, SESSIONS)

    # Второй опрос: у всех приросли счётчики.
    grown = [replace(s, bytes_in=s.bytes_in + 5_000_000) for s in fake.sessions]
    with timed("опрос нод, 500 обновлённых сессий", BUDGET_COLLECT, report):
        result = await traffic.collect(session, node.id, grown, NOW + timedelta(minutes=5))
    assert (result.seen, result.opened, result.closed) == (SESSIONS, 0, 0)

    with timed("перенос расхода в подписки, 500 клиентов", BUDGET_USAGE, report):
        await traffic_flows.apply_usage(session, usernames, NOW + timedelta(minutes=5))

    # Результат верен, а не просто быстр: расход каждого клиента записан в подписку.
    used = await session.scalar(select(func.sum(Subscription.traffic_used_bytes)))
    expected = sum((i + 1) * 1_500_000 + 5_000_000 for i in range(SESSIONS))
    assert used == expected
    open_sessions = await session.scalar(
        select(func.count()).select_from(SessionLog).where(SessionLog.ended_at.is_(None))
    )
    assert open_sessions == SESSIONS
    print("\n" + "\n".join(report))


async def seed_year(session: AsyncSession, usernames: list[str], client_ids: list[int]) -> None:
    node = await registry.ensure_local_node(session, Settings(_env_file=None))
    rows = [
        {
            "username": username,
            "node_id": node.id,
            "day": (NOW - timedelta(days=age)).date(),
            "bytes_in": 3 * GIB + age,
            "bytes_out": GIB + age,
            "duration_sec": 3600,
        }
        for username in usernames
        for age in range(YEAR)
    ]
    for i in range(0, len(rows), CHUNK):
        await session.execute(insert(TrafficDaily), rows[i : i + CHUNK])
    payments: list[dict[str, Any]] = [
        {
            "client_id": client_ids[i % len(client_ids)],
            "provider": "tribute",
            "external_id": f"load-{i}",
            "amount": 19900 + (i % 5) * 1000,
            "currency": "RUB" if i % 10 else "USD",
            "status": "succeeded",
            "raw_payload": {},
            "received_at": NOW - timedelta(days=i % YEAR, minutes=i % 1440),
            "processed_at": NOW,
        }
        for i in range(PAYMENTS)
    ]
    for i in range(0, len(payments), CHUNK):
        await session.execute(insert(Payment), payments[i : i + CHUNK])
    await session.flush()
    await analyze(session)


async def test_admin_charts_for_a_year_stay_fast(
    admin_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    report: list[str] = []
    usernames = await seed_population(session, make_plan)
    client_ids = list(await session.scalars(select(Client.id).order_by(Client.id)))
    await seed_year(session, usernames, client_ids)
    rows = await session.scalar(select(func.count()).select_from(TrafficDaily))
    assert rows == SESSIONS * YEAR

    for path in (
        "/admin/stats/traffic?days=366",
        "/admin/stats/revenue?days=366",
        "/admin/stats/clients?days=366",
        "/admin/stats/economics",
        "/admin/overview",
        "/admin/export/traffic.csv?days=366",
    ):
        with timed(f"GET {path}", BUDGET_ENDPOINT, report):
            r = await admin_client.get(path)
        assert r.status_code == 200, f"{path}: {r.text[:200]}"

    traffic_body = (await admin_client.get("/admin/stats/traffic?days=366")).json()
    assert len(traffic_body["days"]) == 366
    assert len(traffic_body["top_clients"]) == 10
    revenue_body = (await admin_client.get("/admin/stats/revenue?days=366")).json()
    assert sum(t["count"] for t in revenue_body["totals"]) == PAYMENTS
    print("\n" + "\n".join(report))
