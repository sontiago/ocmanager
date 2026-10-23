from datetime import timedelta

import pytest
from conftest import MakeClient, MakeDevice, MakePayment, MakePlan, MakeSubscription
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.nodes import registry
from ocmanager.nodes.models import TrafficDaily

PATHS = ["traffic", "revenue", "clients", "economics"]


@pytest.mark.parametrize("path", PATHS)
async def test_a_session_is_required(anon_client: AsyncClient, path: str) -> None:
    assert (await anon_client.get(f"/admin/stats/{path}")).status_code == 401


@pytest.mark.parametrize("path", ["traffic", "revenue", "clients"])
@pytest.mark.parametrize("days", [0, 367, -1])
async def test_days_are_bounded(admin_client: AsyncClient, path: str, days: int) -> None:
    assert (await admin_client.get(f"/admin/stats/{path}?days={days}")).status_code == 422


async def test_an_empty_system_gives_zero_filled_series(admin_client: AsyncClient) -> None:
    today = utcnow().date()

    traffic = (await admin_client.get("/admin/stats/traffic?days=7")).json()
    assert len(traffic["days"]) == 7
    assert traffic["days"][-1] == {"day": today.isoformat(), "bytes_in": 0, "bytes_out": 0}
    assert traffic["days"][0]["day"] == (today - timedelta(days=6)).isoformat()
    assert traffic["top_clients"] == []

    revenue = (await admin_client.get("/admin/stats/revenue?days=7")).json()
    assert len(revenue["series"]) == 7
    assert all(p["amounts"] == {} for p in revenue["series"])
    assert revenue["totals"] == []

    clients = (await admin_client.get("/admin/stats/clients?days=7")).json()
    assert len(clients["series"]) == 7
    assert (clients["total"], clients["new_in_period"], clients["paying_in_period"]) == (0, 0, 0)

    economics = (await admin_client.get("/admin/stats/economics")).json()
    assert economics == {"mrr": {}, "arpu": {}, "active_paid": 0}


async def test_traffic_sums_per_day_and_ranks_clients(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    node = await registry.ensure_local_node(session, settings)
    big = await make_client(first_name="Big", username="big")
    small = await make_client(first_name="Small")
    d_big, d_big2, d_small = (
        await make_device(big, seq=1),
        await make_device(big, seq=2),
        await make_device(small, seq=1),
    )
    today = utcnow().date()
    rows = [
        (d_big.ocserv_username, 0, 100, 200),
        (d_big2.ocserv_username, 0, 10, 20),
        (d_small.ocserv_username, 1, 5, 5),
        ("c999-d1", 0, 7, 7),  # устройства нет в БД: в топ не попадает, в сумму по дням попадает
        (d_big.ocserv_username, 40, 1, 1),  # вне окна
    ]
    for username, age, rx, tx in rows:
        session.add(
            TrafficDaily(
                username=username,
                node_id=node.id,
                day=today - timedelta(days=age),
                bytes_in=rx,
                bytes_out=tx,
            )
        )
    await session.flush()

    body = (await admin_client.get("/admin/stats/traffic?days=30")).json()
    by_day = {p["day"]: p for p in body["days"]}
    assert by_day[today.isoformat()]["bytes_in"] == 117
    assert by_day[today.isoformat()]["bytes_out"] == 227
    assert by_day[(today - timedelta(days=1)).isoformat()]["bytes_in"] == 5
    assert [c["client_id"] for c in body["top_clients"]] == [big.id, small.id]
    top = body["top_clients"][0]
    assert (top["name"], top["username"], top["bytes_in"], top["bytes_out"]) == (
        "Big",
        "big",
        110,
        220,
    )


async def test_revenue_is_split_by_currency_and_refunds_are_separate(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    now = utcnow()
    a, b = await make_client(), await make_client()
    await make_payment(a, amount=1000, currency="RUB", received_at=now)
    await make_payment(a, amount=500, currency="RUB", received_at=now - timedelta(days=1))
    await make_payment(b, amount=300, currency="USD", received_at=now)
    await make_payment(b, amount=200, currency="RUB", status="refunded", received_at=now)
    await make_payment(b, amount=9999, currency="RUB", received_at=now - timedelta(days=100))

    body = (await admin_client.get("/admin/stats/revenue?days=30")).json()
    by_day = {p["day"]: p["amounts"] for p in body["series"]}
    assert by_day[now.date().isoformat()] == {"RUB": 1000, "USD": 300}
    assert by_day[(now - timedelta(days=1)).date().isoformat()] == {"RUB": 500}
    totals = {t["currency"]: t for t in body["totals"]}
    assert totals["RUB"] == {
        "currency": "RUB",
        "amount": 1500,
        "count": 2,
        "refunded_amount": 200,
        "refunded_count": 1,
    }
    assert totals["USD"]["amount"] == 300
    assert totals["USD"]["refunded_amount"] == 0


async def test_clients_counts_new_and_paying(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    payer, _free = await make_client(), await make_client()
    await make_payment(payer, received_at=utcnow())
    await make_payment(payer, received_at=utcnow())

    body = (await admin_client.get("/admin/stats/clients?days=7")).json()
    assert body["total"] == 2
    assert body["new_in_period"] == 2
    assert body["paying_in_period"] == 1
    assert body["series"][-1]["count"] == 2


async def test_economics_counts_live_paid_subscriptions_only(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
) -> None:
    now = utcnow()
    monthly, yearly, expired, trial = (
        await make_client(),
        await make_client(),
        await make_client(),
        await make_client(),
    )
    await make_subscription(monthly, days=30, now=now)  # 19900 за 30 дней → 19900/мес
    await make_subscription(yearly, days=60, now=now)  # 19900 за 60 дней → 9950/мес
    dead = await make_subscription(expired, days=30, now=now)
    dead.status = "expired"
    tr = await make_subscription(trial, days=3, now=now)
    tr.plan_is_trial = True
    await session.flush()

    body = (await admin_client.get("/admin/stats/economics")).json()
    assert body["active_paid"] == 2
    assert body["mrr"] == {"RUB": 29850}
    assert body["arpu"] == {"RUB": 14925}
