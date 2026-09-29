import json
from datetime import timedelta
from pathlib import Path

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakeDevice, MakePlan, MakeSubscription
from cryptography.hazmat.primitives.serialization import pkcs12
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events.models import EventOutbox
from ocmanager.nodes import registry, service
from ocmanager.nodes.models import SessionLog, TrafficDaily, TrafficSample

ANON_ENDPOINTS = [
    ("GET", "/admin/clients"),
    ("GET", "/admin/clients/1"),
    ("POST", "/admin/clients/1/block"),
    ("POST", "/admin/clients/1/unblock"),
    ("POST", "/admin/clients/1/grant"),
    ("POST", "/admin/clients/1/extend"),
    ("POST", "/admin/clients/1/devices"),
    ("GET", "/admin/downloads/0123456789abcdef0123"),
]


@pytest.mark.parametrize(("method", "path"), ANON_ENDPOINTS)
async def test_every_endpoint_needs_a_session(
    anon_client: AsyncClient, method: str, path: str
) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


@pytest.mark.parametrize(("method", "path"), [e for e in ANON_ENDPOINTS if e[0] == "POST"])
async def test_every_post_needs_the_csrf_token(
    admin_client: AsyncClient, method: str, path: str
) -> None:
    del admin_client.headers["X-CSRF-Token"]
    r = await admin_client.request(method, path, json={})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "csrf_failed")


async def ids(admin_client: AsyncClient, **params: str | int) -> list[int]:
    r = await admin_client.get("/admin/clients", params=params)
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()["items"]]


