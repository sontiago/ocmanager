"""Кто спрашивает: клиент по initData из заголовка `Authorization: tma <initData>`."""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request

from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import Unauthorized
from ocmanager.flows import clients as client_flows
from ocmanager.flows.deps import SettingsDep, client_ip
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.tma.auth import validate_init_data

SCHEME = "tma"


@dataclass(frozen=True)
class TmaContext:
    client: Client
    actor: Actor  # Actor("client", id, ip): его пишет в аудит каждое действие клиента
    lang: Literal["ru", "en"]


def _needs_refresh(client: Client, ident: TelegramIdentity) -> bool:
    return (
        client.first_name != ident.first_name
        or client.username != ident.username
        or client.lang != subscriptions.lang_from_telegram(ident.language_code)
    )


async def current_client(request: Request, db: SessionDep, settings: SettingsDep) -> TmaContext:
    """Клиент создаётся при первом запросе и обновляется, только если Telegram сообщил
    новое имя или язык: обычный запрос не пишет в БД.

    Заблокированный клиент проходит: `GET /tma/me` обязан сказать `is_blocked: true`, чтобы
    TMA показала экран блокировки. Действия, которым блокировка мешает, проверяют её сами."""
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != SCHEME or not raw.strip():
        raise Unauthorized("Authorization: tma <initData> required")
    init = validate_init_data(
        raw.strip(),
        settings.bot_token.get_secret_value(),
        ttl_s=settings.tma_initdata_ttl_s,
        now=utcnow(),
        allow_dev=settings.tma_allow_dev_initdata,
    )
    client = await subscriptions.find_client_by_telegram_id(db, init.user.telegram_id)
    if client is None or _needs_refresh(client, init.user):
        client = (await client_flows.register_client(db, init.user)).client
        await db.commit()
    return TmaContext(
        client=client,
        actor=Actor("client", str(client.id), client_ip(request)),
        lang="ru" if client.lang == "ru" else "en",
    )


CurrentClient = Annotated[TmaContext, Depends(current_client)]
