"""Зависимости FastAPI, общие для api-admin и api-public: настройки, Redis, CA, ключ выдачи
.p12, коммит с «пинком» воркеру и IP клиента. Живёт в flows/, потому что и admin/, и tma/ —
склейка доменов, а друг друга они не импортируют."""

import ipaddress
from typing import Annotated

from arq import ArqRedis
from cryptography.fernet import Fernet
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.config import Settings
from ocmanager.core.crypto import p12_fernet
from ocmanager.core.errors import DomainError
from ocmanager.core.redis import get_redis
from ocmanager.events import bus
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca


def parse_ip(host: str | None) -> str | None:
    """Колонка ip — INET: всё, что не адрес (unix-сокет, тестовый клиент), сохраняем как NULL."""
    try:
        return None if host is None else str(ipaddress.ip_address(host))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    return parse_ip(request.client.host if request.client else None)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[ArqRedis, Depends(get_redis)]


class PkiNotReady(DomainError):
    code, status = "pki_not_ready", 503


def get_ca(request: Request) -> CertificateAuthority:
    """CA читается при первом обращении и держится в памяти процесса: без ca.key процесс
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