async def test_search_by_telegram_id_and_by_part_of_the_name(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    anna = await make_client(telegram_id=111, first_name="Anna", username="anna_k")
    boris = await make_client(telegram_id=222, first_name="Boris", username="boris_b")
    assert await ids(admin_client, q="111") == [anna.id]  # telegram_id — точно
    assert await ids(admin_client, q="11") == []  # …а не подстрока
    assert await ids(admin_client, q="nna") == [anna.id]
    assert await ids(admin_client, q="ANNA") == [anna.id]
    assert await ids(admin_client, q="@boris_b") == [boris.id]
    assert await ids(admin_client, q="   ") == [boris.id, anna.id]  # пустой запрос — все


async def test_like_wildcards_in_the_search_are_literal(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    await make_client(first_name="Plain")
    percent = await make_client(first_name="100% real")
    under = await make_client(first_name="snake_case")
    assert await ids(admin_client, q="%") == [percent.id]
    assert await ids(admin_client, q="_") == [under.id]
    assert await ids(admin_client, q="\\") == []


async def test_a_huge_number_in_the_search_is_not_a_server_error(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    await make_client()
    assert await ids(admin_client, q="9" * 40) == []
    assert await ids(admin_client, q="9" * 19) == []


async def test_status_and_blocked_filters(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    paid = await make_client()
    await make_subscription(paid, now=utcnow())
    bare = await make_client()
    banned = await make_client()
    await admin_client.post(f"/admin/clients/{banned.id}/block")
    assert await ids(admin_client, status="active") == [paid.id]
    assert await ids(admin_client, status="none") == [banned.id, bare.id]
    assert await ids(admin_client, blocked="true") == [banned.id]
    assert await ids(admin_client, blocked="false") == [bare.id, paid.id]
    assert (await admin_client.get("/admin/clients?status=bogus")).status_code == 422


async def test_pagination_reports_the_total_and_orders_newest_first(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    created = [(await make_client()).id for _ in range(5)]
    r = await admin_client.get("/admin/clients?limit=2&offset=2")
    body = r.json()
    assert (body["total"], body["limit"], body["offset"]) == (5, 2, 2)
    assert [row["id"] for row in body["items"]] == [created[2], created[1]]
    assert await ids(admin_client, limit=200) == created[::-1]


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=x"])
async def test_bad_pagination_is_422(admin_client: AsyncClient, query: str) -> None:
    assert (await admin_client.get(f"/admin/clients?{query}")).status_code == 422


async def test_list_rows_carry_subscription_and_device_counts(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client(first_name="Anna")
    sub = await make_subscription(client, now=utcnow())
    await make_device(client, seq=1)
    await make_device(client, seq=2, revoked=True)
    row = (await admin_client.get("/admin/clients")).json()["items"][0]
    assert row["first_name"] == "Anna"
    assert (row["subscription_status"], row["devices_active"]) == ("active", 1)
    assert row["plan_code"].startswith("plan")
    assert row["expires_at"].startswith(sub.expires_at.strftime("%Y-%m-%dT%H:%M"))


@pytest.mark.parametrize("client_id", ["0", "-1", "abc", "9" * 30])
async def test_a_bad_client_id_is_422_and_a_missing_one_is_404(
    admin_client: AsyncClient, client_id: str
) -> None:
    assert (await admin_client.get(f"/admin/clients/{client_id}")).status_code == 422
    assert (await admin_client.get("/admin/clients/424242")).status_code == 404
    r = await admin_client.post("/admin/clients/424242/block")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


async def test_the_card_puts_everything_about_a_client_in_one_place(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: ArqRedis,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    now = utcnow()
    client = await make_client(telegram_id=777, first_name="Anna")
    sub = await make_subscription(client, now=now)
    live = await make_device(client, seq=1)
    dead = await make_device(client, seq=2, revoked=True)
    node = await registry.ensure_local_node(session, settings)
    await redis.set(service.online_key(node.id), json.dumps([live.ocserv_username]))

    session.add_all(
        [
            TrafficSample(
                node_id=node.id,
                username=live.ocserv_username,
                ts=now + timedelta(minutes=1),
                bytes_in_delta=100,
                bytes_out_delta=250,
                duration_sec=60,
            ),
            TrafficDaily(
                username=live.ocserv_username,
                node_id=node.id,
                day=now.date(),
                bytes_in=100,
                bytes_out=250,
            ),
            TrafficDaily(
                username=dead.ocserv_username,
                node_id=node.id,
                day=now.date(),
                bytes_in=1,
                bytes_out=2,
            ),
            TrafficDaily(  # старше 30 дней — в карточку не попадает
                username=live.ocserv_username,
                node_id=node.id,
                day=(now - timedelta(days=45)).date(),
                bytes_in=9,
                bytes_out=9,
            ),
        ]
    )
    await session.flush()

    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["client"]["telegram_id"] == 777
    assert card["subscription"]["status"] == "active"
    assert card["subscription"]["devices_active"] == 1
    assert card["subscription"]["over_device_limit"] is False
    assert card["subscription"]["expires_at"].startswith(sub.expires_at.strftime("%Y-%m-%dT%H:%M"))
    by_name = {d["username"]: d for d in card["devices"]}
    assert set(by_name) == {live.ocserv_username, dead.ocserv_username}  # отозванное тоже
    assert by_name[live.ocserv_username]["is_online"] is True
    assert by_name[dead.ocserv_username]["is_online"] is False
    assert by_name[live.ocserv_username]["traffic_bytes"] == 350
    assert by_name[dead.ocserv_username]["revoked_at"] is not None
    assert card["traffic_daily"] == [
        {"day": now.date().isoformat(), "bytes_in": 101, "bytes_out": 252}
    ]
    assert card["payments"] == []


async def test_online_is_unknown_when_the_node_cache_is_empty(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, now=utcnow())
    await make_device(client)
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["devices"][0]["is_online"] is None  # «не знаем», а не «не подключён»


async def test_card_shows_the_last_50_sessions_and_never_a_negative_duration(
    admin_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    now = utcnow()
    client = await make_client()
    device = await make_device(client)
    node = await registry.ensure_local_node(session, settings)
    for n in range(55):
        started = now - timedelta(hours=n + 1)
        session.add(
            SessionLog(
                node_id=node.id,
                username=device.ocserv_username,
                ocserv_session_id=str(n),
                started_at=started,
                ended_at=started + timedelta(minutes=10),
                client_ip="203.0.113.7",
                vpn_ip="10.77.0.2",
                bytes_in=n,
                bytes_out=2 * n,
                last_polled_at=started,
                final_received=True,
            )
        )
    session.add(  # часы ноды опережают наши: начало «в будущем»
        SessionLog(
            node_id=node.id,
            username=device.ocserv_username,
            ocserv_session_id="future",
            started_at=now + timedelta(hours=1),
            client_ip="203.0.113.7",
            bytes_in=0,
            bytes_out=0,
            last_polled_at=now,
        )
    )
    await session.flush()
    rows = (await admin_client.get(f"/admin/clients/{client.id}")).json()["sessions"]
    assert len(rows) == 50
    assert rows[0]["duration_sec"] == 0  # самая новая — «из будущего»
    assert rows[1]["duration_sec"] == 600
    stamps = [r["started_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)


async def test_over_the_device_limit_is_visible(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
    session: AsyncSession,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, now=utcnow())
    sub.device_limit = 1
    await session.flush()
    await make_device(client, seq=1)
    await make_device(client, seq=2)
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["subscription"]["over_device_limit"] is True


async def test_block_is_visible_events_audit_and_wakes_the_worker(
    admin_client: AsyncClient,
    session: AsyncSession,
    redis: ArqRedis,
    make_client: MakeClient,
) -> None:
    client = await make_client()
    r = await admin_client.post(f"/admin/clients/{client.id}/block")
    assert (r.status_code, r.json()) == (200, {"changed": True})
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["client"]["is_blocked"] is True
    assert "client.blocked" in list(await session.scalars(select(EventOutbox.name)))
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "client.block"))
    assert audit is not None
    assert audit.actor_type == "admin"
    assert audit.actor_id is not None
    assert str(audit.ip) == "127.0.0.1"
    assert audit.target_id == str(client.id)
    assert b"dispatch_events:kick" in await redis.zrange("arq:queue", 0, -1)


async def test_repeated_block_changes_nothing_and_unblock_reverts(
    admin_client: AsyncClient, session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    await admin_client.post(f"/admin/clients/{client.id}/block")
    again = await admin_client.post(f"/admin/clients/{client.id}/block")
    assert again.json() == {"changed": False}
    blocks = await session.scalars(select(AuditLog).where(AuditLog.action == "client.block"))
    assert len(list(blocks)) == 1
    assert (await admin_client.post(f"/admin/clients/{client.id}/unblock")).json() == {
        "changed": True
    }
    card = (await admin_client.get(f"/admin/clients/{client.id}")).json()
    assert card["client"]["is_blocked"] is False


async def test_grant_without_a_subscription_makes_it_active(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1", duration_days=30)
    r = await admin_client.post(f"/admin/clients/{client.id}/grant", json={"plan_code": "m1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["plan_code"], body["auto_renew"]) == ("active", "m1", False)


async def test_grant_with_days_replaces_the_plan_duration(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1", duration_days=30)
    r = await admin_client.post(
        f"/admin/clients/{client.id}/grant", json={"plan_code": "m1", "days": 2}
    )
    assert r.status_code == 200
    expected = (utcnow() + timedelta(days=2)).date().isoformat()
    assert r.json()["expires_at"][:10] == expected


@pytest.mark.parametrize("days", [0, -1, 3651, 999_999_999])
async def test_absurd_days_are_422_not_500(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan, days: int
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    r = await admin_client.post(
        f"/admin/clients/{client.id}/grant", json={"plan_code": "m1", "days": days}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")
    r = await admin_client.post(f"/admin/clients/{client.id}/extend", json={"days": days})
    assert r.status_code == 422


async def test_grant_refuses_unknown_and_trial_plans_and_blocked_clients(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_plan: MakePlan,
    trial_plan: object,
) -> None:
    client = await make_client()
    await make_plan(code="m1")
    grant = f"/admin/clients/{client.id}/grant"
    assert (await admin_client.post(grant, json={"plan_code": "nope"})).status_code == 404
    assert (await admin_client.post(grant, json={"plan_code": "trial"})).status_code == 422
    await admin_client.post(f"/admin/clients/{client.id}/block")
    r = await admin_client.post(grant, json={"plan_code": "m1"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "subscription_inactive")
    assert (await admin_client.post(grant, json={"plan_code": "m1", "x": 1})).status_code == 422


async def test_extend_adds_days_and_needs_a_subscription(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan
) -> None:
    client = await make_client()
    await make_plan(code="m1", duration_days=30)
    r = await admin_client.post(f"/admin/clients/{client.id}/extend", json={"days": 5})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "invalid_transition")
    await admin_client.post(f"/admin/clients/{client.id}/grant", json={"plan_code": "m1"})
    r = await admin_client.post(f"/admin/clients/{client.id}/extend", json={"days": 5})
    assert r.status_code == 200
    expected = (utcnow() + timedelta(days=35)).date().isoformat()
    assert r.json()["expires_at"][:10] == expected


async def grant_and_issue(
    admin_client: AsyncClient,
    make_client: MakeClient,
    make_plan: MakePlan,
    *,
    limit: int = 2,
) -> tuple[int, str]:
    client = await make_client()
    await make_plan(code="m1", device_limit=limit)
    await admin_client.post(f"/admin/clients/{client.id}/grant", json={"plan_code": "m1"})
    return client.id, f"/admin/clients/{client.id}/devices"


async def test_issuing_a_device_without_access_is_refused(
    admin_client: AsyncClient, make_client: MakeClient
) -> None:
    client = await make_client()
    r = await admin_client.post(
        f"/admin/clients/{client.id}/devices", json={"name": "Phone", "platform": "ios"}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (409, "subscription_inactive")


async def test_issue_then_download_the_p12_exactly_once(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_plan: MakePlan,
) -> None:
    client_id, url = await grant_and_issue(admin_client, make_client, make_plan)
    r = await admin_client.post(url, json={"name": "Phone", "platform": "ios"})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["device"]["username"] == f"c{client_id}-d1"
    assert body["download_path"].startswith("/admin/downloads/")

    got = await admin_client.get(body["download_path"])
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/x-pkcs12"
    assert got.headers["cache-control"] == "no-store"
    assert f'filename="c{client_id}-d1.p12"' in got.headers["content-disposition"]
    key, cert, _ = pkcs12.load_key_and_certificates(got.content, body["p12_password"].encode())
    assert key is not None
    assert cert is not None
    again = await admin_client.get(body["download_path"])
    assert (again.status_code, again.json()["error"]["code"]) == (404, "not_found")

    rows = list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))
    actions = [r.action for r in rows]
    assert "device.issue" in actions
    assert "device.download" in actions
    everything = json.dumps([r.details for r in rows])
    assert body["p12_password"] not in everything
    assert body["download_path"].rsplit("/", 1)[1] not in everything


async def test_the_device_limit_holds_for_the_admin_too(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan
) -> None:
    _, url = await grant_and_issue(admin_client, make_client, make_plan, limit=1)
    assert (await admin_client.post(url, json={"name": "A", "platform": "ios"})).status_code == 200
    r = await admin_client.post(url, json={"name": "B", "platform": "ios"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "device_limit_reached")


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Phone", "platform": "beos"},
        {"name": "", "platform": "ios"},
        {"name": "x" * 201, "platform": "ios"},
        {"name": "bad\u0000name", "platform": "ios"},
        {"name": "bad\nname", "platform": "ios"},
        {"name": "Phone"},
    ],
)
async def test_bad_device_input_is_422(
    admin_client: AsyncClient, make_client: MakeClient, make_plan: MakePlan, body: dict[str, str]
) -> None:
    _, url = await grant_and_issue(admin_client, make_client, make_plan)
    assert (await admin_client.post(url, json=body)).status_code == 422


@pytest.mark.parametrize("token", ["short", "x" * 129])
async def test_a_malformed_download_token_is_422(admin_client: AsyncClient, token: str) -> None:
    assert (await admin_client.get(f"/admin/downloads/{token}")).status_code == 422


async def test_a_missing_ca_is_503_not_500(
    admin_client: AsyncClient,
    admin_app: FastAPI,
    settings: Settings,
    make_client: MakeClient,
    make_plan: MakePlan,
    tmp_path: Path,
) -> None:
    _, url = await grant_and_issue(admin_client, make_client, make_plan)
    admin_app.state.ca = None
    admin_app.state.settings = settings.model_copy(update={"pki_dir": tmp_path / "nowhere"})
    r = await admin_client.post(url, json={"name": "Phone", "platform": "ios"})
    assert (r.status_code, r.json()["error"]["code"]) == (503, "pki_not_ready")
