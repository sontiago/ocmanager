"""Кнопка «Купить»: выбор тарифа → намерение → ссылка на оплату."""

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.billing import plans
from ocmanager.billing import service as billing
from ocmanager.billing.models import Plan
from ocmanager.billing.providers import PROVIDER_NAMES, checkout_url
from ocmanager.core.errors import NotFound, SubscriptionInactive
from ocmanager.subscriptions.models import Client

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Checkout:
    url: str
    intent_id: str


def _link_for(plan: Plan) -> tuple[str, str] | None:
    """Первый провайдер, у которого для тарифа есть безопасная ссылка: (имя, ссылка)."""
    for name in PROVIDER_NAMES:
        url = checkout_url(name, plan.provider_product_ids.get(name))
        if url is not None:
            return name, url
    return None


async def create_checkout(
    session: AsyncSession, *, client: Client, plan_code: str, actor: Actor
) -> Checkout:
    """Заблокированному покупать нельзя (оплата без доступа — ручной разбор, решение №23 карты).
    Тариф, которого нет, скрыт или не привязан к провайдеру, для клиента — просто «не найден»."""
    if client.is_blocked:
        raise SubscriptionInactive("client is blocked", blocked=True)
    plan = await plans.get_by_code(session, plan_code)  # NotFound
    if not plan.is_active or plan.is_trial:
        raise NotFound("plan not found")
    found = _link_for(plan)
    if found is None:
        # Клиент видит «не найдено», админ должен узнать, что тариф в каталоге без ссылки оплаты.
        log.warning("plan_without_payment_link", plan_code=plan.code)
        raise NotFound("plan is not available for purchase")
    provider, url = found
    intent = await billing.create_intent(
        session,
        intent_id=billing.new_intent_id(),
        client_id=client.id,
        plan_id=plan.id,
        provider=provider,
    )
    await audit.record(
        session,
        actor,
        "checkout.create",
        target_type="client",
        target_id=str(client.id),
        details={"plan_code": plan.code, "intent_id": intent.id, "provider": provider},
    )
    return Checkout(url=url, intent_id=intent.id)
