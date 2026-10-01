from datetime import UTC, datetime

import pytest
from conftest import MakeClient, MakePlan
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing import service
from ocmanager.billing.models import Payment, Plan
from ocmanager.core.errors import NotFound

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


async def record(session: AsyncSession, client_id: int, **over: object) -> Payment | None:
    fields: dict[str, object] = {
        "provider": "tribute",
        "external_id": "p1",
        "client_id": client_id,
        "plan_id": None,
        "amount": 19900,
        "currency": "RUB",
        "payload": {"k": "v"},
        "now": NOW,
    } | over
    return await service.record_payment(session, **fields)  # type: ignore[arg-type]


async def count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Payment)) or 0)


async def test_a_payment_is_recorded_once(session: AsyncSession, make_client: MakeClient) -> None:
    client = await make_client()
    first = await record(session, client.id)
    second = await record(session, client.id)
    assert first is not None
    assert second is None
    assert await count(session) == 1
    assert (first.status, first.processed_at, first.raw_payload) == ("succeeded", None, {"k": "v"})
    assert first.received_at == NOW


async def test_the_same_external_id_at_another_provider_is_another_payment(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    assert await record(session, client.id) is not None
    assert await record(session, client.id, provider="stars") is not None
    assert await count(session) == 2


async def test_a_payment_can_be_fetched_by_its_external_id(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    saved = await record(session, client.id)
    assert saved is not None
    assert (await service.get_payment(session, "tribute", "p1")).id == saved.id
    with pytest.raises(NotFound):
        await service.get_payment(session, "tribute", "nope")


async def test_a_refund_marks_the_payment_once(
    session: AsyncSession, make_client: MakeClient
) -> None:
    client = await make_client()
    await record(session, client.id)
    first = await service.mark_refunded(session, "tribute", "p1")
    again = await service.mark_refunded(session, "tribute", "p1")
    assert first is not None
    assert again is not None
    assert (first.changed, first.payment.status) == (True, "refunded")
    assert (again.changed, again.payment.status) == (False, "refunded")


async def test_a_refund_of_an_unknown_payment_is_none(session: AsyncSession) -> None:
    assert await service.mark_refunded(session, "tribute", "nope") is None


async def test_a_plan_is_found_by_the_product_of_the_provider(
    session: AsyncSession, make_plan: MakePlan
) -> None:
    plan = await make_plan(provider_product_ids={"tribute": {"product_ref": "1001"}})
    other = await make_plan(provider_product_ids={"tribute": {"product_ref": "2002"}})
    assert (await service.find_plan_by_product(session, "tribute", "1001")) == plan
    assert (await service.find_plan_by_product(session, "tribute", "2002")) == other
    assert await service.find_plan_by_product(session, "tribute", "3003") is None


async def test_the_product_is_looked_up_under_the_right_provider_only(
    session: AsyncSession, make_plan: MakePlan
) -> None:
    await make_plan(provider_product_ids={"stars": {"product_ref": "1001"}})
    assert await service.find_plan_by_product(session, "tribute", "1001") is None


async def test_an_inactive_plan_is_still_found_because_somebody_has_already_paid(
    session: AsyncSession, make_plan: MakePlan
) -> None:
    plan = await make_plan(
        provider_product_ids={"tribute": {"product_ref": "1001"}}, is_active=False
    )
    assert (await service.find_plan_by_product(session, "tribute", "1001")) == plan


async def test_the_hidden_trial_plan_is_never_matched(
    session: AsyncSession, trial_plan: Plan
) -> None:
    trial_plan.provider_product_ids = {"tribute": {"product_ref": "1001"}}
    await session.flush()
    assert await service.find_plan_by_product(session, "tribute", "1001") is None
