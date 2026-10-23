"""Экран «Друзья» и ввод промокода в Mini App."""

from datetime import timedelta

from conftest import TMA_TELEGRAM_ID, MakeClient, MakePayment, MakePlan
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing import promo
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.referral import GIB
from ocmanager.subscriptions.state import PlanTerms


async def me(tma_client: AsyncClient, session: AsyncSession) -> int:
    assert (await tma_client.get("/api/tma/me")).status_code == 200
    client = await subscriptions.find_client_by_telegram_id(session, TMA_TELEGRAM_ID)
    assert client is not None
    return client.id


async def subscribe(
    session: AsyncSession, make_plan: MakePlan, client_id: int, **plan: object
) -> None:
    p = await make_plan(**plan)
    terms = PlanTerms(p.id, p.duration_days, p.device_limit, p.traffic_limit_bytes, False)
    await subscriptions.activate(session, client_id, terms, utcnow(), auto_renew=True)


async def test_the_referral_screen_of_a_new_client(
    tma_client: AsyncClient, session: AsyncSession
) -> None:
    client_id = await me(tma_client, session)
    client = await subscriptions.get_client(session, client_id)
    body = (await tma_client.get("/api/tma/referral")).json()
    assert body["code"] == client.referral_code
    assert body["link"] is None  # имя бота не настроено
    assert (body["invited"], body["paying_friends"]) == (0, 0)
    assert body["badges"] == []
    assert [(t["friends"], t["reached"]) for t in body["tiers"]] == [
        (3, False),
        (5, False),
        (10, False),
    ]
    assert body["next_tier_friends"] == 3
    assert body["history"] == []


async def test_the_link_is_built_when_the_bot_name_is_known(
    tma_client: AsyncClient, session: AsyncSession, public_app: FastAPI, settings: Settings
) -> None:
    public_app.state.settings = settings.model_copy(update={"bot_username": "ocbot"})
    client_id = await me(tma_client, session)
    client = await subscriptions.get_client(session, client_id)
    body = (await tma_client.get("/api/tma/referral")).json()
    assert body["link"] == f"https://t.me/ocbot?start=ref_{client.referral_code}"


async def test_the_screen_counts_friends_tiers_and_history(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    client_id = await me(tma_client, session)
    friends = [await make_client() for _ in range(4)]
    for friend in friends:
        await subscriptions.set_referrer(
            session, friend.id, (await subscriptions.get_client(session, client_id)).referral_code
        )
    for friend in friends[:3]:
        payment = await make_payment(friend, processed_at=utcnow())
        await subscriptions.add_reward(
            session,
            inviter_id=client_id,
            invitee_id=friend.id,
            payment_id=payment.id,
            kind="base",
            days=7,
            invitee_days=3,
            status="applied",
        )
    payment = await make_payment(friends[2], processed_at=utcnow())
    await subscriptions.add_reward(
        session,
        inviter_id=client_id,
        invitee_id=friends[2].id,
        payment_id=payment.id,
        kind="tier",
        tier=3,
        days=30,
        status="applied",
    )
    body = (await tma_client.get("/api/tma/referral")).json()
    assert (body["invited"], body["paying_friends"]) == (4, 3)
    assert body["badges"] == ["friend"]
    assert [t["reached"] for t in body["tiers"]] == [True, False, False]
    assert body["next_tier_friends"] == 5
    kinds = [(h["kind"], h["tier"], h["days"]) for h in body["history"]]
    assert kinds[0] == ("tier", 3, 30)  # новые первыми
    assert len(kinds) == 4


async def test_the_history_never_shows_other_peoples_rewards(
    tma_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    await me(tma_client, session)
    stranger, friend = await make_client(), await make_client()
    payment = await make_payment(friend, processed_at=utcnow())
    await subscriptions.add_reward(
        session,
        inviter_id=stranger.id,
        invitee_id=friend.id,
        payment_id=payment.id,
        kind="base",
        days=7,
        status="applied",
    )
    assert (await tma_client.get("/api/tma/referral")).json()["history"] == []


async def test_a_promo_code_adds_days(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    client_id = await me(tma_client, session)
    await subscribe(session, make_plan, client_id, duration_days=30)
    await promo.create(session, code="spring14", kind="days", value=14)
    r = await tma_client.post("/api/tma/promo/redeem", json={"code": "Spring14"})
    assert (r.status_code, r.json()) == (200, {"kind": "days", "value": 14})
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.expires_at > utcnow() + timedelta(days=43)


async def test_a_promo_code_adds_traffic(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    client_id = await me(tma_client, session)
    await subscribe(session, make_plan, client_id, traffic_limit_bytes=10 * GIB)
    await promo.create(session, code="more50", kind="traffic", value=50 * GIB)
    r = await tma_client.post("/api/tma/promo/redeem", json={"code": "more50"})
    assert r.json() == {"kind": "traffic", "value": 50 * GIB}
    sub = await subscriptions.get_subscription(session, client_id)
    assert sub is not None
    assert sub.traffic_limit_bytes == 60 * GIB


async def test_promo_failures_use_the_contract_error_codes(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    client_id = await me(tma_client, session)
    await promo.create(session, code="real", kind="days", value=1)

    r = await tma_client.post("/api/tma/promo/redeem", json={"code": "real"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "subscription_inactive")

    await subscribe(session, make_plan, client_id)
    r = await tma_client.post("/api/tma/promo/redeem", json={"code": "nosuch"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "promo_invalid")

    assert (
        await tma_client.post("/api/tma/promo/redeem", json={"code": "real"})
    ).status_code == 200
    r = await tma_client.post("/api/tma/promo/redeem", json={"code": "real"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "promo_already_used")


async def test_guessing_codes_is_rate_limited(
    tma_client: AsyncClient, session: AsyncSession, make_plan: MakePlan
) -> None:
    client_id = await me(tma_client, session)
    await subscribe(session, make_plan, client_id)
    codes = [f"guess{i:02d}" for i in range(12)]
    statuses = [
        (await tma_client.post("/api/tma/promo/redeem", json={"code": c})).status_code
        for c in codes
    ]
    assert statuses[:10] == [404] * 10
    assert statuses[10:] == [429, 429]


async def test_an_oversized_or_empty_code_is_a_validation_error(
    tma_client: AsyncClient, session: AsyncSession
) -> None:
    await me(tma_client, session)
    for code in ("", "x" * 65):
        r = await tma_client.post("/api/tma/promo/redeem", json={"code": code})
        assert r.status_code == 422
