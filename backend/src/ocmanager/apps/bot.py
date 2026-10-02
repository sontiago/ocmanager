"""Процесс бота: aiogram 3, long polling (публичный вебхук для бота не нужен).

Запуск: `uv run python -m ocmanager.apps.bot`.
Бот ничего не рассылает: уведомления кладут в очередь обработчики событий, отправляет воркер
(notifications/tasks.py) — рестарт бота не теряет сообщения.
"""

import asyncio
from typing import Literal

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.logging import configure_logging
from ocmanager.flows.clients import register_client
from ocmanager.notifications.render import render
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.service import lang_from_telegram

log = structlog.get_logger(__name__)

router = Router(name="main")
router.message.filter(F.chat.type == "private")


def open_app_markup(settings: Settings, lang: Literal["ru", "en"]) -> InlineKeyboardMarkup | None:
    """Кнопка Mini App. Telegram принимает web_app только с https: без него (dev без туннеля)
    отвечаем без кнопки, а не теряем сообщение целиком."""
    if not settings.public_base_url.startswith("https://"):
        return None
    button = InlineKeyboardButton(
        text=render("bot_open_app", lang, {}), web_app=WebAppInfo(url=settings.public_base_url)
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


@router.message(CommandStart())
async def start(
    message: Message, *, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    user = message.from_user
    if user is None:
        return
    identity = TelegramIdentity(
        telegram_id=user.id,
        first_name=user.first_name,
        username=user.username,
        language_code=user.language_code,
    )
    async with sessionmaker() as session:
        result = await register_client(session, identity)
        await session.commit()
    lang = lang_from_telegram(result.client.lang)
    await message.answer(
        render("bot_start", lang, {"name": user.first_name}),
        reply_markup=open_app_markup(settings, lang),
    )


@router.message(Command("whoami"))
async def whoami(message: Message) -> None:
    """chat_id для admin_chat_ids: так админ узнаёт его, не заходя в БД."""
    user = message.from_user
    if user is None:
        return
    lang = lang_from_telegram(user.language_code)
    await message.answer(render("bot_whoami", lang, {"chat_id": message.chat.id}))


@router.message()
async def fallback(message: Message, *, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = lang_from_telegram(user.language_code)
    await message.answer(render("bot_hint", lang, {}), reply_markup=open_app_markup(settings, lang))


async def run(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = Dispatcher(settings=settings, sessionmaker=make_sessionmaker(engine))
    dispatcher.include_router(router)
    try:
        # Бот мог раньше работать на вебхуке: пока он стоит, getUpdates отвечает ошибкой.
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("bot_started")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
        log.info("bot_stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
