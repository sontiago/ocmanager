import json
from datetime import timedelta

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakePayment, MakeSubscription, MakeWebhook
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.nodes import registry, service
from ocmanager.nodes.models import TrafficDaily
from ocmanager.nodes.service import NodeHealth


async def test_a_session_is_required(anon_client: AsyncClient) -> None:
    assert (await anon_client.get("/admin/overview")).status_code == 401


async def test_an_empty_system_gives_zeros_not_errors(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/admin/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["node"] is None
    assert body["health"] is None
    assert body["active_sessions"] is None
    assert (body["traffic"]["bytes_in"], body["traffic"]["bytes_out"]) == (0, 0)
    assert body["expiring_soon"] == 0
    assert body["last_reconcile"] is None
    assert body["revenue"] == {}
    assert body["recent_payments"] == []
    assert body["webhooks_needing_attention"] == 0
    assert body["subscriptions_by_status"] == {
        "pending_payment": 0,
        "trial": 0,
        "active": 0,
        "expired": 0,
        "exhausted": 0,
        "cancelled": 0,
        "blocked": 0,
    }


async def test_the_overview_adds_everything_up(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: ArqRedis,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    now = utcnow()
    soon, later, ended = await make_client(), await make_client(), await make_client()
    await make_subscription(soon, days=2, now=now)
    await make_subscription(later, days=30, now=now)
    dead = await make_subscription(ended, days=1, now=now)
    dead.status = "expired"

    node = await registry.ensure_local_node(session, settings)
    node.last_reconcile_report = {"drifts": [{"kind": "crl_missing", "details": {}}], "error": None}
    health = NodeHealth(node.id, "online", "running", 4, now, None)
    await redis.set(service.health_key(node.id), health.to_json())
    for age, rx, tx in [(0, 100, 200), (1, 10, 20), (2, 1000, 2000)]:
        session.add(
            TrafficDaily(
                username="c1-d1",
                node_id=node.id,
                day=(now - timedelta(days=age)).date(),
                bytes_in=rx,
                bytes_out=tx,
            )
        )
    await session.flush()

    body = (await admin_client.get("/admin/overview")).json()
    assert body["node"]["name"] == "local"
    assert (body["health"]["state"], body["active_sessions"]) == ("online", 4)
    assert body["subscriptions_by_status"]["active"] == 2
    assert body["subscriptions_by_status"]["expired"] == 1
    assert body["expiring_soon"] == 1  # только «soon»: живая и в окне
    traffic = body["traffic"]
    assert (traffic["bytes_in"], traffic["bytes_out"]) == (110, 220)  # без позавчера
    assert body["last_reconcile"]["drifts"][0]["kind"] == "crl_missing"


async def test_recent_audit_is_the_newest_twenty(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    for n in range(25):
        await audit.record(
            session, Actor.system(), "test.event", target_type="thing", target_id=str(n)
        )
    await session.flush()
    rows = (await admin_client.get("/admin/overview")).json()["recent_audit"]
    assert len(rows) == 20
    assert [r["target_id"] for r in rows[:3]] == ["24", "23", "22"]


@pytest.mark.parametrize("path", ["/admin/overview", "/admin/audit", "/admin/settings"])
async def test_nothing_secret_leaks_through_the_read_endpoints(
    admin_client: AsyncClient, settings: Settings, path: str
) -> None:
    text = (await admin_client.get(path)).text
    for secret in (
        settings.secret_key.get_secret_value(),
        settings.internal_token.get_secret_value(),
        "ocm:ocm@",  # пароль из адреса БД
    ):
        assert secret not in text


async def test_the_body_is_json(admin_client: AsyncClient) -> None:
    assert json.loads((await admin_client.get("/admin/overview")).text)


async def test_revenue_is_summed_per_currency_over_thirty_days(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_payment: MakePayment,
    make_webhook: MakeWebhook,
) -> None:
    client = await make_client()
    await make_payment(client, amount=19900, currency="RUB")
    await make_payment(client, amount=10000, currency="RUB")
    await make_payment(client, amount=500, currency="USD")
    await make_payment(client, amount=99999, currency="RUB", status="refunded")
    await make_payment(
        client, amount=7777, currency="RUB", received_at=utcnow() - timedelta(days=31)
    )
    await make_webhook(status="dead")
    await make_webhook(status="failed")
    await make_webhook(status="processed")

    body = (await admin_client.get("/admin/overview")).json()
    assert body["revenue"] == {"RUB": 29900, "USD": 500}  # возврат и старый платёж не считаются
    assert [p["amount"] for p in body["recent_payments"]] == [99999, 500, 10000, 19900, 7777]
    assert body["webhooks_needing_attention"] == 2
