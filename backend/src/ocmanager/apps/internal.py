"""Внутренний API: только для нод. `POST /internal/session-end` принимает финальные
счётчики сессии от disconnect.sh. Не проксируется наружу (Caddy, Фаза 7).

Лежит в apps/, а не в nodes/: после учёта трафика надо обновить расход подписки
(flows), а домен nodes не импортирует другие домены.
"""

import hmac
import ipaddress
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import Forbidden, Unauthorized
from ocmanager.flows.traffic import apply_usage
from ocmanager.nodes import registry
from ocmanager.nodes.files import validate_username
from ocmanager.nodes.traffic import SessionEnd, record_session_end

router = APIRouter(prefix="/internal", tags=["internal"])

MAX_COUNTER = 2**62  # с запасом влезает в BIGINT


class SessionEndBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    session_id: str = Field(pattern=r"^\d{1,20}$")
    bytes_in: int = Field(ge=0, le=MAX_COUNTER)
    bytes_out: int = Field(ge=0, le=MAX_COUNTER)
    duration_sec: int = Field(ge=0, le=MAX_COUNTER)
    remote_ip: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("remote_ip")
    @classmethod
    def _remote_ip(cls, value: str | None) -> str | None:
        """Хук шлёт пустую строку, если ocserv не сообщил адрес."""
        if not value:
            return None
        return str(ipaddress.ip_address(value))


def _require_internal_caller(request: Request, token: str | None) -> None:
    """Два слоя: адрес из частной сети И общий секрет. Публичный процесс слушает и
    внешний трафик, поэтому одного секрета мало — утечка не должна открывать эндпоинт миру."""
    host = request.client.host if request.client else None
    try:
        private = host is not None and ipaddress.ip_address(host).is_private
    except ValueError:
        private = False
    if not private:
        raise Forbidden("internal network only")
    settings: Settings = request.app.state.settings
    expected = settings.internal_token.get_secret_value().encode()
    if token is None or not hmac.compare_digest(token.encode(), expected):
        raise Unauthorized("bad internal token")


@router.post("/session-end", status_code=204)
async def session_end(
    body: SessionEndBody,
    request: Request,
    session: SessionDep,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> Response:
    _require_internal_caller(request, x_internal_token)
    settings: Settings = request.app.state.settings
    now = utcnow()
    node = await registry.ensure_local_node(session, settings)  # нода этапа 1 одна
    await record_session_end(
        session,
        node.id,
        SessionEnd(
            username=body.username,
            session_id=body.session_id,
            bytes_in=body.bytes_in,
            bytes_out=body.bytes_out,
            duration_sec=body.duration_sec,
            remote_ip=body.remote_ip,
        ),
        now,
    )
    await apply_usage(session, [body.username], now)
    await session.commit()
    return Response(status_code=204)
