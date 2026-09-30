from datetime import datetime, timedelta

from conftest import (
    TMA_TELEGRAM_ID,
    MakeClient,
    MakeDevice,
    MakePlan,
    MakeSubscription,
    TmaHeaders,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Plan
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.subscriptions import service as subscriptions

ENDPOINTS = ["/api/tma/me", "/api/tma/plans", "/api/tma/subscription", "/api/tma/connection"]


async def test_every_endpoint_needs_the_init_data(public_client: AsyncClient) -> None:
    for path in ENDPOINTS:
        r = await public_client.get(path)
        assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized"), path


async def test_a_new_client_can_take_the_trial(tma_client: AsyncClient) -> None:
    body = (await tma_client.get("/api/tma/me")).json()
    assert body == {
        "telegram_id": TMA_TELEGRAM_ID,
        "first_name": "Anna",
        "username": None,
        "lang": "ru",
        "is_blocked": False,
        "trial_available": True,
    }
    assert (await tma_client.get("/api/tma/subscription")).json() == {"subscription": None}


async def test_the_trial_is_not_offered_once_it_was_used_or_a_subscription_exists(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await make_subscription(client, now=utcnow())
    assert (await tma_client.get("/api/tma/me")).json()["trial_available"] is False


async def test_a_used_trial_without_a_subscription_is_not_offered_again(
    tma_client: AsyncClient, session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    client.trial_used_at = utcnow()
    await session.flush()
    assert (await tma_client.get("/api/tma/me")).json()["trial_available"] is False


async def test_a_blocked_client_gets_200_and_the_flag(
    tma_client: AsyncClient, session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    r = await tma_client.get("/api/tma/me")
    assert r.status_code == 200
    assert r.json()["is_blocked"] is True
    assert r.json()["trial_available"] is False


async def test_the_catalog_is_localized_sorted_and_hides_the_trial(
    tma_client: AsyncClient,
    public_client: AsyncClient,
    tma_headers: TmaHeaders,
    make_plan: MakePlan,
    trial_plan: Plan,
) -> None:
    await make_plan(code="year", name_i18n={"ru": "Год", "en": "Year"}, sort_order=20)
    await make_plan(
        code="month",
        name_i18n={"ru": "Месяц", "en": "Month"},
        description_i18n={"ru": "Для начала", "en": "To start"},
        sort_order=10,
    )
    await make_plan(code="old", is_active=False, sort_order=1)
    ru = (await tma_client.get("/api/tma/plans")).json()
    assert [p["code"] for p in ru] == ["month", "year"]
    assert [p["name"] for p in ru] == ["Месяц", "Год"]
    assert (ru[0]["description"], ru[1]["description"]) == ("Для начала", None)
    assert not any(p["is_trial"] for p in ru)

    en = await public_client.get(
        "/api/tma/plans", headers=tma_headers(telegram_id=8002, language_code="en")
    )
    assert [p["name"] for p in en.json()] == ["Month", "Year"]
    assert en.json()[0]["description"] == "To start"


async def test_the_subscription_shape_and_the_device_counter(
    tma_client: AsyncClient,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_device: MakeDevice,
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    now = utcnow()
    await make_subscription(client, now=now, days=30)
    await make_device(client, seq=1)
    await make_device(client, seq=2, revoked=True)  # отозванное не занимает место
    body = (await tma_client.get("/api/tma/subscription")).json()["subscription"]
    assert (body["status"], body["devices_used"], body["device_limit"]) == ("active", 1, 3)
    assert body["plan"]["duration_days"] == 30
    assert body["expires_at"].endswith("Z")
    assert isinstance(body["id"], str)
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert timedelta(days=29) < expires - now <= timedelta(days=30)


async def test_the_connection_points_at_the_gateway_with_the_camouflage_secret(
    tma_client: AsyncClient, settings: Settings
) -> None:
    body = (await tma_client.get("/api/tma/connection")).json()
    assert body["server_host"] == settings.vpn_host
    assert body["gateway_url"] == (
        f"https://{settings.vpn_host}/?{settings.camouflage_secret.get_secret_value()}"
    )
    assert body["server_host"] in body["gateway_url"]


async def test_a_non_default_port_is_part_of_the_gateway_address(
    public_client: AsyncClient, public_app: FastAPI, tma_headers: TmaHeaders, settings: Settings
) -> None:
    public_app.state.settings = settings.model_copy(update={"vpn_port": 4443})
    body = (await public_client.get("/api/tma/connection", headers=tma_headers())).json()
    assert body["gateway_url"].startswith(f"https://{settings.vpn_host}:4443/?")
    assert body["server_host"] == settings.vpn_host


async def test_a_blocked_client_does_not_get_the_gateway_address(
    tma_client: AsyncClient, session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client(telegram_id=TMA_TELEGRAM_ID, first_name="Anna")
    await subscriptions.set_blocked(session, client.id, True, utcnow())
    r = await tma_client.get("/api/tma/connection")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "subscription_inactive")
