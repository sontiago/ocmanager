from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.notifications import tasks
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import render

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
TOKEN = "123456:secret-bot-token"
OK = (200, {"ok": True, "result": {}})


class FakeTelegram:
    """Подменяет Bot API: отвечает заданными (статус, тело) по очереди, последний — навсегда."""

    def __init__(self, *responses: tuple[int, dict[str, Any]]) -> None:
        self.responses = list(responses) or [OK]
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.AsyncClient:
        def respond(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status, body = self.responses[min(len(self.requests), len(self.responses)) - 1]
            return httpx.Response(status, json=body)

        return httpx.AsyncClient(transport=httpx.MockTransport(respond))


async def add(session: AsyncSession, **over: Any) -> OutboxMessage:
    fields: dict[str, Any] = {
        "recipient_type": "client",
        "chat_id": 42,
        "template_key": "expired",
        "lang": "ru",
        "payload": {},
        "send_after": NOW,
    } | over
    row = OutboxMessage(**fields)
    session.add(row)
    await session.flush()
    await session.commit()
    return row


async def run(
    sessionmaker: async_sessionmaker[AsyncSession], telegram: FakeTelegram, **kwargs: Any
) -> int:
    async with telegram.client() as http:
        return await tasks.send_pending(sessionmaker, http, TOKEN, pause=0, **kwargs)


async def test_a_pending_message_is_rendered_sent_and_marked(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session, template_key="device_issued", payload={"device": "iPhone"})
    telegram = FakeTelegram()

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1

    await session.refresh(row)
    assert (row.status, row.sent_at, row.attempts, row.last_error) == ("sent", NOW, 0, None)
    [request] = telegram.requests
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert (
        request.content
        == httpx.Request(
            "POST",
            "http://x",
            json={"chat_id": 42, "text": render("device_issued", "ru", {"device": "iPhone"})},
        ).content
    )


async def test_a_sent_message_is_not_sent_again(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1
        assert await run(sessionmaker, telegram) == 0
    assert len(telegram.requests) == 1


async def test_a_message_scheduled_for_later_waits(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session, send_after=NOW + timedelta(minutes=5))
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
    assert telegram.requests == []


async def test_messages_go_out_oldest_first(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session, chat_id=1)
    await add(session, chat_id=2)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 2
    text = render("expired", "ru", {})
    assert [r.content for r in telegram.requests] == [
        httpx.Request("POST", "http://x", json={"chat_id": chat, "text": text}).content
        for chat in (1, 2)
    ]


async def test_403_is_undeliverable_and_never_retried(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)
    telegram = FakeTelegram((403, {"ok": False, "description": "Forbidden: bot was blocked"}))

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
        assert await run(sessionmaker, telegram) == 0

    await session.refresh(row)
    assert (row.status, row.attempts) == ("undeliverable", 0)
    assert row.last_error is not None
    assert "blocked" in row.last_error
    assert len(telegram.requests) == 1


async def test_a_server_error_backs_off_and_the_tenth_failure_is_final(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)
    telegram = FakeTelegram((500, {"ok": False}), OK)

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
        await session.refresh(row)
        assert (row.status, row.attempts) == ("pending", 1)
        assert row.send_after == NOW + timedelta(seconds=2)
        assert await run(sessionmaker, telegram) == 0  # пауза ещё не прошла
        assert len(telegram.requests) == 1

    with time_machine.travel(NOW + timedelta(seconds=3), tick=False):
        assert await run(sessionmaker, telegram) == 1  # второй ответ — OK
    await session.refresh(row)
    assert row.status == "sent"

    last = await add(session, attempts=tasks.MAX_ATTEMPTS - 1)
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, FakeTelegram((500, {"ok": False}))) == 0
    await session.refresh(last)
    assert (last.status, last.attempts) == ("failed", tasks.MAX_ATTEMPTS)


async def test_backoff_is_capped() -> None:
    assert tasks.backoff(1) == timedelta(seconds=2)
    assert tasks.backoff(5) == timedelta(seconds=32)
    assert tasks.backoff(30) == timedelta(seconds=tasks.MAX_BACKOFF_S)


async def test_429_reschedules_by_retry_after_and_stops_the_batch(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await add(session, chat_id=1)
    second = await add(session, chat_id=2)
    telegram = FakeTelegram(
        (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}})
    )

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0

    await session.refresh(first)
    await session.refresh(second)
    assert len(telegram.requests) == 1  # вторую даже не пробовали
    assert (first.status, first.attempts, first.send_after) == (
        "pending",
        0,
        NOW + timedelta(seconds=7),
    )
    assert (second.status, second.attempts, second.send_after) == ("pending", 0, NOW)


async def test_an_unrenderable_message_fails_without_blocking_the_queue(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    broken = await add(session, template_key="no_such_template")
    fine = await add(session, chat_id=7)
    telegram = FakeTelegram()

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1

    await session.refresh(broken)
    await session.refresh(fine)
    assert broken.status == "failed"
    assert broken.last_error is not None
    assert "no_such_template" in broken.last_error
    assert fine.status == "sent"
    assert len(telegram.requests) == 1


async def test_a_failed_send_does_not_leak_the_token_into_last_error(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        with time_machine.travel(NOW, tick=False):
            await tasks.send_pending(sessionmaker, http, TOKEN, pause=0)

    await session.refresh(row)
    assert row.last_error == "ConnectError"


async def test_the_batch_size_limits_one_run(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    for chat in (1, 2, 3):
        await add(session, chat_id=chat)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram, batch=2) == 2
        assert await run(sessionmaker, telegram, batch=2) == 1
