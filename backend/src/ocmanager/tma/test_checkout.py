import pytest
from conftest import TMA_TELEGRAM_ID, MakePlan, TmaHeaders
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.billing.models import CheckoutIntent, Plan
from ocmanager.core.clock import utcnow
from ocmanager.flows import subscriptions as subscription_flows
from ocmanager.subscriptions.models import Client
from ocmanager.tma.test_contract_parity import KNOWN_UNMAPPED, frontend_codes

URL = "/api/tma/checkout"
LINK = "https://t.me/tribute/app?startapp=s1"
PRODUCT = {"tribute": {"product_ref": "1001", "link": LINK}}


async def error(r: Response) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


async def test_the_checkout_returns_the_link_and_remembers_the_intent(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    plan = await make_plan(code="month", provider_product_ids=PRODUCT)
    r = await tma_client.post(URL, json={"plan_code": "month"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checkout_url"] == LINK
    assert body["payment_id"].startswith("ci_")

    client = await session.scalar(select(Client).where(Client.telegram_id == TMA_TELEGRAM_ID))
    assert client is not None
    [intent] = list(await session.scalars(select(CheckoutIntent)))
    assert (intent.id, intent.client_id, intent.plan_id, intent.provider) == (
        body["payment_id"],
        client.id,
        plan.id,
        "tribute",
    )
    [entry] = list(
        await session.scalars(select(AuditLog).where(AuditLog.action == "checkout.create"))
    )
    assert (entry.actor_type, entry.actor_id, entry.details["plan_code"]) == (
        "client",
        str(client.id),
        "month",
    )


async def test_every_press_of_the_button_is_its_own_intent(
    tma_client: AsyncClient, make_plan: MakePlan
) -> None:
    await make_plan(code="month", provider_product_ids=PRODUCT)
    ids = {
        (await tma_client.post(URL, json={"plan_code": "month"})).json()["payment_id"]
        for _ in range(3)
    }
    assert len(ids) == 3


async def test_the_checkout_needs_the_init_data(public_client: AsyncClient) -> None:
    r = await public_client.post(URL, json={"plan_code": "month"})
    assert await error(r) == (401, "unauthorized")


async def test_an_unknown_plan_is_not_found(tma_client: AsyncClient) -> None:
    r = await tma_client.post(URL, json={"plan_code": "nope"})
    assert await error(r) == (404, "not_found")


async def test_an_inactive_plan_cannot_be_bought(
    tma_client: AsyncClient, make_plan: MakePlan
) -> None:
    await make_plan(code="old", provider_product_ids=PRODUCT, is_active=False)
    assert await error(await tma_client.post(URL, json={"plan_code": "old"})) == (404, "not_found")


async def test_the_hidden_trial_plan_cannot_be_bought(
    tma_client: AsyncClient, session: AsyncSession, trial_plan: Plan
) -> None:
    trial_plan.provider_product_ids = PRODUCT
    await session.flush()  # иначе приложение, читающее другой сессией, изменения не увидит
    r = await tma_client.post(URL, json={"plan_code": trial_plan.code})
    assert await error(r) == (404, "not_found")


async def test_a_plan_without_a_payment_link_is_not_found_and_the_admin_is_warned(
    tma_client: AsyncClient, make_plan: MakePlan, session: AsyncSession
) -> None:
    await make_plan(code="bare")
    with capture_logs() as logs:
        r = await tma_client.post(URL, json={"plan_code": "bare"})
    assert await error(r) == (404, "not_found")
    assert any(e["event"] == "plan_without_payment_link" for e in logs)
    assert list(await session.scalars(select(CheckoutIntent))) == []


@pytest.mark.parametrize("link", ["http://t.me/x", "javascript:alert(1)", "//evil.example/x"])
async def test_an_unsafe_link_is_never_handed_to_the_client(
    tma_client: AsyncClient, make_plan: MakePlan, link: str
) -> None:
    await make_plan(code="bad", provider_product_ids={"tribute": {"link": link}})
    assert await error(await tma_client.post(URL, json={"plan_code": "bad"})) == (404, "not_found")


async def test_a_blocked_client_cannot_start_a_purchase(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    await make_plan(code="month", provider_product_ids=PRODUCT)
    await tma_client.get("/api/tma/me")  # создаёт клиента
    client = await session.scalar(select(Client).where(Client.telegram_id == TMA_TELEGRAM_ID))
    assert client is not None
    await subscription_flows.set_blocked(session, client.id, True, Actor.system(), utcnow())

    r = await tma_client.post(URL, json={"plan_code": "month"})
    assert await error(r) == (403, "subscription_inactive")
    assert list(await session.scalars(select(CheckoutIntent))) == []


async def test_the_checkout_is_rate_limited_per_client(
    tma_client: AsyncClient, make_plan: MakePlan, tma_headers: TmaHeaders
) -> None:
    await make_plan(code="month", provider_product_ids=PRODUCT)
    for _ in range(20):
        assert (await tma_client.post(URL, json={"plan_code": "month"})).status_code == 200
    assert await error(await tma_client.post(URL, json={"plan_code": "month"})) == (
        429,
        "rate_limited",
    )
    # Другой клиент лимит не делит.
    other = await tma_client.post(
        URL, json={"plan_code": "month"}, headers=tma_headers(telegram_id=7002)
    )
    assert other.status_code == 200


@pytest.mark.parametrize(
    "body",
    [{}, {"plan_code": ""}, {"plan_code": 5}, {"plan_code": "x" * 65}, {"plan_code": "m", "x": 1}],
    ids=["empty", "blank", "number", "too-long", "extra-field"],
)
async def test_a_malformed_body_is_a_validation_error(
    tma_client: AsyncClient, body: dict[str, object]
) -> None:
    assert await error(await tma_client.post(URL, json=body)) == (422, "validation_error")


async def test_every_checkout_error_is_a_code_the_frontend_knows(
    tma_client: AsyncClient, public_client: AsyncClient, make_plan: MakePlan
) -> None:
    await make_plan(code="bare")
    known = frontend_codes() | set(KNOWN_UNMAPPED)
    seen = {
        (await public_client.post(URL, json={"plan_code": "x"})).json()["error"]["code"],
        (await tma_client.post(URL, json={"plan_code": "nope"})).json()["error"]["code"],
        (await tma_client.post(URL, json={"plan_code": "bare"})).json()["error"]["code"],
        (await tma_client.post(URL, json={})).json()["error"]["code"],
    }
    assert seen <= known, f"фронтенд не знает коды: {sorted(seen - known)}"
