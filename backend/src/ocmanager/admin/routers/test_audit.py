from datetime import UTC, datetime

import pytest
from conftest import ADMIN_PASSWORD
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor


async def seed(session: AsyncSession) -> None:
    """Пять записей с известными временами: 1-е .. 5-е октября 2026."""
    rows = [
        (Actor("admin", "1", "203.0.113.5"), "client.block", "client", "10"),
        (Actor("admin", "1", "203.0.113.5"), "device.revoke", "device", "20"),
        (Actor.system(), "subscription.expire", "client", "10"),
        (Actor("client", "10"), "device.issue", "device", "21"),
        (Actor.system(), "reconcile.crl_missing", "node", "1"),
    ]
    for actor, action, target_type, target_id in rows:
        await audit.record(session, actor, action, target_type=target_type, target_id=target_id)
    await session.flush()
    ids = [
        r
        for r in (
            await session.execute(
                AuditLog.__table__.select().where(AuditLog.action.in_([a for _, a, _, _ in rows]))
            )
        )
    ]
    for day, row in enumerate(sorted(ids, key=lambda r: r.id), start=1):
        await session.execute(
            update(AuditLog)
            .where(AuditLog.id == row.id)
            .values(created_at=datetime(2026, 10, day, 12, tzinfo=UTC))
        )


async def actions(admin_client: AsyncClient, **params: str | int) -> list[str]:
    r = await admin_client.get("/admin/audit", params=params)
    assert r.status_code == 200, r.text
    return [row["action"] for row in r.json()["items"] if row["created_at"].startswith("2026-10")]


async def test_a_session_is_required(anon_client: AsyncClient) -> None:
    assert (await anon_client.get("/admin/audit")).status_code == 401


async def test_newest_first_and_the_ip_is_text(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    await seed(session)
    r = await admin_client.get("/admin/audit?limit=200")
    stamps = [row["created_at"] for row in r.json()["items"]]
    assert stamps == sorted(stamps, reverse=True)
    blocks = [row for row in r.json()["items"] if row["action"] == "client.block"]
    assert blocks[0]["ip"] == "203.0.113.5"
    assert blocks[0]["details"] == {}


async def test_filters_combine_with_and(admin_client: AsyncClient, session: AsyncSession) -> None:
    await seed(session)
    assert await actions(admin_client, actor_type="system") == [
        "reconcile.crl_missing",
        "subscription.expire",
    ]
    assert await actions(admin_client, target_type="client", target_id="10") == [
        "subscription.expire",
        "client.block",
    ]
    assert await actions(admin_client, actor_type="admin", target_type="client") == ["client.block"]
    assert await actions(admin_client, action="device.issue") == ["device.issue"]
    assert await actions(admin_client, actor_type="client", target_type="node") == []


async def test_the_period_is_half_open(admin_client: AsyncClient, session: AsyncSession) -> None:
    await seed(session)
    got = await actions(admin_client, since="2026-10-02T12:00:00Z", until="2026-10-04T12:00:00Z")
    assert got == ["subscription.expire", "device.revoke"]  # since включительно, until — нет
    offset = await actions(admin_client, since="2026-10-02T15:00:00+03:00")
    assert offset[-1] == "device.revoke"  # часовой пояс учитывается


@pytest.mark.parametrize("value", ["2026-10-02T12:00:00", "2026-10-02", "yesterday", "9" * 40])
async def test_a_time_without_a_zone_or_garbage_is_422_not_500(
    admin_client: AsyncClient, value: str
) -> None:
    for name in ("since", "until"):
        r = await admin_client.get("/admin/audit", params={name: value})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")


async def test_pagination_and_bad_filters(admin_client: AsyncClient, session: AsyncSession) -> None:
    await seed(session)
    page = (await admin_client.get("/admin/audit?limit=2&offset=1")).json()
    assert len(page["items"]) == 2
    assert page["total"] >= 6  # пять посеянных и создание админа
    assert (await admin_client.get("/admin/audit?actor_type=robot")).status_code == 422
    assert (await admin_client.get("/admin/audit?action=" + "x" * 65)).status_code == 422
    assert (await admin_client.get("/admin/audit?limit=201")).status_code == 422


async def test_the_admins_own_actions_show_up_with_their_ip(
    admin_client: AsyncClient,
) -> None:
    await admin_client.post("/admin/auth/logout")
    r = await admin_client.post(
        "/admin/auth/login", json={"username": "alice", "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 200
    admin_client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    rows = (await admin_client.get("/admin/audit?action=admin.login")).json()["items"]
    assert rows
    assert all(row["actor_type"] == "admin" and row["ip"] == "127.0.0.1" for row in rows)
