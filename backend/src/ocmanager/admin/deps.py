import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from ocmanager.admin import auth
from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import Unauthorized
from ocmanager.flows.deps import CaDep as CaDep
from ocmanager.flows.deps import FernetDep as FernetDep
from ocmanager.flows.deps import PkiNotReady as PkiNotReady
from ocmanager.flows.deps import RedisDep as RedisDep
from ocmanager.flows.deps import SettingsDep as SettingsDep
from ocmanager.flows.deps import client_ip
from ocmanager.flows.deps import commit_and_kick as commit_and_kick

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AdminContext:
    admin: Admin
    session: AdminSession
    actor: Actor  # с IP запроса: его пишет в аудит каждая мутация


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
