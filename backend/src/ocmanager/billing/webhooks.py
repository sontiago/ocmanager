"""Приём вебхука провайдера: сырое тело → запись → ответ. Бизнес-логика — в воркере
(flows/purchase.py): любой баг в ней не должен превращаться в шторм повторов от провайдера."""

import json
import secrets
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import WebhookEvent
from ocmanager.billing.providers.base import PaymentProvider
from ocmanager.events import bus
from ocmanager.events.types import WebhookRejected

MAX_BODY_BYTES = 256 * 1024


@dataclass(frozen=True)
class Intake:
    outcome: Literal["accepted", "duplicate", "rejected"]
    webhook_event_id: int | None


def json_object(body: bytes) -> dict[str, Any]:
    """Тело как JSON-объект или `{}`. Разбор не должен ронять приём: не-JSON, вложенность глубже
    лимита рекурсии и `\\u0000` (JSONB его не хранит, insert упал бы ошибкой БД) дают `{}`.
    Сырое тело при этом сохраняется всегда — по нему видно, что пришло."""
    if b"\\u0000" in body:
        return {}
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


async def receive(
    session: AsyncSession, provider: PaymentProvider, body: bytes, *, verified: bool
) -> Intake:
    """Записывает вебхук. Коммит и постановка в очередь — у вызывающего.

    Неверная подпись: строка `rejected` со случайным идентификатором (чтобы подделка не заняла
    идентификатор настоящего события) и событие WebhookRejected для алерта (Фаза 6).
    Повтор уже принятого тела: ничего не пишется — `ON CONFLICT DO NOTHING` атомарен, два
    одновременных повтора не дадут дубля."""
    if not verified:
        rejected = WebhookEvent(
            provider=provider.name,
            external_event_id=f"rejected:{secrets.token_hex(8)}",
            signature_ok=False,
            payload={},
            raw_body=body,
            status="rejected",
        )
        session.add(rejected)
        await session.flush()
        await bus.record(session, WebhookRejected(webhook_event_id=rejected.id))
        return Intake("rejected", rejected.id)

    payload = json_object(body)
    stmt = (
        insert(WebhookEvent)
        .values(
            provider=provider.name,
            external_event_id=provider.event_id(body, payload),
            signature_ok=True,
            payload=payload,
            raw_body=body,
            status="received",
        )
        .on_conflict_do_nothing(
            index_elements=[WebhookEvent.provider, WebhookEvent.external_event_id]
        )
        .returning(WebhookEvent.id)
    )
    new_id = await session.scalar(stmt)
    if new_id is None:
        return Intake("duplicate", None)
    return Intake("accepted", new_id)
