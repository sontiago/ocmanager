from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps import bot
from ocmanager.core.config import Settings
from ocmanager.notifications.render import render
from ocmanager.subscriptions.models import Client

PANEL = "https://panel.example.com"


class FakeMessage:
    """Ровно то, что читают обработчики: from_user, chat и answer()."""

    def __init__(
        self,
        *,
        user_id: int = 7001,
        first_name: str = "Anna",
        language_code: str | None = "ru",
        chat_id: int | None = None,
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, first_name=first_name, username=None, language_code=language_code
        )
        self.chat = SimpleNamespace(id=user_id if chat_id is None else chat_id)
        self.answers: list[tuple[str, Any]] = []

    async def answer(self, text: str, reply_markup: Any = None) -> None:
        self.answers.append((text, reply_markup))


def msg(fake: FakeMessage) -> Message:
    return cast("Message", fake)


@pytest.fixture
def https_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"public_base_url": PANEL})


async def clients(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Client)) or 0


async def test_start_registers_the_client_and_opens_the_mini_app(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    fake = FakeMessage(user_id=7001, first_name="Anna")

    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)

    assert await clients(session) == 1
    client = await session.scalar(select(Client).where(Client.telegram_id == 7001))
    assert client is not None
    assert (client.first_name, client.lang) == ("Anna", "ru")
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "ru", {"name": "Anna"})
    button = markup.inline_keyboard[0][0]
    assert button.text == render("bot_open_app", "ru", {})
    assert button.web_app.url == PANEL


async def test_start_twice_does_not_duplicate_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    for _ in range(2):
        await bot.start(msg(FakeMessage()), settings=https_settings, sessionmaker=sessionmaker)
    assert await clients(session) == 1


async def test_start_answers_in_the_clients_language(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    fake = FakeMessage(language_code="en")
    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "en", {"name": "Anna"})
    assert markup.inline_keyboard[0][0].text == render("bot_open_app", "en", {})


async def test_start_without_https_sends_no_button(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    # Telegram отвергает web_app с http-адресом и всё сообщение пропало бы.
    assert settings.public_base_url.startswith("http://")
    fake = FakeMessage()
    await bot.start(msg(fake), settings=settings, sessionmaker=sessionmaker)
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "ru", {"name": "Anna"})
    assert markup is None


async def test_whoami_shows_the_chat_id_and_touches_no_database(session: AsyncSession) -> None:
    fake = FakeMessage(user_id=7001, chat_id=555)
    await bot.whoami(msg(fake))
    [(text, _)] = fake.answers
    assert text == render("bot_whoami", "ru", {"chat_id": 555})
    assert await clients(session) == 0


async def test_any_other_text_gets_the_hint_with_the_button(https_settings: Settings) -> None:
    fake = FakeMessage(language_code="en")
    await bot.fallback(msg(fake), settings=https_settings)
    [(text, markup)] = fake.answers
    assert text == render("bot_hint", "en", {})
    assert markup.inline_keyboard[0][0].web_app.url == PANEL


async def test_a_message_without_a_sender_is_ignored(
    sessionmaker: async_sessionmaker[AsyncSession], https_settings: Settings
) -> None:
    fake = FakeMessage()
    fake.from_user = None  # type: ignore[assignment]
    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)
    await bot.whoami(msg(fake))
    await bot.fallback(msg(fake), settings=https_settings)
    assert fake.answers == []
