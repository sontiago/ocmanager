"""Публичный API для Mini App: `/api/tma/*`."""

from fastapi import APIRouter

from ocmanager.billing import plans as plan_service
from ocmanager.billing.models import Plan
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import SubscriptionInactive
from ocmanager.flows.deps import SettingsDep
from ocmanager.provisioning import service as provisioning
from ocmanager.subscriptions import service as subscriptions
from ocmanager.tma.deps import CurrentClient
from ocmanager.tma.schemas import (
    ConnectionOut,
    MeOut,
    PlanOut,
    SubscriptionEnvelope,
    SubscriptionOut,
)

router = APIRouter(prefix="/tma", tags=["tma"])


@router.get("/me")
async def get_me(ctx: CurrentClient, db: SessionDep) -> MeOut:
    sub = await subscriptions.get_subscription(db, ctx.client.id)
    return MeOut.of(ctx.client, lang=ctx.lang, has_subscription=sub is not None)


@router.get("/plans")
async def list_plans(ctx: CurrentClient, db: SessionDep) -> list[PlanOut]:
    return [PlanOut.of(p, ctx.lang) for p in await plan_service.list_catalog(db)]


@router.get("/subscription")
async def get_subscription(ctx: CurrentClient, db: SessionDep) -> SubscriptionEnvelope:
    sub = await subscriptions.get_subscription(db, ctx.client.id)
    if sub is None:
        return SubscriptionEnvelope(subscription=None)
    plan = await db.get(Plan, sub.plan_id)
    assert plan is not None  # внешний ключ
    used = await provisioning.count_active(db, ctx.client.id)
    return SubscriptionEnvelope(
        subscription=SubscriptionOut.of(sub, plan, lang=ctx.lang, devices_used=used)
    )


@router.get("/connection")
async def get_connection(ctx: CurrentClient, settings: SettingsDep) -> ConnectionOut:
    """Адрес шлюза с камуфляжным секретом. Заблокированному не выдаётся."""
    if ctx.client.is_blocked:
        raise SubscriptionInactive("client is blocked", blocked=True)
    port = "" if settings.vpn_port == 443 else f":{settings.vpn_port}"
    secret = settings.camouflage_secret.get_secret_value()
    return ConnectionOut(
        server_host=settings.vpn_host,
        gateway_url=f"https://{settings.vpn_host}{port}/?{secret}",
    )
