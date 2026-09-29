"""Вход админа: проверка пароля и TOTP, серверные сессии.

Аудит здесь пишется до исключения и тут же коммитится: get_session откатывает
незакоммиченное, а запись о неудачной попытке нужна именно при неудаче.
"""

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.accounts import USERNAME_RE, get_by_username
from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core import ratelimit, security
from ocmanager.core.config import Settings
from ocmanager.core.crypto import derive_fernet
from ocmanager.core.errors import Forbidden, Unauthorized

COOKIE = "ocm_admin"
CSRF_HEADER = "X-CSRF-Token"
IDLE_TIMEOUT = timedelta(hours=12)
MAX_LIFETIME = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=1)  # last_seen_at пишется не чаще раза в минуту
LOGIN_LIMIT = 5
LOGIN_WINDOW_S = 15 * 60


class TotpRequired(Unauthorized):
    code = "totp_required"


class CsrfFailed(Forbidden):
    code = "csrf_failed"


@dataclass(frozen=True)
class LoginResult:
    admin: Admin
    session: AdminSession
    token: str  # в cookie; в БД только sha256


def totp_fernet(settings: Settings) -> Fernet:
    return derive_fernet(settings.secret_key.get_secret_value(), purpose=b"ocmanager.admin-totp")


def parse_ip(host: str | None) -> str | None:
    """Колонка ip — INET: всё, что не адрес (unix-сокет, тестовый клиент), сохраняем как NULL."""
    try:
        return None if host is None else str(ipaddress.ip_address(host))
    except ValueError:
        return None


def actor_of(admin: Admin, ip: str | None) -> Actor:
    return Actor(type="admin", id=str(admin.id), ip=ip)


async def _fail(
    db: AsyncSession, ip: str | None, username: str, admin: Admin | None, reason: str
) -> Unauthorized:
    # В аудит идёт только то, что похоже на логин: в поле «логин» легко набрать пароль.
    await audit.record(
        db,
        Actor(type="admin", ip=ip),
        "admin.login_failed",
        target_type="admin",
        target_id=None if admin is None else str(admin.id),
        details={
            "username": username if USERNAME_RE.fullmatch(username) else None,
            "reason": reason,
        },
    )
    await db.commit()
    return Unauthorized("invalid credentials")


async def login(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    username: str,
    password: str,
    totp_code: str | None,
    ip: str | None,
    user_agent: str | None,
    now: datetime,
) -> LoginResult:
    """Неверный логин и неверный пароль дают один и тот же ответ; для несуществующего
    логина тратится столько же времени (dummy_verify). Считаются все попытки, а не только
    неудачные, — успешный вход обнуляет счётчик."""
    limiter_key = f"admin_login:{username[:64].lower()}:{ip}"
    await ratelimit.hit(redis, limiter_key, limit=LOGIN_LIMIT, window_s=LOGIN_WINDOW_S)

    admin = await get_by_username(db, username)
    if admin is None or not admin.is_active:
        security.dummy_verify()
        raise await _fail(db, ip, username, admin, "unknown_user")
    if not security.verify_password(password, admin.password_hash):
        raise await _fail(db, ip, username, admin, "bad_password")
    if admin.totp_enabled:
        if not totp_code:
            raise TotpRequired("totp code required")
        assert admin.totp_secret is not None
        secret = totp_fernet(settings).decrypt(admin.totp_secret.encode()).decode()
        if not security.verify_totp(secret, totp_code, now=now):
            raise await _fail(db, ip, username, admin, "bad_totp")

    await ratelimit.reset(redis, limiter_key)
    token = security.new_token()
    row = AdminSession(
        admin_id=admin.id,
        token_hash=security.sha256_hex(token),
        csrf_token=security.new_token(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + MAX_LIFETIME,
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(row)
    admin.last_login_at = now
    await db.flush()
    await audit.record(
        db, actor_of(admin, ip), "admin.login", target_type="admin", target_id=str(admin.id)
    )
    await db.commit()
    return LoginResult(admin=admin, session=row, token=token)


async def authenticate(db: AsyncSession, token: str, now: datetime) -> tuple[Admin, AdminSession]:
    """Админ и сессия по значению cookie. Просроченная сессия удаляется."""
    row = (
        await db.execute(
            select(AdminSession, Admin)
            .join(Admin, Admin.id == AdminSession.admin_id)
            .where(AdminSession.token_hash == security.sha256_hex(token))
        )
    ).one_or_none()
    if row is None:
        raise Unauthorized()
    session, admin = row
    if session.expires_at <= now or session.last_seen_at + IDLE_TIMEOUT <= now:
        await db.execute(delete(AdminSession).where(AdminSession.id == session.id))
        await db.commit()
        raise Unauthorized("session expired")
    if not admin.is_active:
        raise Unauthorized()
    if now - session.last_seen_at >= TOUCH_EVERY:
        session.last_seen_at = now
        await db.commit()
    return admin, session
