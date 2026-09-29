import hmac
from dataclasses import dataclass
from typing import Annotated

from arq import ArqRedis
from fastapi import Depends, Request

from ocmanager.admin import auth
from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import Unauthorized
from ocmanager.core.redis import get_redis

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AdminContext:
    admin: Admin
    session: AdminSession
    actor: Actor  # с IP запроса: его пишет в аудит каждая мутация


def client_ip(request: Request) -> str | None:
    return auth.parse_ip(request.client.host if request.client else None)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[ArqRedis, Depends(get_redis)]


async def current_admin(request: Request, db: SessionDep) -> AdminContext:
    """Сессия по cookie; для небезопасных методов ещё и сверка X-CSRF-Token."""
    token = request.cookies.get(auth.COOKIE)
    if not token:
        raise Unauthorized()
    admin, session = await auth.authenticate(db, token, utcnow())
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(auth.CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise auth.CsrfFailed("csrf token missing or wrong")
    return AdminContext(
        admin=admin, session=session, actor=auth.actor_of(admin, client_ip(request))
    )


CurrentAdmin = Annotated[AdminContext, Depends(current_admin)]
