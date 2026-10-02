"""Доставка очереди outbox_messages в Telegram.

Каждое сообщение — своя транзакция: строка берётся FOR UPDATE SKIP LOCKED (параллельные запуски
не шлют одно и то же), после ответа Telegram статус коммитится сразу. Падение процесса между
отправкой и коммитом дублирует максимум одно сообщение, а не пачку.
"""

import asyncio
from datetime import datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.clock import utcnow
from ocmanager.notifications import telegram
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import TemplateError, render
from ocmanager.notifications.telegram import SendOutcome, SendResult

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 10
MAX_BACKOFF_S = 600
ERROR_LIMIT = 500
# Глобальный лимит Telegram — 30 сообщений в секунду; идём с запасом.
SEND_PAUSE_S = 0.04


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts, MAX_BACKOFF_S))


async def _send_one(
    session: AsyncSession, http: httpx.AsyncClient, bot_token: str, now: datetime
) -> SendResult | None:
    """None — очередь пуста. Иначе результат попытки (для подсчёта и для 429)."""
    row = await session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.status == "pending", OutboxMessage.send_after <= now)
        .order_by(OutboxMessage.send_after, OutboxMessage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    try:
        text = render(row.template_key, row.lang, row.payload)
    except TemplateError as exc:
        # Шаблон удалён или payload не подходит: отправить это сообщение нельзя никогда.
        row.status = "failed"
        row.last_error = str(exc)[:ERROR_LIMIT]
        log.error("notification_unrenderable", message_id=row.id, error=str(exc))
        return SendResult(SendOutcome.UNDELIVERABLE, error=row.last_error)

    result = await telegram.send_message(http, bot_token, row.chat_id, text)
    if result.outcome is SendOutcome.SENT:
        row.status = "sent"
        row.sent_at = now
        row.last_error = None
    elif result.outcome is SendOutcome.UNDELIVERABLE:
        row.status = "undeliverable"
        row.last_error = result.error
        log.info("notification_undeliverable", message_id=row.id, error=result.error)
    elif result.retry_after is not None:
        # Просьба Telegram притормозить — не сбой сообщения: попытка не считается.
        row.send_after = now + timedelta(seconds=result.retry_after)
    else:
        row.attempts += 1
        row.last_error = result.error
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            log.warning("notification_failed", message_id=row.id, error=result.error)
        else:
            row.send_after = now + backoff(row.attempts)
    return result


async def send_pending(
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    bot_token: str,
    *,
    batch: int = 50,
    pause: float = SEND_PAUSE_S,
) -> int:
    """Отправляет до `batch` готовых сообщений. Возвращает число отправленных."""
    sent = 0
    for _ in range(batch):
        async with sessionmaker() as session, session.begin():
            result = await _send_one(session, http, bot_token, utcnow())
        if result is None:
            break
        if result.outcome is SendOutcome.SENT:
            sent += 1
        if result.retry_after is not None:
            break  # Telegram просит паузу для всей очереди, а не для одного сообщения
        await asyncio.sleep(pause)
    return sent
