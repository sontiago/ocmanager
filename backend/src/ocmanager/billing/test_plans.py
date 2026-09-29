from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing import plans
from ocmanager.billing.models import Plan
from ocmanager.billing.plans import PlanCreate, PlanUpdate
from ocmanager.core.errors import Conflict, InvalidInput, NotFound

GIB = 1024**3


@pytest.fixture(autouse=True)
async def no_seeded_plans(session: AsyncSession) -> None:
    """Миграция сеет скрытый тариф trial; здесь тесты считают тарифы с нуля.
    Удаление откатывается вместе с транзакцией теста."""
    await session.execute(text("DELETE FROM plans"))


def payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": "m1",
        "name_i18n": {"ru": "Месяц", "en": "Month"},
        "duration_days": 30,
        "device_limit": 3,
        "traffic_limit_bytes": 100 * GIB,
        "price_amount": 19900,
        "currency": "RUB",
    }
    return base | over


async def make(session: AsyncSession, **over: Any) -> Plan:
    return await plans.create_plan(session, PlanCreate(**payload(**over)))


async def test_create_normalizes_and_defaults(session: AsyncSession) -> None:
    plan = await make(session, currency=" rub ", name_i18n={"ru": " Месяц ", "en": "Month"})
    assert plan.currency == "RUB"
    assert plan.name_i18n["ru"] == "Месяц"
    assert (plan.is_active, plan.is_trial, plan.sort_order) == (True, False, 0)
    assert plan.provider_product_ids == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"name_i18n": {"ru": "Месяц"}},
        {"name_i18n": {"ru": "Месяц", "en": "  "}},
        {"code": "M1"},
        {"code": "x"},
        {"currency": "RU"},
        {"currency": "рубль"},
        {"price_amount": -1},
        {"duration_days": 0},
        {"device_limit": 0},
        {"traffic_limit_bytes": 0},
        {"duration_days": plans.MAX_DURATION_DAYS + 1},  # иначе дата уходит за 9999 год
        {"duration_days": 999_999_999},
        {"device_limit": plans.MAX_DEVICE_LIMIT + 1},
        {"price_amount": plans.MAX_PRICE + 1},
        {"price_amount": 2**63},  # BIGINT переполнился бы
        {"traffic_limit_bytes": plans.MAX_BYTES + 1},
        {"speed_limit_kbps": plans.MAX_SPEED_KBPS + 1},
        {"unknown_field": 1},
    ],
)
def test_create_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanCreate(**payload(**bad))


async def test_duplicate_code_is_conflict_and_transaction_survives(
    session: AsyncSession,
) -> None:
    await make(session)
    with pytest.raises(Conflict):
        await make(session)
    assert len(await plans.list_all(session)) == 1  # сессия ещё жива


async def test_catalog_hides_trial_and_inactive_and_sorts(
    session: AsyncSession,
) -> None:
    await make(session, code="y1", sort_order=2)
    await make(session, code="m3", sort_order=1)
    await make(session, code="old", is_active=False)
    await session.execute(
        text(
            "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
            " currency, is_trial, is_active) VALUES ('trial-x', '{}', 3, 1, 0, 'RUB', true, false)"
        )
    )
    assert [p.code for p in await plans.list_catalog(session)] == ["m3", "y1"]
    assert {p.code for p in await plans.list_all(session)} == {
        "y1",
        "m3",
        "old",
        "trial-x",
    }


async def test_second_trial_plan_is_rejected_by_database(session: AsyncSession) -> None:
    insert = (
        "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
        " currency, is_trial) VALUES (:c, '{}', 3, 1, 0, 'RUB', true)"
    )
    async with session.begin_nested():
        await session.execute(text(insert), {"c": "trial-a"})
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text(insert), {"c": "trial-b"})


async def test_trial_plan_lookup_finds_the_hidden_plan(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO plans (code, name_i18n, duration_days, device_limit, price_amount,"
            " currency, is_trial, is_active) VALUES ('trial', '{}', 3, 1, 0, 'RUB', true, false)"
        )
    )
    assert (await plans.get_trial_plan(session)).code == "trial"


async def test_lookups(session: AsyncSession) -> None:
    plan = await make(session)
    assert (await plans.get_by_code(session, "m1")).id == plan.id
    assert (await plans.get_by_id(session, plan.id)).code == "m1"
    with pytest.raises(NotFound):
        await plans.get_by_code(session, "nope")
    with pytest.raises(NotFound):
        await plans.get_by_id(session, 999_999)


async def test_update_reports_only_real_changes(session: AsyncSession) -> None:
    await make(session)
    change = await plans.update_plan(
        session, "m1", PlanUpdate(price_amount=24900, device_limit=3, is_active=False)
    )
    assert change.changed == {
        "price_amount": (19900, 24900),
        "is_active": (True, False),
    }
    assert change.plan.price_amount == 24900


async def test_update_can_make_traffic_unlimited(session: AsyncSession) -> None:
    await make(session)
    change = await plans.update_plan(session, "m1", PlanUpdate(traffic_limit_bytes=None))
    assert change.plan.traffic_limit_bytes is None
    assert change.changed == {"traffic_limit_bytes": (100 * GIB, None)}


@pytest.mark.parametrize(
    "bad",
    [
        {"duration_days": plans.MAX_DURATION_DAYS + 1},
        {"device_limit": plans.MAX_DEVICE_LIMIT + 1},
        {"price_amount": plans.MAX_PRICE + 1},
        {"traffic_limit_bytes": plans.MAX_BYTES + 1},
        {"speed_limit_kbps": plans.MAX_SPEED_KBPS + 1},
    ],
)
def test_update_has_the_same_ceilings(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanUpdate(**bad)


def test_the_ceilings_themselves_are_allowed() -> None:
    PlanCreate(
        **payload(
            duration_days=plans.MAX_DURATION_DAYS,
            device_limit=plans.MAX_DEVICE_LIMIT,
            price_amount=plans.MAX_PRICE,
            traffic_limit_bytes=plans.MAX_BYTES,
            speed_limit_kbps=plans.MAX_SPEED_KBPS,
        )
    )


def test_update_rejects_nulling_required_and_immutable_fields() -> None:
    with pytest.raises(ValidationError):
        PlanUpdate(price_amount=None)
    with pytest.raises(ValidationError):
        PlanUpdate(name_i18n={"ru": "Месяц"})
    with pytest.raises(ValidationError):
        PlanUpdate(is_trial=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        PlanUpdate(code="other")  # type: ignore[call-arg]


async def test_update_needs_something_and_a_real_plan(session: AsyncSession) -> None:
    await make(session)
    with pytest.raises(InvalidInput):
        await plans.update_plan(session, "m1", PlanUpdate())
    with pytest.raises(NotFound):
        await plans.update_plan(session, "nope", PlanUpdate(sort_order=1))


async def test_trial_plan_lookup_needs_the_plan(session: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await plans.get_trial_plan(session)
