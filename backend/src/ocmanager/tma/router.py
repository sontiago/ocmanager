"""Публичный API для Mini App: `/api/tma/*`."""

from fastapi import APIRouter, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing import plans as plan_service
from ocmanager.billing.models import Plan
from ocmanager.core import ratelimit
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import (
    InvalidTransition,
    NotFound,
    SubscriptionInactive,
    TrialAlreadyUsed,
)
from ocmanager.flows import devices as device_flows
from ocmanager.flows import trial as trial_flow
from ocmanager.flows.deps import CaDep, FernetDep, RedisDep, SettingsDep, commit_and_kick
from ocmanager.flows.nodes import online_usernames
from ocmanager.nodes import traffic
from ocmanager.provisioning import delivery
from ocmanager.provisioning import service as provisioning
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Subscription
from ocmanager.tma.deps import CurrentClient, TmaContext
from ocmanager.tma.schemas import (
    ConnectionOut,
    CreateDeviceIn,
    DeviceOut,
    IssuedDeviceOut,
    MeOut,
    PlanOut,
    SubscriptionEnvelope,
    SubscriptionOut,
)

router = APIRouter(prefix="/tma", tags=["tma"])

# Лимиты на действия, которые создают строки и ключи (решение об анти-абьюзе, дорожная карта 4.3).
TRIAL_LIMIT, TRIAL_WINDOW_S = 3, 3600
DEVICE_LIMIT, DEVICE_WINDOW_S = 10, 3600
MAX_ID_DIGITS = 18  # 18 цифр всегда влезают в BIGINT
MIN_TOKEN_LEN, MAX_TOKEN_LEN = 16, 128


@router.get("/me")
async def get_me(ctx: CurrentClient, db: SessionDep) -> MeOut:
    sub = await subscriptions.get_subscription(db, ctx.client.id)
    return MeOut.of(ctx.client, lang=ctx.lang, has_subscription=sub is not None)


@router.get("/plans")
async def list_plans(ctx: CurrentClient, db: SessionDep) -> list[PlanOut]:
    return [PlanOut.of(p, ctx.lang) for p in await plan_service.list_catalog(db)]


async def subscription_out(db: AsyncSession, sub: Subscription, ctx: TmaContext) -> SubscriptionOut:
    plan = await db.get(Plan, sub.plan_id)
    assert plan is not None  # внешний ключ
    used = await provisioning.count_active(db, ctx.client.id)
    return SubscriptionOut.of(sub, plan, lang=ctx.lang, devices_used=used)


@router.get("/subscription")
async def get_subscription(ctx: CurrentClient, db: SessionDep) -> SubscriptionEnvelope:
    sub = await subscriptions.get_subscription(db, ctx.client.id)
    if sub is None:
        return SubscriptionEnvelope(subscription=None)
    return SubscriptionEnvelope(subscription=await subscription_out(db, sub, ctx))


@router.post("/subscription/trial")
async def start_trial(ctx: CurrentClient, db: SessionDep, redis: RedisDep) -> SubscriptionOut:
    await ratelimit.hit(redis, f"trial:{ctx.client.id}", limit=TRIAL_LIMIT, window_s=TRIAL_WINDOW_S)
    try:
        sub = await trial_flow.start_trial(
            db, client_id=ctx.client.id, actor=ctx.actor, now=utcnow()
        )
    except InvalidTransition:
        # Подписка уже есть (например, выдана из админки): для Mini App это тот же отказ.
        raise TrialAlreadyUsed("a subscription already exists") from None
    out = await subscription_out(db, sub, ctx)
    await commit_and_kick(db, redis)
    return out


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


def _device_id(raw: str) -> int:
    """Идентификатор из пути. Мусор — это `not_found`, а не 422: такого кода у Mini App нет."""
    if not (raw.isascii() and raw.isdigit() and 0 < len(raw) <= MAX_ID_DIGITS):
        raise NotFound("device not found")
    return int(raw)


@router.get("/devices")
async def list_devices(ctx: CurrentClient, db: SessionDep, redis: RedisDep) -> list[DeviceOut]:
    devices = await provisioning.list_devices(db, ctx.client.id)
    sub = await subscriptions.get_subscription(db, ctx.client.id)
    names = [d.ocserv_username for d in devices]
    used = (
        await traffic.usage_since(db, names, sub.traffic_period_start)
        if sub is not None
        else dict.fromkeys(names, 0)
    )
    online = await online_usernames(db, redis) or set()  # нет кэша — «не подключён»
    return [
        DeviceOut.of(
            d, is_online=d.ocserv_username in online, traffic_used_bytes=used[d.ocserv_username]
        )
        for d in devices
    ]


@router.post("/devices")
async def create_device(
    body: CreateDeviceIn,
    response: Response,
    ctx: CurrentClient,
    db: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    ca: CaDep,
    fernet: FernetDep,
) -> IssuedDeviceOut:
    """Пароль и ссылка отдаются один раз, поэтому ответ нельзя кэшировать нигде по пути."""
    await ratelimit.hit(
        redis, f"device:{ctx.client.id}", limit=DEVICE_LIMIT, window_s=DEVICE_WINDOW_S
    )
    bundle = await device_flows.issue_for_client(
        db,
        redis,
        client_id=ctx.client.id,
        name=body.name,
        platform=body.platform,
        ca=ca,
        fernet=fernet,
        actor=ctx.actor,
        now=utcnow(),
    )
    await commit_and_kick(db, redis)
    response.headers["Cache-Control"] = "no-store"
    return IssuedDeviceOut(
        device=DeviceOut.of(bundle.device, is_online=False, traffic_used_bytes=0),
        p12_password=bundle.password,
        download_url=f"{settings.public_base_url}/api/tma/download/{bundle.ticket.token}",
        download_expires_at=bundle.ticket.expires_at,
    )


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    ctx: CurrentClient,
    db: SessionDep,
    redis: RedisDep,
) -> Response:
    """Чужое и несуществующее устройство неотличимы: оба — `not_found`. Повтор безвреден."""
    await device_flows.revoke_for_client(
        db,
        client_id=ctx.client.id,
        device_id=_device_id(device_id),
        actor=ctx.actor,
        now=utcnow(),
    )
    await commit_and_kick(db, redis)
    return Response(status_code=204)


@router.get("/download/{token}")
async def download_p12(token: str, redis: RedisDep, fernet: FernetDep) -> Response:
    """Без initData: ссылку открывают вне Mini App (системный браузер, менеджер загрузок).
    Право на скачивание — сам одноразовый токен на 256 бит; повтор и просрочка — 404."""
    # Длина проверяется здесь, а не в Path(): 422 у Mini App нет кода, а тут нужен обычный 404.
    plausible = MIN_TOKEN_LEN <= len(token) <= MAX_TOKEN_LEN
    taken = await delivery.take_p12(redis, fernet, token) if plausible else None
    if taken is None:
        raise NotFound("link expired or already used")
    filename, data = taken
    return Response(
        data,
        media_type="application/x-pkcs12",
        headers={
            # filename — это ocserv-username (c1-d1.p12): ASCII, экранировать нечего.
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
