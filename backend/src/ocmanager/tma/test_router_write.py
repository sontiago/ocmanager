import json
from datetime import datetime, timedelta

import pytest
from arq import ArqRedis
from conftest import TMA_TELEGRAM_ID, MakeClient, MakeDevice, MakeSubscription, TmaHeaders
from cryptography.hazmat.primitives.serialization import pkcs12
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.billing.models import Plan
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.events.models import EventOutbox
from ocmanager.nodes import registry, service
from ocmanager.nodes.models import TrafficSample
from ocmanager.provisioning.models import Device, Revocation
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client

DEVICE = {"name": "iPhone Ивана", "platform": "ios"}


async def error(r: Response) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


async def events(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(EventOutbox.name).order_by(EventOutbox.id)))


async def me_id(session: AsyncSession) -> int:
    client = await session.scalar(select(Client).where(Client.telegram_id == TMA_TELEGRAM_ID))
    assert client is not None
    return client.id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/tma/subscription/trial"),
        ("GET", "/api/tma/devices"),
        ("POST", "/api/tma/devices"),
        ("DELETE", "/api/tma/devices/1"),
    ],
)
async def test_every_action_needs_the_init_data(
    public_client: AsyncClient, method: str, path: str
) -> None:
    r = await public_client.request(method, path)
    assert await error(r) == (401, "unauthorized")


# --- пробный период -----------------------------------------------------------


async def test_the_trial_starts_and_is_visible_everywhere(
    tma_client: AsyncClient, session: AsyncSession, trial_plan: Plan
) -> None:
    r = await tma_client.post("/api/tma/subscription/trial", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["auto_renew"], body["devices_used"]) == ("trial", False, 0)
    assert (body["device_limit"], body["plan"]["is_trial"]) == (1, True)
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert timedelta(days=2) < expires - utcnow() <= timedelta(days=3)

    again = (await tma_client.get("/api/tma/subscription")).json()["subscription"]
    assert again["id"] == body["id"]
    me = (await tma_client.get("/api/tma/me")).json()
    assert me["trial_available"] is False
    assert "subscription.activated" in await events(session)
    actions = list(await session.scalars(select(AuditLog.action)))
    assert "subscription.start_trial" in actions


async def test_the_trial_body_is_optional(tma_client: AsyncClient, trial_plan: Plan) -> None:
    assert (await tma_client.post("/api/tma/subscription/trial")).status_code == 200


async def test_a_second_trial_is_refused(tma_client: AsyncClient, trial_plan: Plan) -> None:
    assert (await tma_client.post("/api/tma/subscription/trial")).status_code == 200
    r = await tma_client.post("/api/tma/subscription/trial")
    assert await error(r) == (409, "trial_already_used")


