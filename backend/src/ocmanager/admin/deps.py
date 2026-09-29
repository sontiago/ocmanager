import hmac
from dataclasses import dataclass
from typing import Annotated

from arq import ArqRedis
from cryptography.fernet import Fernet
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin import auth
from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit.service import Actor
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.core.crypto import p12_fernet
from ocmanager.core.db import SessionDep
from ocmanager.core.errors import DomainError, Unauthorized
from ocmanager.core.redis import get_redis
from ocmanager.events import bus
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca

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


class PkiNotReady(DomainError):
    code, status = "pki_not_ready", 503


def get_ca(request: Request) -> CertificateAuthority:
    """CA читается при первом обращении и держится в памяти процесса: без ca.key админка
    работает, отказывают только операции выпуска."""
    ca: CertificateAuthority | None = getattr(request.app.state, "ca", None)
    if ca is None:
        settings: Settings = request.app.state.settings
        try:
            ca = load_ca(settings.pki_dir)
        except FileNotFoundError:
            raise PkiNotReady("CA not found: run `ocmanager pki init`") from None
        request.app.state.ca = ca
    return ca


def get_p12_fernet(request: Request) -> Fernet:
    settings: Settings = request.app.state.settings
    return p12_fernet(settings.secret_key.get_secret_value())


CaDep = Annotated[CertificateAuthority, Depends(get_ca)]
FernetDep = Annotated[Fernet, Depends(get_p12_fernet)]


async def commit_and_kick(db: AsyncSession, redis: ArqRedis) -> None:
    """Коммит, и только после него — просьба воркеру разобрать события: иначе он мог бы
    прочитать outbox раньше, чем изменение станет видно."""
    await db.commit()
    await bus.kick_dispatch(redis)
