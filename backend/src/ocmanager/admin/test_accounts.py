import pytest
from conftest import ADMIN_PASSWORD, MakeAdmin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.admin import accounts
from ocmanager.admin.models import AdminSession
from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.core import security
from ocmanager.core.clock import utcnow
from ocmanager.core.errors import Conflict, InvalidInput

CLI = Actor(type="admin", id="cli")


async def test_create_hashes_the_password_and_audits(
    session: AsyncSession, make_admin: MakeAdmin
) -> None:
    admin = await make_admin("alice")
    assert admin.role == "owner"
    assert admin.is_active
    assert not admin.totp_enabled
    assert admin.password_hash != ADMIN_PASSWORD
    assert security.verify_password(ADMIN_PASSWORD, admin.password_hash)
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "admin.create"))
    assert row is not None
    assert row.details == {"username": "alice"}
    assert ADMIN_PASSWORD not in str(row.details)


async def test_duplicate_username_is_a_conflict(
    session: AsyncSession, make_admin: MakeAdmin
) -> None:
    await make_admin("alice")
    with pytest.raises(Conflict):
        await make_admin("alice")
    assert len(await accounts.list_admins(session)) == 1  # транзакция жива


@pytest.mark.parametrize("username", ["", "ab", "Alice", "a b c", "x" * 33, "al!ce", "алиса"])
async def test_bad_usernames_are_refused(make_admin: MakeAdmin, username: str) -> None:
    with pytest.raises(InvalidInput):
        await make_admin(username)


@pytest.mark.parametrize("password", ["", "short", "12345678901", "я" * 37])
async def test_bad_passwords_are_refused(make_admin: MakeAdmin, password: str) -> None:
    with pytest.raises(InvalidInput):
        await make_admin("alice", password)


async def test_72_bytes_is_the_ceiling(make_admin: MakeAdmin) -> None:
    assert (await make_admin("alice", "a" * 72)).id
    with pytest.raises(InvalidInput):
        await make_admin("bob", "a" * 73)


async def test_set_password_closes_other_sessions(
    session: AsyncSession, make_admin: MakeAdmin
) -> None:
    admin = await make_admin("alice")
    now = utcnow()
    ids = []
    for n in range(3):
        row = AdminSession(
            admin_id=admin.id,
            token_hash=f"h{n}",
            csrf_token="c",
            created_at=now,
            last_seen_at=now,
            expires_at=now,
        )
        session.add(row)
        await session.flush()
        ids.append(row.id)
    await accounts.set_password(
        session, admin, "another-long-password", CLI, keep_session_id=ids[0]
    )
    left = list(await session.scalars(select(AdminSession.id)))
    assert left == [ids[0]]
    assert security.verify_password("another-long-password", admin.password_hash)
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "admin.password_change"))
    assert row is not None
    assert row.details == {"sessions_closed": 2}
    assert row.actor_id == "cli"
