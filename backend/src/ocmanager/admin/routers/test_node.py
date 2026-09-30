import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakeDevice, MakeSubscription, read_stream_then_disconnect
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.nodes import registry, service
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.nodes.models import Node
from ocmanager.nodes.service import NodeHealth


@pytest.fixture
def fake() -> Iterator[FakeNodeDriver]:
    driver = FakeNodeDriver(allowlist=set())
    with registry.override_driver(driver):
        yield driver


ENDPOINTS = [
    ("GET", "/admin/node"),
    ("POST", "/admin/node/probe"),
    ("GET", "/admin/node/sessions"),
    ("POST", "/admin/node/actions"),
    ("POST", "/admin/node/reconcile"),
    ("GET", "/admin/node/logs"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
async def test_a_session_is_required(anon_client: AsyncClient, method: str, path: str) -> None:
    assert (await anon_client.request(method, path)).status_code == 401


@pytest.mark.parametrize(("method", "path"), [e for e in ENDPOINTS if e[0] == "POST"])
async def test_posts_need_the_csrf_token(
    admin_client: AsyncClient, fake: FakeNodeDriver, method: str, path: str
) -> None:
    del admin_client.headers["X-CSRF-Token"]
    assert (await admin_client.request(method, path, json={})).status_code == 403


async def test_status_shows_the_cache_and_the_last_reconcile(
    admin_client: AsyncClient, session: AsyncSession, settings: Settings, redis: ArqRedis
) -> None:
    body = (await admin_client.get("/admin/node")).json()
    assert body["node"]["name"] == "local"
    assert body["health"] is None  # воркер ещё не писал кэш
    assert body["last_reconcile_report"] is None

    node = await registry.ensure_local_node(session, settings)
    health = NodeHealth(node.id, "online", "running", 3, utcnow(), None)
    await redis.set(service.health_key(node.id), health.to_json())
    body = (await admin_client.get("/admin/node")).json()
    assert (body["health"]["state"], body["health"]["active_sessions"]) == ("online", 3)


async def test_probe_is_live_and_refreshes_status_and_cache(
    admin_client: AsyncClient, redis: ArqRedis, fake: FakeNodeDriver
) -> None:
    fake.container_state = "exited"
    r = await admin_client.post("/admin/node/probe")
    assert r.status_code == 200
    assert (r.json()["state"], r.json()["container_state"]) == ("offline", "exited")
    node = (await admin_client.get("/admin/node")).json()
    assert node["node"]["status"] == "offline"
    assert node["health"]["state"] == "offline"  # кэш обновлён самой проверкой
    fake.container_state = "running"
    assert (await admin_client.post("/admin/node/probe")).json()["state"] == "online"


async def test_live_sessions_are_matched_to_clients_and_devices(
    admin_client: AsyncClient,
    fake: FakeNodeDriver,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client(telegram_id=4242, first_name="Anna")
    device = await make_device(client)
    fake.add_session(device.ocserv_username, bytes_in=10, bytes_out=20)
    fake.add_session("c999-d9")  # ocserv видит того, кого нет в БД
    rows = {s["username"]: s for s in (await admin_client.get("/admin/node/sessions")).json()}
    mine = rows[device.ocserv_username]
    assert (mine["client_name"], mine["telegram_id"], mine["device_name"]) == (
        "Anna",
        4242,
        device.name,
    )
    assert (mine["bytes_in"], mine["bytes_out"], mine["client_id"]) == (10, 20, client.id)
    stranger = rows["c999-d9"]
    assert (stranger["client_id"], stranger["device_id"], stranger["telegram_id"]) == (
        None,
        None,
        None,
    )


async def test_sessions_of_a_dead_node_are_503(
    admin_client: AsyncClient, fake: FakeNodeDriver
) -> None:
    fake.container_state = "exited"
    r = await admin_client.get("/admin/node/sessions")
    assert (r.status_code, r.json()["error"]["code"]) == (503, "node_unavailable")
    fake.container_state, fake.occtl_ok = "running", False
    assert (await admin_client.get("/admin/node/sessions")).status_code == 503


async def audit_actions(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(AuditLog.action).order_by(AuditLog.id)))


async def test_restart_reaches_the_driver_and_is_audited(
    admin_client: AsyncClient, session: AsyncSession, fake: FakeNodeDriver
) -> None:
    r = await admin_client.post("/admin/node/actions", json={"action": "restart"})
    assert r.status_code == 204
    assert ("container_action", ("restart",)) in fake.calls
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "node.restart"))
    assert row is not None
    assert row.actor_type == "admin"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "rm"},
        {"action": "restart; rm -rf /"},
        {"action": "disconnect_user"},  # без username
        {"action": "disconnect_user", "username": "../etc/passwd"},
        {"action": "reload", "extra": 1},
        {},
    ],
)
async def test_only_registered_actions_with_valid_arguments_run(
    admin_client: AsyncClient,
    session: AsyncSession,
    fake: FakeNodeDriver,
    body: dict[str, Any],
) -> None:
    r = await admin_client.post("/admin/node/actions", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")
    mutating = {"container_action", "reload", "disconnect_user"}
    assert [c for c in fake.calls if c[0] in mutating] == []
    assert not [a for a in await audit_actions(session) if a.startswith("node.")]


async def test_disconnect_user_drops_the_session(
    admin_client: AsyncClient, fake: FakeNodeDriver
) -> None:
    fake.add_session("c1-d1")
    r = await admin_client.post(
        "/admin/node/actions", json={"action": "disconnect_user", "username": "c1-d1"}
    )
    assert r.status_code == 204
    assert fake.sessions == []


async def test_an_action_on_a_dead_node_is_503_and_not_audited(
    admin_client: AsyncClient, session: AsyncSession, fake: FakeNodeDriver
) -> None:
    fake.container_state = "exited"
    r = await admin_client.post("/admin/node/actions", json={"action": "reload"})
    assert (r.status_code, r.json()["error"]["code"]) == (503, "node_unavailable")
    assert "node.reload" not in await audit_actions(session)


async def test_reconcile_repairs_reports_and_remembers(
    admin_client: AsyncClient,
    session: AsyncSession,
    fake: FakeNodeDriver,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    await make_subscription(client, now=utcnow())
    device = await make_device(client)
    fake.allowlist = set()  # событие «потерялось»

    r = await admin_client.post("/admin/node/reconcile")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {d["kind"] for d in body["drifts"]}
    assert {"allowlist_diff", "crl_missing"} <= kinds
    assert body["error"] is None
    assert fake.allowlist == {device.ocserv_username}  # починено

    node = await session.scalar(select(Node))
    assert node is not None
    await session.refresh(node)
    assert node.last_reconcile_report is not None
    assert {d["kind"] for d in node.last_reconcile_report["drifts"]} == kinds
    shown = (await admin_client.get("/admin/node")).json()
    assert shown["last_reconcile_report"] == node.last_reconcile_report

    clean = (await admin_client.post("/admin/node/reconcile")).json()
    assert clean["drifts"] == []


async def test_reconcile_of_a_dead_node_reports_instead_of_failing(
    admin_client: AsyncClient, fake: FakeNodeDriver
) -> None:
    fake.container_state = "exited"
    r = await admin_client.post("/admin/node/reconcile")
    assert r.status_code == 200
    assert r.json()["error"] == "container exited"


async def test_logs_are_an_event_stream(admin_client: AsyncClient, fake: FakeNodeDriver) -> None:
    fake.log_lines = ["ocserv started", "user connected"]
    r = await admin_client.get("/admin/node/logs?tail=10")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    assert r.text == "data: ocserv started\n\ndata: user connected\n\n"
    assert ("stream_logs", (10,)) in fake.calls


@pytest.mark.parametrize("tail", ["0", "2001", "x"])
async def test_a_silly_tail_is_422(admin_client: AsyncClient, tail: str) -> None:
    assert (await admin_client.get(f"/admin/node/logs?tail={tail}")).status_code == 422


async def test_logs_of_a_missing_container_are_503(
    admin_client: AsyncClient, fake: FakeNodeDriver
) -> None:
    fake.container_state = "missing"
    r = await admin_client.get("/admin/node/logs")
    assert (r.status_code, r.json()["error"]["code"]) == (503, "node_unavailable")


class EndlessLogs(FakeNodeDriver):
    """Логи, которые никогда не кончаются, и отметка о том, что читатель закрыт."""

    closed: asyncio.Event

    @asynccontextmanager
    async def stream_logs(self, *, tail: int = 200) -> AsyncIterator[AsyncIterator[str]]:
        async def lines() -> AsyncIterator[str]:
            try:
                n = 0
                while True:
                    n += 1
                    yield f"line {n}"
                    await asyncio.sleep(0.01)
            finally:
                self.closed.set()  # здесь на настоящей ноде умирает `docker logs -f`

        stream = lines()
        try:
            yield stream
        finally:
            await stream.aclose()  # type: ignore[attr-defined]


async def test_a_dropped_connection_stops_the_log_reader(
    admin_client: AsyncClient, admin_app: FastAPI
) -> None:
    driver = EndlessLogs(allowlist=set())
    driver.closed = asyncio.Event()
    with registry.override_driver(driver):
        received = await read_stream_then_disconnect(
            admin_app, admin_client.cookies["ocm_admin"], chunks=2
        )
        # Ответ завершился отключением клиента, а читатель закрыт не позже чем через секунду.
        await asyncio.wait_for(driver.closed.wait(), timeout=1)
    assert received[:2] == [b"data: line 1\n\n", b"data: line 2\n\n"]
