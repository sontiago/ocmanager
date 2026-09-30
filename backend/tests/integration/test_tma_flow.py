"""Критерий готовности Фазы 4 (бэкенд): клиент проходит путь Mini App на живом ocserv.

Открыл → пробный период → выпустил устройство → скачал `.p12` (один раз) → подключился →
отозвал в приложении → сессия оборвана, сертификат больше не принимается. Ни одного действия
админа и оператора: всё — публичным API с подписанной initData.
"""

import time
from collections.abc import AsyncIterator

import pytest
from arq import ArqRedis
from cryptography.hazmat.primitives.serialization import pkcs12
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ocmanager.apps.public_api import create_app
from ocmanager.core.clock import utcnow
from ocmanager.events import bus
from ocmanager.flows import handlers
from ocmanager.flows import revocations as revocation_flows
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca
from ocmanager.tma.testing import make_init_data
from tests.integration.env import Env
from tests.integration.stand import CERTS_DIR, ClientCert

pytestmark = pytest.mark.ocserv

TELEGRAM_ID = 5101


@pytest.fixture
async def tma_app(env: Env, redis: ArqRedis, dev_ca: CertificateAuthority) -> FastAPI:
    """Настоящее публичное приложение поверх той же БД и живой ноды."""
    async with env.sessionmaker() as session:
        await session.execute(
            text(
                "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
                " currency, is_active, is_trial)"
                ' VALUES (\'trial\', CAST(\'{"ru": "Пробный", "en": "Trial"}\' AS jsonb),'
                " 3, 1, 0, 'RUB', false, true) ON CONFLICT DO NOTHING"
            )
        )
        await session.commit()
    app = create_app(env.settings)
    app.state.sessionmaker = env.sessionmaker
    app.state.redis = redis
    app.state.ca = dev_ca
    return app


@pytest.fixture
async def browser(tma_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Системный браузер, в котором открывается ссылка на скачивание: initData у него нет."""
    async with AsyncClient(
        transport=ASGITransport(app=tma_app), base_url="http://localhost"
    ) as client:
        yield client


@pytest.fixture
async def tma(env: Env, tma_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Mini App: клиент — Анна из Telegram."""
    raw = make_init_data(
        env.settings.bot_token.get_secret_value(),
        user={"id": TELEGRAM_ID, "first_name": "Anna", "language_code": "ru"},
        auth_date=int(time.time()),
    )
    async with AsyncClient(
        transport=ASGITransport(app=tma_app),
        base_url="http://localhost",
        headers={"Authorization": f"tma {raw}"},
    ) as client:
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


async def test_the_mini_app_path_from_the_first_open_to_a_vpn_session(
    env: Env, tma: AsyncClient, browser: AsyncClient
) -> None:
    me = (await tma.get("/api/tma/me")).json()
    assert (me["first_name"], me["trial_available"], me["is_blocked"]) == ("Anna", True, False)

    trial = await tma.post("/api/tma/subscription/trial")
    assert trial.status_code == 200, trial.text
    assert trial.json()["status"] == "trial"

    issued = await tma.post("/api/tma/devices", json={"name": "ноутбук", "platform": "linux"})
    assert issued.status_code == 200, issued.text
    body = issued.json()

    # ссылку открывают вне Mini App — без initData
    path = "/api/tma" + body["download_url"].split("/api/tma", 1)[1]
    p12 = await browser.get(path)
    assert p12.status_code == 200
    assert (await browser.get(path)).status_code == 404  # одноразовая

    username = p12.headers["Content-Disposition"].split('filename="')[1].removesuffix('.p12"')
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    (CERTS_DIR / f"{username}.p12").write_bytes(p12.content)
    _, cert, _ = pkcs12.load_key_and_certificates(p12.content, body["p12_password"].encode())
    assert cert is not None
    vpn_cert = ClientCert(username, body["p12_password"], cert.serial_number)

    await sync(env)  # allowed.list обновился событиями
    await env.vpn.connect(vpn_cert)
    await env.vpn.ping(username, "10.77.0.1", count=3, size=1000)
    await env.collect_traffic()

    devices = (await tma.get("/api/tma/devices")).json()
    assert [d["name"] for d in devices] == ["ноутбук"]
    assert devices[0]["traffic_used_bytes"] >= 6000
    sub = (await tma.get("/api/tma/subscription")).json()["subscription"]
    assert (sub["devices_used"], sub["traffic_used_bytes"] >= 6000) == (1, True)
    connection = (await tma.get("/api/tma/connection")).json()
    assert connection["server_host"] in connection["gateway_url"]

    # отзыв из приложения рвёт сессию и закрывает сертификат
    assert (await tma.delete(f"/api/tma/devices/{devices[0]['id']}")).status_code == 204
    await sync(env)
    await env.eventually_disconnected(username)
    assert not await env.vpn.authenticate_only(vpn_cert)
    assert (await tma.get("/api/tma/devices")).json() == []
