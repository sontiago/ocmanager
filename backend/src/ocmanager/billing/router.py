"""POST /webhooks/{provider} — единственный вход платёжных провайдеров.

Импортирует только core и events (граница модулей), поэтому зависимости FastAPI здесь свои,
а не из flows/deps."""

from typing import Annotated

import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, Request

from ocmanager.billing import webhooks
from ocmanager.billing.providers import get_provider
from ocmanager.core import ratelimit
from ocmanager.core.config import Settings
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import InvalidInput, NotFound, Unauthorized
from ocmanager.core.redis import get_redis
from ocmanager.events import bus

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Запись подделок ограничена: флуд с неверной подписью не должен заполнять таблицу (П5-6).
REJECTED_LIMIT, REJECTED_WINDOW_S = 30, 60

RedisDep = Annotated[ArqRedis, Depends(get_redis)]


@router.post("/{provider_name}")
async def receive_webhook(
    provider_name: str, request: Request, db: SessionDep, redis: RedisDep
) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    provider = get_provider(provider_name, settings)
    if provider is None:
        raise NotFound("unknown provider")

    # Лимит по заголовку — чтобы не читать заведомо огромное тело; по факту — на случай
    # chunked-запроса без Content-Length (потолок для него ставит прокси, Фаза 7).
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > webhooks.MAX_BODY_BYTES:
        raise InvalidInput("body too large")
    body = await request.body()
    if len(body) > webhooks.MAX_BODY_BYTES:
        raise InvalidInput("body too large")

    verified = provider.verify(body, request.headers)
    if not verified:
        await ratelimit.hit(
            redis,
            f"webhook_rejected:{provider.name}",
            limit=REJECTED_LIMIT,
            window_s=REJECTED_WINDOW_S,
        )
    intake = await webhooks.receive(db, provider, body, verified=verified)
    await db.commit()

    if intake.outcome == "rejected":
        log.warning(
            "webhook_rejected", provider=provider.name, webhook_event_id=intake.webhook_event_id
        )
        await bus.kick_dispatch(redis)  # событие WebhookRejected — в обработчики без ожидания cron
        raise Unauthorized("bad signature")
    if intake.outcome == "duplicate":
        return {"status": "duplicate"}
    try:
        await redis.enqueue_job("process_webhook", intake.webhook_event_id)
    except Exception as exc:
        # Тело уже в БД: провайдеру — 200, а потерянную постановку подберёт cron (Задача 5.5).
        log.warning(
            "webhook_enqueue_failed", webhook_event_id=intake.webhook_event_id, exc_info=exc
        )
    return {"status": "ok"}
