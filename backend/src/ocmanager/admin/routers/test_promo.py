from datetime import timedelta

import pytest
from conftest import MakeClient, MakePlan
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.billing import promo
from ocmanager.core.clock import utcnow
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.state import PlanTerms

GIB = 1024**3
ENDPOINTS = [
    ("GET", "/admin/promo-codes"),
    ("POST", "/admin/promo-codes"),
    ("PATCH", "/admin/promo-codes/1"),
    ("GET", "/admin/promo-codes/1/redemptions"),
    ("DELETE", "/admin/promo-codes/1"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


async def test_create_a_days_code_and_list_it(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    r = await admin_client.post(
        "/admin/promo-codes", json={"code": "Spring14", "kind": "days", "value": 14, "max_uses": 5}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["code"], body["kind"], body["value"], body["max_uses"], body["uses"]) == (
        "spring14",
        "days",
        14,
        5,
        0,
    )
    assert body["is_active"] is True
    listing = (await admin_client.get("/admin/promo-codes")).json()
    assert [c["code"] for c in listing] == ["spring14"]
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "promo.create"))
    assert audit is not None
    assert audit.actor_type == "admin"
    assert audit.details["code"] == "spring14"


async def test_a_traffic_code_is_entered_and_shown_in_gib(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    r = await admin_client.post(
        "/admin/promo-codes", json={"code": "gb50", "kind": "traffic", "value": 50}
    )
    assert r.json()["value"] == 50
    stored = (await promo.list_all(session))[0]
    assert stored.value == 50 * GIB


async def test_duplicates_and_bad_input_are_rejected(admin_client: AsyncClient) -> None:
    ok = {"code": "dup", "kind": "days", "value": 1}
    assert (await admin_client.post("/admin/promo-codes", json=ok)).status_code == 201
    assert (await admin_client.post("/admin/promo-codes", json=ok)).status_code == 409
    for bad in (
        {"code": "x", "kind": "days", "value": 1},
        {"code": "okcode", "kind": "gold", "value": 1},
        {"code": "okcode", "kind": "days", "value": 0},
        {"code": "okcode", "kind": "days", "value": 1, "max_uses": 0},
        {"code": "okcode", "kind": "days", "value": 1, "unknown": True},
    ):
        assert (await admin_client.post("/admin/promo-codes", json=bad)).status_code == 422, bad


async def test_patch_switches_a_code_off_and_changes_limits(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    created = (
        await admin_client.post(
            "/admin/promo-codes", json={"code": "tweak", "kind": "days", "value": 3, "max_uses": 2}
        )
    ).json()
    url = f"/admin/promo-codes/{created['id']}"

    r = await admin_client.patch(url, json={"is_active": False})
    assert (r.status_code, r.json()["is_active"], r.json()["max_uses"]) == (200, False, 2)

    r = await admin_client.patch(url, json={"max_uses": None})
    assert r.json()["max_uses"] is None

    expires = (utcnow() + timedelta(days=3)).isoformat()
    r = await admin_client.patch(url, json={"expires_at": expires})
    assert r.json()["expires_at"] is not None

    audit = list(
        await session.scalars(select(AuditLog.action).where(AuditLog.action == "promo.update"))
    )
    assert len(audit) == 3


async def test_patch_of_an_unknown_code_is_404_and_empty_body_changes_nothing(
    admin_client: AsyncClient,
) -> None:
    assert (await admin_client.patch("/admin/promo-codes/999", json={})).status_code == 404
    created = (
        await admin_client.post(
            "/admin/promo-codes", json={"code": "same", "kind": "days", "value": 1}
        )
    ).json()
    r = await admin_client.patch(f"/admin/promo-codes/{created['id']}", json={})
    assert r.status_code == 200
    assert r.json()["is_active"] is True


async def test_redemptions_show_who_used_the_code(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
) -> None:
    client = await make_client(first_name="Anna", username="anna")
    plan = await make_plan()
    await subscriptions.activate(
        session,
        client.id,
        PlanTerms(plan.id, 30, plan.device_limit, plan.traffic_limit_bytes, False),
        utcnow(),
        auto_renew=True,
    )
    code = await promo.create(session, code="used", kind="days", value=2)
    await promo.claim(session, client.id, "used", utcnow())

    rows = (await admin_client.get(f"/admin/promo-codes/{code.id}/redemptions")).json()
    assert [(r["client_id"], r["client_name"], r["kind"], r["value"]) for r in rows] == [
        (client.id, "Anna", "days", 2)
    ]
    assert (await admin_client.get("/admin/promo-codes")).json()[0]["uses"] == 1


async def test_an_unused_code_can_be_deleted_with_audit(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    created = (
        await admin_client.post(
            "/admin/promo-codes", json={"code": "oops", "kind": "days", "value": 3}
        )
    ).json()
    r = await admin_client.delete(f"/admin/promo-codes/{created['id']}")
    assert r.status_code == 204
    assert (await admin_client.get("/admin/promo-codes")).json() == []
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "promo.delete"))
    assert audit is not None
    assert audit.details["code"] == "oops"


async def test_a_used_code_cannot_be_deleted_only_switched_off(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
) -> None:
    client = await make_client()
    plan = await make_plan()
    await subscriptions.activate(
        session,
        client.id,
        PlanTerms(plan.id, 30, plan.device_limit, plan.traffic_limit_bytes, False),
        utcnow(),
        auto_renew=True,
    )
    code = await promo.create(session, code="used", kind="days", value=2)
    await promo.claim(session, client.id, "used", utcnow())

    r = await admin_client.delete(f"/admin/promo-codes/{code.id}")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "conflict")
    assert len((await admin_client.get("/admin/promo-codes")).json()) == 1  # код цел, история цела


async def test_deleting_an_unknown_code_is_404(admin_client: AsyncClient) -> None:
    assert (await admin_client.delete("/admin/promo-codes/999")).status_code == 404
