"""Клиенты и подписки. Аудит здесь не пишется: subscriptions не импортирует
домен audit (граница модулей) — его пишут функции из flows/."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Boolean, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.errors import NotFound
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.schemas import TelegramIdentity


def lang_from_telegram(code: str | None) -> Literal["ru", "en"]:
    """ru, ru-RU → ru; всё остальное, включая отсутствие, → en (решение C4 плана TMA)."""
    return "ru" if code is not None and code.lower().startswith("ru") else "en"


@dataclass(frozen=True)
class UpsertResult:
    client: Client
    created: bool


async def upsert_client(session: AsyncSession, ident: TelegramIdentity) -> UpsertResult:
    """Создаёт клиента или обновляет имя, username и язык из Telegram.
    Один SQL-запрос: два одновременных первых захода не дадут дубля."""
    values = {
        "telegram_id": ident.telegram_id,
        "first_name": ident.first_name,
        "username": ident.username,
        "lang": lang_from_telegram(ident.language_code),
    }
    stmt = insert(Client).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Client.telegram_id],
        set_={k: stmt.excluded[k] for k in ("first_name", "username", "lang")}
        | {"updated_at": text("now()")},
    )
    # xmax = 0 только у строки, вставленной этим запросом.
    inserted = literal_column("(xmax = 0)", Boolean).label("inserted")
    row = (
        await session.execute(
            stmt.returning(Client, inserted).execution_options(populate_existing=True)
        )
    ).one()
    return UpsertResult(client=row[0], created=bool(row[1]))


async def get_client(session: AsyncSession, client_id: int) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFound("client not found")
    return client


async def find_client_by_telegram_id(session: AsyncSession, telegram_id: int) -> Client | None:
    client: Client | None = await session.scalar(
        select(Client).where(Client.telegram_id == telegram_id)
    )
    return client
