"""Каталог тарифов. Аудит здесь не пишется (граница модулей) — его пишет flows/plans.py."""

from dataclasses import dataclass
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Plan
from ocmanager.core.errors import Conflict, InvalidInput, NotFound

I18N_LANGS = ("ru", "en")
CODE_PATTERN = r"^[a-z0-9_-]{2,32}$"

# Верхние границы. Без них абсурдный ввод админа (`--days 999999999`, цена в триллионах)
# доходит до сдвига даты за 9999 год или до переполнения BIGINT и превращается в ошибку 500.
# MAX_DURATION_DAYS обязан совпадать с subscriptions.state.MAX_DAYS (scripts/test_consistency.py).
MAX_DURATION_DAYS = 3650
MAX_DEVICE_LIMIT = 1000
MAX_PRICE = 10**12  # минорные единицы
MAX_BYTES = 2**62
MAX_SPEED_KBPS = 10**7


def _check_i18n(value: dict[str, str] | None, *, required: bool) -> dict[str, str] | None:
    if value is None:
        return None
    if required:
        missing = [lang for lang in I18N_LANGS if not value.get(lang, "").strip()]
        if missing:
            raise ValueError(f"нужны обе локали, нет: {', '.join(missing)}")
    return {lang: text.strip() for lang, text in value.items()}


def _upper_currency(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError("валюта — код ISO 4217 из трёх букв")
    return code


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CODE_PATTERN)
    name_i18n: dict[str, str]
    description_i18n: dict[str, str] | None = None
    duration_days: int = Field(gt=0, le=MAX_DURATION_DAYS)
    device_limit: int = Field(gt=0, le=MAX_DEVICE_LIMIT)
    traffic_limit_bytes: int | None = Field(None, gt=0, le=MAX_BYTES)
    speed_limit_kbps: int | None = Field(None, gt=0, le=MAX_SPEED_KBPS)
    price_amount: int = Field(ge=0, le=MAX_PRICE)
    currency: str
    provider_product_ids: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    sort_order: int = 0

    @field_validator("name_i18n")
    @classmethod
    def _name(cls, value: dict[str, str]) -> dict[str, str]:
        checked = _check_i18n(value, required=True)
        assert checked is not None
        return checked

    @field_validator("description_i18n")
    @classmethod
    def _description(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_i18n(value, required=False)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _upper_currency(value)


class PlanUpdate(BaseModel):
    """Частичное изменение: меняются только явно переданные поля. code и is_trial
    не меняются. None допустим лишь там, где он значит «не ограничено» или «нет»."""

    model_config = ConfigDict(extra="forbid")

    name_i18n: dict[str, str] | None = None
    description_i18n: dict[str, str] | None = None
    duration_days: int | None = Field(None, gt=0, le=MAX_DURATION_DAYS)
    device_limit: int | None = Field(None, gt=0, le=MAX_DEVICE_LIMIT)
    traffic_limit_bytes: int | None = Field(None, gt=0, le=MAX_BYTES)
    speed_limit_kbps: int | None = Field(None, gt=0, le=MAX_SPEED_KBPS)
    price_amount: int | None = Field(None, ge=0, le=MAX_PRICE)
    currency: str | None = None
    provider_product_ids: dict[str, Any] | None = None
    is_active: bool | None = None
    sort_order: int | None = None

    NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {"description_i18n", "traffic_limit_bytes", "speed_limit_kbps"}
    )

    @field_validator("name_i18n")
    @classmethod
    def _name(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_i18n(value, required=True)

    @field_validator("description_i18n")
    @classmethod
    def _description(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_i18n(value, required=False)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str | None) -> str | None:
        return None if value is None else _upper_currency(value)

    @model_validator(mode="after")
    def _no_null_for_required(self) -> Self:
        nulled = {f for f in self.model_fields_set if getattr(self, f) is None} - self.NULLABLE
        if nulled:
            raise ValueError(f"нельзя обнулить: {', '.join(sorted(nulled))}")
        return self


@dataclass(frozen=True)
class PlanChange:
    plan: Plan
    changed: dict[str, tuple[Any, Any]]  # поле → (было, стало)


async def list_catalog(session: AsyncSession) -> list[Plan]:
    """Что видит клиент: активные, не trial."""
    return list(
        await session.scalars(
            select(Plan).where(Plan.is_active, ~Plan.is_trial).order_by(Plan.sort_order, Plan.id)
        )
    )


async def list_all(session: AsyncSession) -> list[Plan]:
    return list(await session.scalars(select(Plan).order_by(Plan.sort_order, Plan.id)))


async def get_by_code(session: AsyncSession, code: str) -> Plan:
    plan = await session.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise NotFound(f"plan {code!r} not found")
    return plan


async def get_by_id(session: AsyncSession, plan_id: int) -> Plan:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise NotFound("plan not found")
    return plan


async def get_trial_plan(session: AsyncSession) -> Plan:
    plan = await session.scalar(select(Plan).where(Plan.is_trial))
    if plan is None:
        raise NotFound("trial plan not found")
    return plan


async def create_plan(session: AsyncSession, data: PlanCreate) -> Plan:
    plan = Plan(**data.model_dump(), is_trial=False)
    try:
        # SAVEPOINT: дубль code не отравляет транзакцию вызывающего.
        async with session.begin_nested():
            session.add(plan)
    except IntegrityError:
        raise Conflict(f"plan {data.code!r} already exists") from None
    return plan


async def update_plan(session: AsyncSession, code: str, patch: PlanUpdate) -> PlanChange:
    plan = await get_by_code(session, code)
    if not patch.model_fields_set:
        raise InvalidInput("nothing to update")
    changed: dict[str, tuple[Any, Any]] = {}
    for field in patch.model_fields_set:
        old, new = getattr(plan, field), getattr(patch, field)
        if old != new:
            changed[field] = (old, new)
            setattr(plan, field, new)
    await session.flush()
    return PlanChange(plan=plan, changed=changed)