async def test_the_trial_is_refused_to_someone_who_already_has_a_subscription(
    tma_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    trial_plan: Plan,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await make_subscription(client, now=utcnow())  # выдана из админки, trial не использован
    r = await tma_client.post("/api/tma/subscription/trial")
    assert await error(r) == (409, "trial_already_used")


async def test_a_blocked_client_cannot_start_the_trial(
    tma_client: AsyncClient, session: AsyncSession, make_client: MakeClient, trial_plan: Plan
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    r = await tma_client.post("/api/tma/subscription/trial")
    assert await error(r) == (403, "subscription_inactive")


async def test_the_trial_is_limited_to_three_attempts_an_hour(
    tma_client: AsyncClient, trial_plan: Plan
) -> None:
    codes = [(await tma_client.post("/api/tma/subscription/trial")).status_code for _ in range(4)]
    assert codes == [200, 409, 409, 429]
    r = await tma_client.post("/api/tma/subscription/trial")
    assert await error(r) == (429, "rate_limited")
    assert 0 < int(r.headers["Retry-After"]) <= 3600


# --- выпуск устройства и скачивание ------------------------------------------


async def start_trial(tma_client: AsyncClient) -> None:
    assert (await tma_client.post("/api/tma/subscription/trial")).status_code == 200


async def test_the_key_is_issued_downloaded_once_and_opens_with_the_password(
    tma_client: AsyncClient,
    public_client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    trial_plan: Plan,
) -> None:
    await start_trial(tma_client)
    r = await tma_client.post("/api/tma/devices", json=DEVICE)
    assert r.status_code == 200, r.text
    assert r.headers["Cache-Control"] == "no-store"
    body = r.json()
    device = body["device"]
    assert (device["name"], device["platform"], device["is_online"]) == (
        "iPhone Ивана",
        "ios",
        False,
    )
    assert (device["traffic_used_bytes"], device["last_seen_at"]) == (0, None)
    assert isinstance(device["id"], str)
    assert body["download_url"].startswith(f"{settings.public_base_url}/api/tma/download/")
    expires = datetime.fromisoformat(body["download_expires_at"].replace("Z", "+00:00"))
    assert timedelta(minutes=14) < expires - utcnow() <= timedelta(minutes=15)

    path = body["download_url"].removeprefix(settings.public_base_url)
    first = await public_client.get(path)  # без initData: ссылку открывает системный браузер
    assert first.status_code == 200
    assert first.headers["Content-Type"] == "application/x-pkcs12"
    assert first.headers["Cache-Control"] == "no-store"
    client_id = await me_id(session)
    assert first.headers["Content-Disposition"] == f'attachment; filename="c{client_id}-d1.p12"'
    _, cert, _ = pkcs12.load_key_and_certificates(first.content, body["p12_password"].encode())
    assert cert is not None
    assert cert.subject.rfc4514_string() == f"CN=c{client_id}-d1"

    second = await public_client.get(path)
    assert await error(second) == (404, "not_found")
    assert "device.issued" in await events(session)


async def test_the_password_and_the_link_never_reach_the_audit_log(
    tma_client: AsyncClient, session: AsyncSession, trial_plan: Plan
) -> None:
    await start_trial(tma_client)
    body = (await tma_client.post("/api/tma/devices", json=DEVICE)).json()
    dump = json.dumps(
        [row.details for row in await session.scalars(select(AuditLog))], ensure_ascii=False
    )
    token = body["download_url"].rsplit("/", 1)[1]
    assert body["p12_password"] not in dump
    assert token not in dump


async def test_a_wrong_or_malformed_token_is_a_plain_404(public_client: AsyncClient) -> None:
    for token in ("x", "short", "a" * 43, "a" * 5000, "%00" * 20, "..%2f..%2fetc"):
        r = await public_client.get(f"/api/tma/download/{token}")
        assert await error(r) == (404, "not_found"), token


async def test_the_device_list_counts_the_limit_and_the_issue_stops_at_it(
    tma_client: AsyncClient, trial_plan: Plan
) -> None:
    await start_trial(tma_client)  # в trial — одно устройство
    assert (await tma_client.post("/api/tma/devices", json=DEVICE)).status_code == 200
    r = await tma_client.post("/api/tma/devices", json=DEVICE | {"name": "second"})
    assert await error(r) == (409, "device_limit_reached")
    devices = (await tma_client.get("/api/tma/devices")).json()
    sub = (await tma_client.get("/api/tma/subscription")).json()["subscription"]
    assert len(devices) == sub["devices_used"] == 1


async def test_no_subscription_means_no_key(tma_client: AsyncClient) -> None:
    r = await tma_client.post("/api/tma/devices", json=DEVICE)
    assert await error(r) == (409, "subscription_inactive")


async def test_a_blocked_client_gets_no_key(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await make_subscription(client, now=utcnow())
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    r = await tma_client.post("/api/tma/devices", json=DEVICE)
    assert await error(r) == (403, "subscription_inactive")


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "platform": "ios"},
        {"name": "   ", "platform": "ios"},
        {"name": "x" * 41, "platform": "ios"},
        {"name": "bad\x00name", "platform": "ios"},
        {"name": "ok", "platform": "symbian"},
        {"name": "ok"},
        {"name": "ok", "platform": "ios", "extra": 1},
    ],
)
async def test_a_bad_device_body_is_422_and_issues_nothing(
    tma_client: AsyncClient, session: AsyncSession, trial_plan: Plan, body: dict[str, object]
) -> None:
    await start_trial(tma_client)
    r = await tma_client.post("/api/tma/devices", json=body)
    assert await error(r) == (422, "validation_error")
    assert await session.scalar(select(func.count()).select_from(Device)) == 0


async def test_the_key_can_be_issued_only_ten_times_an_hour(tma_client: AsyncClient) -> None:
    codes = [
        (await tma_client.post("/api/tma/devices", json=DEVICE)).status_code for _ in range(11)
    ]
    assert codes == [409] * 10 + [429]


