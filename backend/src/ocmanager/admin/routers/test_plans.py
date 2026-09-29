from typing import Any

import pytest
from conftest import MakeClient, MakePlan, MakeSubscription
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.billing import plans as plan_service
from ocmanager.billing.models import Plan
from ocmanager.core.clock import utcnow
from ocmanager.subscriptions.models import Subscription

NEW: dict[str, Any] = {
    "code": "m1",
    "name_i18n": {"ru": "Месяц", "en": "Month"},
    "duration_days": 30,
    "device_limit": 2,
    "price_amount": 19900,
    "currency": "rub",
}


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/admin/plans"), ("POST", "/admin/plans"), ("PATCH", "/admin/plans/m1")],
)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


async def test_the_list_includes_inactive_and_trial_plans(
    admin_client: AsyncClient, make_plan: MakePlan, trial_plan: Plan
) -> None:
    await make_plan(code="on")
    await make_plan(code="off", is_active=False)
    codes = {p["code"]: p for p in (await admin_client.get("/admin/plans")).json()}
    assert {"on", "off", "trial"} <= set(codes)
    assert codes["off"]["is_active"] is False
    assert codes["trial"]["is_trial"] is True


async def test_create_normalises_and_audits(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    r = await admin_client.post("/admin/plans", json=NEW)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["code"], body["currency"], body["is_trial"]) == ("m1", "RUB", False)
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "plan.create"))
    assert row is not None
    assert row.details == {"code": "m1"}
    assert row.actor_type == "admin"


async def test_a_duplicate_code_is_409(admin_client: AsyncClient) -> None:
    assert (await admin_client.post("/admin/plans", json=NEW)).status_code == 201
    r = await admin_client.post("/admin/plans", json=NEW)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "conflict")


@pytest.mark.parametrize(
    "bad",
    [
        {"currency": "RUBLES"},
        {"currency": "12"},
        {"name_i18n": {"ru": "Месяц"}},
        {"price_amount": -1},
        {"price_amount": 10**13},
        {"duration_days": 3651},
        {"duration_days": 0},
        {"device_limit": 1001},
        {"code": "Bad Code"},
        {"is_trial": True},
    ],
)
async def test_invalid_plans_are_422(admin_client: AsyncClient, bad: dict[str, Any]) -> None:
    r = await admin_client.post("/admin/plans", json={**NEW, **bad})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")


async def test_patch_changes_only_what_was_sent(
    admin_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    await make_plan(code="m1", price_amount=100, device_limit=3)
    r = await admin_client.patch("/admin/plans/m1", json={"price_amount": 250})
    assert r.status_code == 200
    body = r.json()
    assert (body["price_amount"], body["device_limit"]) == (250, 3)
    again = await admin_client.patch("/admin/plans/m1", json={"price_amount": 250})
    assert again.status_code == 200
    updates = await session.scalars(select(AuditLog).where(AuditLog.action == "plan.update"))
    rows = list(updates)
    assert len(rows) == 1  # повтор ничего не изменил — аудита нет
    assert rows[0].details == {"code": "m1", "changed": {"price_amount": [100, 250]}}


async def test_patch_may_clear_the_traffic_cap_but_not_the_price(
    admin_client: AsyncClient, make_plan: MakePlan
) -> None:
    await make_plan(code="m1", traffic_limit_bytes=10**9)
    ok = await admin_client.patch("/admin/plans/m1", json={"traffic_limit_bytes": None})
    assert ok.json()["traffic_limit_bytes"] is None
    bad = await admin_client.patch("/admin/plans/m1", json={"price_amount": None})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "body", [{}, {"is_trial": False}, {"code": "other"}, {"name_i18n": {"ru": "Только ру"}}]
)
async def test_bad_patches_are_422(
    admin_client: AsyncClient, make_plan: MakePlan, body: dict[str, Any]
) -> None:
    await make_plan(code="m1")
    assert (await admin_client.patch("/admin/plans/m1", json=body)).status_code == 422


async def test_patch_of_an_unknown_plan_is_404(admin_client: AsyncClient) -> None:
    r = await admin_client.patch("/admin/plans/ghost", json={"sort_order": 1})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


async def test_the_trial_plan_can_be_renamed_but_stays_a_trial(
    admin_client: AsyncClient, trial_plan: Plan
) -> None:
    r = await admin_client.patch(
        "/admin/plans/trial", json={"name_i18n": {"ru": "Проба", "en": "Try"}}
    )
    assert r.status_code == 200
    assert (r.json()["name_i18n"]["ru"], r.json()["is_trial"]) == ("Проба", True)


async def test_deactivating_hides_the_plan_but_keeps_subscriptions(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, now=utcnow())
    plan = await session.get(Plan, sub.plan_id)
    assert plan is not None
    assert plan.code in [p.code for p in await plan_service.list_catalog(session)]

    r = await admin_client.patch(f"/admin/plans/{plan.code}", json={"is_active": False})
    assert r.status_code == 200
    assert plan.code not in [p.code for p in await plan_service.list_catalog(session)]
    stored = await session.scalar(select(Subscription))
    assert stored is not None
    await session.refresh(stored)
    assert stored.status == "active"


async def test_editing_a_plan_does_not_change_purchased_terms(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, now=utcnow())
    plan = await session.get(Plan, sub.plan_id)
    assert plan is not None
    before = sub.device_limit
    await admin_client.patch(f"/admin/plans/{plan.code}", json={"device_limit": before + 5})
    await session.refresh(sub)
    assert sub.device_limit == before
