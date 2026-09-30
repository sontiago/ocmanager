"""Критерий готовности Фазы 3: сервис эксплуатируется из админ-API на живом ocserv.

Вход → тариф → клиент → выдача и устройство → `.p12` → подключение → сессия на ноде →
отзыв → перезапуск ocserv → живые логи → всё это в аудите. Воркера нет: события и отзывы
доставляются тем же вызовом, что делает CLI (`sync`).
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from arq import ArqRedis
from conftest import ADMIN_PASSWORD, read_stream_then_disconnect
from cryptography.hazmat.primitives.serialization import pkcs12
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ocmanager.admin import accounts
from ocmanager.apps.admin_api import create_app
from ocmanager.audit.service import Actor
from ocmanager.core import shell
from ocmanager.core.clock import utcnow
from ocmanager.events import bus
from ocmanager.flows import handlers
from ocmanager.flows import revocations as revocation_flows
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca
from tests.integration.env import Env
from tests.integration.stand import CERTS_DIR, ClientCert, eventually

pytestmark = pytest.mark.ocserv


@pytest.fixture
async def admin_app(
    env: Env, redis: ArqRedis, dev_ca: CertificateAuthority, fast_bcrypt: None
) -> FastAPI:
    """Настоящий админ-API поверх той же БД и живой ноды."""
    async with env.sessionmaker() as session:
        await accounts.create_admin(session, "owner", ADMIN_PASSWORD, Actor.system())
        await session.commit()
    app = create_app(env.settings)
    app.state.sessionmaker = env.sessionmaker
    app.state.redis = redis
    app.state.ca = dev_ca
    return app


@pytest.fixture
async def admin(admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Клиент, уже вошедший под `owner`."""
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        r = await client.post(
            "/admin/auth/login", json={"username": "owner", "password": ADMIN_PASSWORD}
        )
        assert r.status_code == 200, r.text
        client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        yield client


async def sync(env: Env) -> None:
    """То, что в проде делает воркер: доставить события и применить отзывы (CRL)."""
    handlers.register(env.settings)
    await bus.dispatch_pending(env.sessionmaker)
    async with env.sessionmaker() as session:
        await revocation_flows.apply_revocations(
            session, env.settings, load_ca(env.settings.pki_dir), utcnow()
        )
        await session.commit()


async def test_the_operator_path_through_the_admin_api(
    env: Env, admin: AsyncClient, admin_app: FastAPI
) -> None:
    # тариф и клиент; клиентов в проде создаёт TMA, здесь — dev-команда
    plan = await admin.post(
        "/admin/plans",
        json={
            "code": "m1",
            "name_i18n": {"ru": "Месяц", "en": "Month"},
            "duration_days": 30,
            "device_limit": 2,
            "price_amount": 19900,
            "currency": "RUB",
        },
    )
    assert plan.status_code == 201, plan.text
    await env.cli("client", "add", "--telegram-id", "5001", "--first-name", "Anna")

    # найти клиента, выдать тариф и устройство
    found = (await admin.get("/admin/clients", params={"q": "5001"})).json()["items"]
    client_id = found[0]["id"]
    granted = await admin.post(f"/admin/clients/{client_id}/grant", json={"plan_code": "m1"})
    assert granted.json()["status"] == "active"
    issued = await admin.post(
        f"/admin/clients/{client_id}/devices", json={"name": "laptop", "platform": "linux"}
    )
    assert issued.status_code == 200, issued.text
    body = issued.json()

    # скачать .p12 (один раз) и положить туда, где его видит контейнер vpn-client
    p12 = await admin.get(body["download_path"])
    assert p12.status_code == 200
    username = body["device"]["username"]
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    (CERTS_DIR / f"{username}.p12").write_bytes(p12.content)
    _, cert, _ = pkcs12.load_key_and_certificates(p12.content, body["p12_password"].encode())
    assert cert is not None
    vpn_cert = ClientCert(username, body["p12_password"], cert.serial_number)
    assert (await admin.get(body["download_path"])).status_code == 404  # ссылка одноразовая

    await sync(env)  # allowed.list обновился событиями
    await env.vpn.connect(vpn_cert)

    # сессия видна на ноде вместе с клиентом и устройством
    sessions = (await admin.get("/admin/node/sessions")).json()
    mine = next(s for s in sessions if s["username"] == username)
    assert (mine["client_name"], mine["telegram_id"], mine["device_name"]) == (
        "Anna",
        5001,
        "laptop",
    )

    # отзыв: сессия разорвана, сертификат больше не принимается
    device_id = body["device"]["id"]
    revoked = await admin.post(f"/admin/devices/{device_id}/revoke", json={"reason": "тест"})
    assert revoked.status_code == 200
    await sync(env)
    await env.eventually_disconnected(username)
    assert not await env.vpn.authenticate_only(vpn_cert)

    # перезапуск ocserv и живые логи
    assert (await admin.post("/admin/node/actions", json={"action": "restart"})).status_code == 204

    async def back() -> bool:
        state = (await admin.post("/admin/node/probe")).json()["state"]
        return bool(state == "online")

    await eventually(back, within=60)

    chunks = await read_stream_then_disconnect(admin_app, admin.cookies["ocm_admin"], chunks=1)
    assert chunks[0].startswith(b"data: ")
    await asyncio.sleep(1)  # процесс docker logs успел завершиться после обрыва
    leaked = await shell.run(["pgrep", "-f", "docker logs -f"], check=False)
    assert leaked.stdout.strip() == ""

    # всё сделанное — в аудите
    rows = (await admin.get("/admin/audit", params={"limit": 200})).json()["items"]
    done = {r["action"] for r in rows}
    assert {
        "admin.login",
        "plan.create",
        "subscription.activate",
        "device.issue",
        "device.download",
        "device.revoke",
        "node.restart",
    } <= done
    admin_rows = [r for r in rows if r["action"] in {"device.revoke", "node.restart"}]
    assert all(r["actor_type"] == "admin" and r["ip"] == "127.0.0.1" for r in admin_rows)