async def test_the_list_shows_online_status_and_traffic_of_the_period(
    tma_client: AsyncClient,
    session: AsyncSession,
    redis: ArqRedis,
    settings: Settings,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    now = utcnow()
    sub = await make_subscription(client, now=now - timedelta(days=2))
    first = await make_device(client, seq=1)
    second = await make_device(client, seq=2)
    await make_device(client, seq=3, revoked=True)
    node = await registry.ensure_local_node(session, settings)
    session.add_all(
        [
            TrafficSample(  # в периоде подписки
                node_id=node.id,
                username=first.ocserv_username,
                ts=now - timedelta(days=1),
                bytes_in_delta=100,
                bytes_out_delta=900,
                duration_sec=60,
            ),
            TrafficSample(  # до начала периода — не считается
                node_id=node.id,
                username=first.ocserv_username,
                ts=sub.traffic_period_start - timedelta(days=1),
                bytes_in_delta=5,
                bytes_out_delta=5,
                duration_sec=60,
            ),
        ]
    )
    await session.flush()
    await redis.set(service.online_key(node.id), json.dumps([second.ocserv_username]))
    rows = {d["name"]: d for d in (await tma_client.get("/api/tma/devices")).json()}
    assert set(rows) == {"dev1", "dev2"}  # отозванного нет
    assert (rows["dev1"]["is_online"], rows["dev1"]["traffic_used_bytes"]) == (False, 1000)
    assert (rows["dev2"]["is_online"], rows["dev2"]["traffic_used_bytes"]) == (True, 0)


async def test_without_the_node_cache_everyone_is_offline_not_an_error(
    tma_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await make_subscription(client, now=utcnow())
    await make_device(client)
    r = await tma_client.get("/api/tma/devices")
    assert r.status_code == 200
    assert [d["is_online"] for d in r.json()] == [False]


async def test_a_client_without_a_subscription_sees_an_empty_list(tma_client: AsyncClient) -> None:
    assert (await tma_client.get("/api/tma/devices")).json() == []


# --- отзыв --------------------------------------------------------------------


async def test_revoking_removes_the_device_and_the_event_follows(
    tma_client: AsyncClient, session: AsyncSession, trial_plan: Plan
) -> None:
    await start_trial(tma_client)
    device = (await tma_client.post("/api/tma/devices", json=DEVICE)).json()["device"]
    r = await tma_client.delete(f"/api/tma/devices/{device['id']}")
    assert (r.status_code, r.content) == (204, b"")
    assert (await tma_client.get("/api/tma/devices")).json() == []
    assert await session.scalar(select(func.count()).select_from(Revocation)) == 1
    assert "device.revoked" in await events(session)
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "device.revoke"))
    assert audit is not None
    assert audit.actor_type == "client"

    # Освободившееся место можно занять; повторный отзыв не плодит ни записей, ни событий.
    again = await tma_client.delete(f"/api/tma/devices/{device['id']}")
    assert again.status_code == 204
    assert await session.scalar(select(func.count()).select_from(Revocation)) == 1
    assert (await events(session)).count("device.revoked") == 1
    assert (await tma_client.post("/api/tma/devices", json=DEVICE)).status_code == 200


async def test_someone_elses_device_looks_exactly_like_a_missing_one(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    other = await make_client(telegram_id=9999, first_name="Boris")
    foreign = await make_device(other)
    stranger = await tma_client.delete(f"/api/tma/devices/{foreign.id}")
    missing = await tma_client.delete("/api/tma/devices/999999")
    assert await error(stranger) == await error(missing) == (404, "not_found")
    assert stranger.json() == missing.json()
    await session.refresh(foreign)
    assert foreign.revoked_at is None


@pytest.mark.parametrize("raw", ["abc", "-1", "0", "1.5", "99999999999999999999", "%20", "١٢"])
async def test_a_junk_device_id_is_not_found_not_a_server_error(
    tma_client: AsyncClient, raw: str
) -> None:
    r = await tma_client.delete(f"/api/tma/devices/{raw}")
    assert await error(r) == (404, "not_found")


async def test_a_blocked_client_can_still_revoke_their_own_key(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await make_subscription(client, now=utcnow())
    device = await make_device(client)
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    assert (await tma_client.delete(f"/api/tma/devices/{device.id}")).status_code == 204


async def test_two_clients_do_not_share_the_rate_limit(
    public_client: AsyncClient, tma_headers: TmaHeaders
) -> None:
    for _ in range(10):
        await public_client.post("/api/tma/devices", json=DEVICE, headers=tma_headers())
    blocked = await public_client.post("/api/tma/devices", json=DEVICE, headers=tma_headers())
    other = await public_client.post(
        "/api/tma/devices", json=DEVICE, headers=tma_headers(telegram_id=555)
    )
    assert (blocked.status_code, other.status_code) == (429, 409)
