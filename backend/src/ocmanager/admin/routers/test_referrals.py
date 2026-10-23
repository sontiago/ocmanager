import pytest
from conftest import MakeClient, MakePayment
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.subscriptions import service as subscriptions

ENDPOINTS = ["/admin/referrals/stats", "/admin/referrals/rewards"]


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_a_session_is_required(anon_client: AsyncClient, path: str) -> None:
    assert (await anon_client.get(path)).status_code == 401


async def test_an_empty_system_has_zero_stats(admin_client: AsyncClient) -> None:
    body = (await admin_client.get("/admin/referrals/stats")).json()
    assert body == {
        "invited": 0,
        "paying": 0,
        "conversion_percent": 0,
        "days_given": 0,
        "devices_given": 0,
        "traffic_bytes_given": 0,
        "tiers": [
            {"friends": 3, "reached": 0},
            {"friends": 5, "reached": 0},
            {"friends": 10, "reached": 0},
        ],
    }
    page = (await admin_client.get("/admin/referrals/rewards")).json()
    assert (page["items"], page["total"]) == ([], 0)


async def _reward(
    session: AsyncSession,
    inviter_id: int,
    friend_id: int,
    payment_id: int,
    **over: object,
) -> None:
    fields: dict[str, object] = {
        "inviter_id": inviter_id,
        "invitee_id": friend_id,
        "payment_id": payment_id,
        "kind": "base",
        "days": 7,
        "invitee_days": 3,
        "status": "applied",
    } | over
    await subscriptions.add_reward(session, **fields)


async def test_stats_add_up(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    inviter = await make_client()
    friends = [await make_client() for _ in range(4)]
    for friend in friends:
        await subscriptions.set_referrer(session, friend.id, inviter.referral_code)
    for friend in friends[:3]:
        payment = await make_payment(friend, processed_at=utcnow())
        await _reward(session, inviter.id, friend.id, payment.id)
    tier_payment = await make_payment(friends[2], processed_at=utcnow())
    await _reward(
        session,
        inviter.id,
        friends[2].id,
        tier_payment.id,
        kind="tier",
        tier=3,
        days=30,
        invitee_days=0,
    )
    await _reward(
        session,
        inviter.id,
        friends[2].id,
        tier_payment.id,
        kind="tier",
        tier=5,
        days=0,
        invitee_days=0,
        devices=1,
    )

    body = (await admin_client.get("/admin/referrals/stats")).json()
    assert (body["invited"], body["paying"], body["conversion_percent"]) == (4, 3, 75)
    assert body["days_given"] == 3 * 7 + 3 * 3 + 30  # пригласившим, приглашённым и за уровень
    assert body["devices_given"] == 1
    assert {t["friends"]: t["reached"] for t in body["tiers"]} == {3: 1, 5: 1, 10: 0}


async def test_pending_and_capped_rewards_give_no_days_yet(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    inviter, friend = await make_client(), await make_client()
    payment = await make_payment(friend, processed_at=utcnow())
    await _reward(session, inviter.id, friend.id, payment.id, status="pending", invitee_days=3)
    body = (await admin_client.get("/admin/referrals/stats")).json()
    assert body["days_given"] == 3  # только приглашённому: пригласившему ещё не начислено


async def test_the_reward_log_names_people_and_flags_refunded_payments(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    inviter = await make_client(first_name="Ivan", username="ivan")
    friend = await make_client(first_name="Petr")
    payment = await make_payment(friend, processed_at=utcnow())
    await _reward(session, inviter.id, friend.id, payment.id)
    payment.status = "refunded"
    await session.flush()

    page = (await admin_client.get("/admin/referrals/rewards")).json()
    [row] = page["items"]
    assert (row["inviter_id"], row["inviter_name"], row["invitee_name"]) == (
        inviter.id,
        "Ivan",
        "Petr",
    )
    assert (row["kind"], row["days"], row["status"]) == ("base", 7, "applied")
    assert row["payment_status"] == "refunded"  # админ видит возврат и решает вручную


async def test_the_reward_log_filters_and_pages(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    a, b = await make_client(), await make_client()
    for inviter in (a, a, b):
        friend = await make_client()
        payment = await make_payment(friend, processed_at=utcnow())
        await _reward(session, inviter.id, friend.id, payment.id)
    only_a = (await admin_client.get(f"/admin/referrals/rewards?inviter_id={a.id}")).json()
    assert only_a["total"] == 2
    paged = (await admin_client.get("/admin/referrals/rewards?limit=1&offset=2")).json()
    assert (len(paged["items"]), paged["total"]) == (1, 3)


async def test_the_client_card_shows_the_referral_block(
    admin_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    inviter = await make_client(first_name="Ivan")
    friend = await make_client()
    await subscriptions.set_referrer(session, friend.id, inviter.referral_code)
    payment = await make_payment(friend, processed_at=utcnow())
    await _reward(session, inviter.id, friend.id, payment.id)

    card = (await admin_client.get(f"/admin/clients/{inviter.id}")).json()["referral"]
    assert card["code"] == inviter.referral_code
    assert card["referred_by"] is None
    assert (card["invited"], card["paying_friends"]) == (1, 1)

    friend_card = (await admin_client.get(f"/admin/clients/{friend.id}")).json()["referral"]
    assert friend_card["referred_by"] == {"id": inviter.id, "name": "Ivan"}
