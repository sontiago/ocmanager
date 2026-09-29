"""Учётные записи админов: создание, смена пароля, список.

admin/ — слой склейки (как flows/): здесь можно писать аудит. Коммит — у вызывающего.
"""

import re

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin.models import Admin, AdminSession
from ocmanager.audit import service as audit
from ocmanager.audit.service import Actor
from ocmanager.core import security
from ocmanager.core.errors import Conflict, InvalidInput

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD_LEN = 12


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise InvalidInput(f"password must be at least {MIN_PASSWORD_LEN} characters")
    # bcrypt молча учитывает только 72 байта; отказываем явно, а не режем пароль втихую.
    if len(password.encode()) > security.MAX_PASSWORD_BYTES:
        raise InvalidInput(f"password must be at most {security.MAX_PASSWORD_BYTES} bytes")


async def get_by_username(session: AsyncSession, username: str) -> Admin | None:
    admin: Admin | None = await session.scalar(select(Admin).where(Admin.username == username))
    return admin


async def list_admins(session: AsyncSession) -> list[Admin]:
    return list(await session.scalars(select(Admin).order_by(Admin.id)))


async def create_admin(session: AsyncSession, username: str, password: str, actor: Actor) -> Admin:
    if not USERNAME_RE.fullmatch(username):
        raise InvalidInput("username must match [a-z0-9_.-], 3..32 characters")
    check_password(password)
    admin = Admin(username=username, password_hash=security.hash_password(password), role="owner")
    try:
        # SAVEPOINT: дубль логина не отравляет транзакцию вызывающего.
        async with session.begin_nested():
            session.add(admin)
    except IntegrityError:
        raise Conflict(f"admin {username!r} already exists") from None
    await audit.record(
        session,
        actor,
        "admin.create",
        target_type="admin",
        target_id=str(admin.id),
        details={"username": username},
    )
    return admin


async def close_sessions(
    session: AsyncSession, admin_id: int, *, keep_session_id: int | None = None
) -> int:
    """Удаляет сессии админа, кроме текущей. Возвращает, сколько закрыто."""
    stmt = delete(AdminSession).where(AdminSession.admin_id == admin_id)
    if keep_session_id is not None:
        stmt = stmt.where(AdminSession.id != keep_session_id)
    result = await session.execute(stmt.returning(AdminSession.id))
    return len(result.all())


async def set_password(
    session: AsyncSession,
    admin: Admin,
    new_password: str,
    actor: Actor,
    *,
    keep_session_id: int | None = None,
) -> None:
    """Меняет пароль и закрывает остальные сессии: украденная cookie не переживает смену."""
    check_password(new_password)
    admin.password_hash = security.hash_password(new_password)
    closed = await close_sessions(session, admin.id, keep_session_id=keep_session_id)
    await audit.record(
        session,
        actor,
        "admin.password_change",
        target_type="admin",
        target_id=str(admin.id),
        details={"sessions_closed": closed},
    )


async def reset_totp(session: AsyncSession, admin: Admin, actor: Actor) -> bool:
    """Выключает второй фактор без кода — для админа, потерявшего телефон.
    Доступно только тому, у кого есть доступ к хосту (CLI). True — что-то изменилось."""
    if not admin.totp_enabled and admin.totp_secret is None:
        return False
    admin.totp_enabled = False
    admin.totp_secret = None
    await audit.record(
        session, actor, "admin.totp_disable", target_type="admin", target_id=str(admin.id)
    )
    return True
