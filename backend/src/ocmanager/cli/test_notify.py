"""`ocmanager notify backup-failed` и `ocmanager settings admin-chat` на настоящей БД."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner, Result

from ocmanager.cli import app
from ocmanager.core import settings_store
from ocmanager.core.config import Settings
from ocmanager.notifications.models import OutboxMessage

runner = CliRunner()
Invoke = Callable[..., Awaitable[Result]]


@pytest.fixture
def invoke(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Invoke:
    monkeypatch.setenv("OCM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("OCM_LOG_LEVEL", "WARNING")

    async def run(*args: str) -> Result:
        return await asyncio.to_thread(runner.invoke, app, list(args))

    return run


async def set_admins(
    committed_sessionmaker: async_sessionmaker[AsyncSession], *chat_ids: int
) -> None:
    async with committed_sessionmaker() as s, s.begin():
        await settings_store.update(s, {"admin_chat_ids": list(chat_ids)})


async def alerts(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> list[OutboxMessage]:
    async with committed_sessionmaker() as s:
        rows = await s.scalars(
            select(OutboxMessage).where(OutboxMessage.template_key == "backup_failed")
        )
        return list(rows)


async def admin_chats(committed_sessionmaker: async_sessionmaker[AsyncSession]) -> list[int]:
    async with committed_sessionmaker() as s:
        return (await settings_store.load(s)).admin_chat_ids


async def test_backup_failed_is_queued_for_every_admin(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await set_admins(committed_sessionmaker, 11, 22)
    result = await invoke("notify", "backup-failed", "--reason", "pg_dump: connection refused")
    assert result.exit_code == 0, result.output
    rows = await alerts(committed_sessionmaker)
    assert sorted(m.chat_id for m in rows) == [11, 22]
    assert all(m.recipient_type == "admin" for m in rows)
    assert all(m.payload == {"reason": "pg_dump: connection refused"} for m in rows)


async def test_a_second_failure_the_same_day_is_deduplicated(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await set_admins(committed_sessionmaker, 11)
    await invoke("notify", "backup-failed", "--reason", "first")
    result = await invoke("notify", "backup-failed", "--reason", "second")
    assert result.exit_code == 0
    assert len(await alerts(committed_sessionmaker)) == 1


async def test_without_admins_it_succeeds_and_says_so(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await invoke("notify", "backup-failed", "--reason", "x")
    assert result.exit_code == 0
    assert "админы не заданы" in result.output
    assert await alerts(committed_sessionmaker) == []


async def test_a_long_reason_is_truncated_to_300_chars(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await set_admins(committed_sessionmaker, 11)
    await invoke("notify", "backup-failed", "--reason", "x" * 1000)
    [message] = await alerts(committed_sessionmaker)
    assert len(message.payload["reason"]) == 300


async def test_admin_chat_adds_a_number_once(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    assert (await invoke("settings", "admin-chat", "123456789")).exit_code == 0
    result = await invoke("settings", "admin-chat", "123456789")
    assert result.exit_code == 0
    assert await admin_chats(committed_sessionmaker) == [123456789]
    assert "123456789" in result.output


async def test_admin_chat_keeps_the_existing_chats(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await set_admins(committed_sessionmaker, 5)
    await invoke("settings", "admin-chat", "6")
    assert await admin_chats(committed_sessionmaker) == [5, 6]


async def test_admin_chat_rejects_non_numbers(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await invoke("settings", "admin-chat", "not-a-number")
    assert result.exit_code != 0
    assert await admin_chats(committed_sessionmaker) == []
