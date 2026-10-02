from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import TemplateError
from ocmanager.notifications.service import enqueue

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


async def queue(session: AsyncSession, **over: Any) -> bool:
    fields: dict[str, Any] = {
        "recipient_type": "client",
        "chat_id": 42,
        "template_key": "expired",
        "lang": "ru",
        "payload": {},
    } | over
    return await enqueue(session, **fields)


async def count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(OutboxMessage)) or 0


async def test_enqueue_stores_a_pending_message(session: AsyncSession) -> None:
    with time_machine.travel(NOW, tick=False):
        assert await queue(session, template_key="device_issued", payload={"device": "iPhone"})
    [row] = (await session.scalars(select(OutboxMessage))).all()
    assert (row.recipient_type, row.chat_id, row.template_key, row.lang) == (
        "client",
        42,
        "device_issued",
        "ru",
    )
    assert row.payload == {"device": "iPhone"}
    assert (row.status, row.attempts, row.sent_at, row.last_error) == ("pending", 0, None, None)
    assert row.send_after == NOW


async def test_send_after_can_be_postponed(session: AsyncSession) -> None:
    later = NOW + timedelta(hours=2)
    await queue(session, send_after=later)
    [row] = (await session.scalars(select(OutboxMessage))).all()
    assert row.send_after == later


async def test_enqueue_with_the_same_dedupe_key_for_the_same_chat_is_a_duplicate(
    session: AsyncSession,
) -> None:
    assert await queue(session, dedupe_key="expired:client:1") is True
    assert await queue(session, dedupe_key="expired:client:1") is False
    assert await count(session) == 1


async def test_the_same_dedupe_key_for_another_chat_is_not_a_duplicate(
    session: AsyncSession,
) -> None:
    assert await queue(session, chat_id=1, dedupe_key="node_down:1") is True
    assert await queue(session, chat_id=2, dedupe_key="node_down:1") is True
    assert await count(session) == 2


async def test_messages_without_a_dedupe_key_never_collide(session: AsyncSession) -> None:
    assert await queue(session) is True
    assert await queue(session) is True
    assert await count(session) == 2


async def test_enqueue_refuses_a_payload_the_template_cannot_render(
    session: AsyncSession,
) -> None:
    with pytest.raises(TemplateError, match="device"):
        await queue(session, template_key="device_issued", payload={})
    assert await count(session) == 0


async def test_enqueue_refuses_an_unknown_template_or_language(session: AsyncSession) -> None:
    with pytest.raises(TemplateError):
        await queue(session, template_key="nope")
    with pytest.raises(TemplateError):
        await queue(session, lang="de")
    assert await count(session) == 0
