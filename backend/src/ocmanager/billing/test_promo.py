from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing import promo
from ocmanager.core.errors import Conflict, InvalidInput, PromoAlreadyUsed, PromoInvalid

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
DAY = timedelta(days=1)


async def test_codes_are_stored_in_lower_case(session: AsyncSession) -> None:
    created = await promo.create(session, code="Spring-14", kind="days", value=14)
    assert created.code == "spring-14"
    assert (created.uses, created.is_active) == (0, True)


@pytest.mark.parametrize("code", ["ab", "has space", "кириллица", "x" * 33, "bad!"])
async def test_bad_codes_are_rejected(session: AsyncSession, code: str) -> None:
    with pytest.raises(InvalidInput):
        await promo.create(session, code=code, kind="days", value=1)


@pytest.mark.parametrize(
    ("kind", "value"), [("days", 0), ("days", 3651), ("traffic", 0), ("gold", 1)]
)
async def test_bad_values_are_rejected(session: AsyncSession, kind: str, value: int) -> None:
    with pytest.raises(InvalidInput):
        await promo.create(session, code="okcode", kind=kind, value=value)


async def test_a_duplicate_code_conflicts_whatever_its_case(session: AsyncSession) -> None:
    await promo.create(session, code="dup", kind="days", value=1)
    with pytest.raises(Conflict):
        await promo.create(session, code="DUP", kind="days", value=1)


async def test_max_uses_must_be_positive(session: AsyncSession) -> None:
    with pytest.raises(InvalidInput):
        await promo.create(session, code="okcode", kind="days", value=1, max_uses=0)


async def test_claim_records_the_redemption_and_counts_the_use(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    await promo.create(session, code="hello", kind="traffic", value=5000)
    code = await promo.claim(session, client.id, "HELLO", NOW)
    assert (code.kind, code.value, code.uses) == ("traffic", 5000, 1)
    redemptions = await promo.redemptions(session, code.id)
    assert [(r.client_id, r.kind, r.value) for r in redemptions] == [(client.id, "traffic", 5000)]


async def test_a_client_redeems_a_code_once(session: AsyncSession, make_client: MakeClient) -> None:
    client = await make_client()
    await promo.create(session, code="once", kind="days", value=3)
    await promo.claim(session, client.id, "once", NOW)
    with pytest.raises(PromoAlreadyUsed):
        await promo.claim(session, client.id, "once", NOW)


@pytest.mark.parametrize("why", ["unknown", "inactive", "expired", "used_up"])
async def test_unusable_codes_look_the_same(
    session: AsyncSession, make_client: MakeClient, why: str
) -> None:
    first, second = await make_client(), await make_client()
    if why != "unknown":
        created = await promo.create(
            session,
            code="gone",
            kind="days",
            value=3,
            max_uses=1 if why == "used_up" else None,
            expires_at=NOW - DAY if why == "expired" else None,
        )
        if why == "inactive":
            await promo.update(session, created.id, is_active=False)
        if why == "used_up":
            await promo.claim(session, first.id, "gone", NOW)
    with pytest.raises(PromoInvalid):
        await promo.claim(session, second.id, "gone", NOW)


async def test_a_code_is_valid_until_the_expiry_moment(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    await promo.create(session, code="edge", kind="days", value=1, expires_at=NOW + DAY)
    assert (await promo.claim(session, client.id, "edge", NOW)).uses == 1


async def test_update_changes_only_the_given_fields(session: AsyncSession) -> None:
    created = await promo.create(session, code="tweak", kind="days", value=5, max_uses=10)
    updated = await promo.update(session, created.id, max_uses=20)
    assert (updated.max_uses, updated.is_active, updated.value) == (20, True, 5)
    cleared = await promo.update(session, created.id, max_uses=None)
    assert cleared.max_uses is None


async def test_list_shows_the_newest_first(session: AsyncSession) -> None:
    await promo.create(session, code="aaa", kind="days", value=1)
    await promo.create(session, code="bbb", kind="days", value=1)
    assert [p.code for p in await promo.list_all(session)] == ["bbb", "aaa"]
