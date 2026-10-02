"""Очередь исходящих уведомлений. enqueue() кладёт сообщение в outbox_messages в транзакции
вызывающего (commit — у него); отправляет сообщения воркер (tasks.py)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import render


async def enqueue(
    session: AsyncSession,
    *,
    recipient_type: Literal["client", "admin"],
    chat_id: int,
    template_key: str,
    lang: str,
    payload: Mapping[str, Any],
    dedupe_key: str | None = None,
    send_after: datetime | None = None,
) -> bool:
    """False — такое сообщение уже в очереди (тот же chat_id и dedupe_key).

    Шаблон рендерится вхолостую: ошибка в шаблоне или payload падает здесь, в обработчике
    события (оно уйдёт на повтор и будет видно в event_outbox), а не при отправке."""
    render(template_key, lang, payload)
    stmt = (
        insert(OutboxMessage)
        .values(
            recipient_type=recipient_type,
            chat_id=chat_id,
            template_key=template_key,
            lang=lang,
            payload=dict(payload),
            dedupe_key=dedupe_key,
            send_after=send_after or utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_outbox_messages_chat_id_dedupe_key")
        .returning(OutboxMessage.id)
    )
    return await session.scalar(stmt) is not None
