from datetime import timedelta
from typing import Any

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakePayment, MakePlan, MakeWebhook
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps.worker import process_webhook
from ocmanager.audit.models import AuditLog
from ocmanager.billing import webhooks
from ocmanager.billing.providers import build_providers
from ocmanager.billing.testing import webhook_body
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.subscriptions import service as subscriptions


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/payments"),
        ("GET", "/admin/webhooks"),
        ("GET", "/admin/webhooks/1"),
        ("POST", "/admin/webhooks/1/reprocess"),
    ],
)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


# --- платежи ----------------------------------------------------------------------------


async def test_payments_come_newest_first_and_filter_by_client_status_and_time(
    admin_client: AsyncClient, make_client: MakeClient, make_payment: MakePayment
) -> None:
    anna, boris = await make_client(), await make_client()
    old = await make_payment(anna, received_at=utcnow() - timedelta(days=10))
    refunded = await make_payment(boris, status="refunded")
    new = await make_payment(anna, amount=500, currency="USD")

    everything = (await admin_client.get("/admin/payments")).json()
    assert ids(everything) == [new.id, refunded.id, old.id]
    assert (everything["total"], everything["limit"], everything["offset"]) == (3, 50, 0)
    assert set(everything["items"][0]) == {
        "id", "client_id", "subscription_id", "provider", "external_id", "plan_id",
        "amount", "currency", "status", "received_at", "processed_at",
    }  # fmt: skip
    assert everything["items"][0]["amount"] == 500

    by_client = (await admin_client.get(f"/admin/payments?client_id={anna.id}")).json()
    assert ids(by_client) == [new.id, old.id]
    by_status = (await admin_client.get("/admin/payments?status=refunded")).json()
    assert ids(by_status) == [refunded.id]
    since = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = (await admin_client.get(f"/admin/payments?since={since}")).json()
    assert ids(recent) == [new.id, refunded.id]
    page = (await admin_client.get("/admin/payments?limit=1&offset=1")).json()
    assert (ids(page), page["total"]) == ([refunded.id], 3)


async def test_a_bad_payment_filter_is_a_validation_error(admin_client: AsyncClient) -> None:
    for query in ("status=lost", "client_id=abc", "since=yesterday", "limit=0", "limit=9999"):
        r = await admin_client.get(f"/admin/payments?{query}")
        assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error"), query


# --- вебхуки ----------------------------------------------------------------------------


async def test_the_webhook_list_shows_what_needs_attention_by_default(
    admin_client: AsyncClient, make_webhook: MakeWebhook
) -> None:
    dead = await make_webhook(status="dead", last_error="no plan")
    failed = await make_webhook(status="failed", attempts=2)
    processed = await make_webhook(status="processed")
    rejected = await make_webhook(status="rejected", signature_ok=False)

    default = (await admin_client.get("/admin/webhooks")).json()
    assert ids(default) == [failed.id, dead.id]
    assert default["items"][1]["last_error"] == "no plan"
    everything = (await admin_client.get("/admin/webhooks?status=all")).json()
    assert ids(everything) == [rejected.id, processed.id, failed.id, dead.id]
    only = (await admin_client.get("/admin/webhooks?status=processed")).json()
    assert ids(only) == [processed.id]
    assert ids((await admin_client.get("/admin/webhooks?provider=nope")).json()) == []


async def test_the_webhook_detail_shows_the_payload_but_not_the_raw_bytes(
    admin_client: AsyncClient, make_webhook: MakeWebhook
) -> None:
    row = await make_webhook(status="dead", payload={"name": "new_subscription", "x": 1})
    body = (await admin_client.get(f"/admin/webhooks/{row.id}")).json()
    assert body["payload"] == {"name": "new_subscription", "x": 1}
    assert (body["status"], body["signature_ok"], body["provider"]) == ("dead", True, "tribute")
    assert "raw_body" not in body


async def test_an_unknown_webhook_is_not_found(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/admin/webhooks/999999")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    r = await admin_client.post("/admin/webhooks/999999/reprocess")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


async def test_reprocessing_requeues_a_dead_webhook_and_is_audited(
    admin_client: AsyncClient,
    session: AsyncSession,
    redis: ArqRedis,
    make_webhook: MakeWebhook,
) -> None:
    row = await make_webhook(status="dead", attempts=8, last_error="no plan")
    r = await admin_client.post(f"/admin/webhooks/{row.id}/reprocess")
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["attempts"], r.json()["last_error"]) == (
        "received",
        0,
        None,
    )
    jobs = [j.args for j in await redis.queued_jobs() if j.function == "process_webhook"]
    assert jobs == [(row.id,)]
    [entry] = list(
        await session.scalars(select(AuditLog).where(AuditLog.action == "webhook.reprocess"))
    )
    assert (entry.actor_type, entry.target_id) == ("admin", str(row.id))


@pytest.mark.parametrize("status", ["processed", "ignored", "received", "rejected"])
async def test_only_failed_and_dead_webhooks_can_be_reprocessed(
    admin_client: AsyncClient, make_webhook: MakeWebhook, status: str
) -> None:
    row = await make_webhook(status=status, signature_ok=status != "rejected")
    r = await admin_client.post(f"/admin/webhooks/{row.id}/reprocess")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "conflict")


async def test_a_dead_payment_is_fixed_by_linking_the_plan_and_reprocessing(
    admin_client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    settings: Settings,
    make_plan: MakePlan,
) -> None:
    """Весь путь оператора: оплата пришла, а тариф не привязан к продукту → dead; админ
    привязывает тариф, жмёт «переобработать» → подписка и платёж появляются в карточке клиента."""
    plan = await make_plan()  # пока без продукта Tribute
    provider = build_providers(settings)["tribute"]
    intake = await webhooks.receive(
        session, provider, webhook_body("new_subscription"), verified=True
    )
    event_id = intake.webhook_event_id
    assert event_id is not None
    ctx: dict[str, Any] = {
        "settings": settings,
        "sessionmaker": sessionmaker,
        "redis": redis,
        "job_try": 1,
    }
    assert await process_webhook(ctx, event_id) == "dead"
    dead = (await admin_client.get("/admin/webhooks")).json()
    assert ids(dead) == [event_id]

    plan.provider_product_ids = {"tribute": {"product_ref": "2001"}}
    await session.flush()
    assert (await admin_client.post(f"/admin/webhooks/{event_id}/reprocess")).status_code == 200
    assert await process_webhook(ctx, event_id) == "processed"
    assert (await admin_client.get("/admin/webhooks")).json()["items"] == []

    client = await subscriptions.find_client_by_telegram_id(session, 7001)
    assert client is not None
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["subscription"]["status"] == "active"
    [payment] = card["payments"]
    assert (payment["amount"], payment["currency"], payment["status"]) == (
        19900,
        "RUB",
        "succeeded",
    )
    assert payment["plan_id"] == plan.id


async def test_the_client_card_lists_payments_newest_first(
    admin_client: AsyncClient, make_client: MakeClient, make_payment: MakePayment
) -> None:
    client = await make_client()
    other = await make_client()
    first = await make_payment(client)
    await make_payment(other)
    second = await make_payment(client)
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert [p["id"] for p in card["payments"]] == [second.id, first.id]
