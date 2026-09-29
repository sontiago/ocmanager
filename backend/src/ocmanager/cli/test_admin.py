"""Команды `ocmanager admin …` на настоящей БД. Данные коммитятся по-настоящему —
после теста таблицы очищает committed_sessionmaker."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from conftest import ADMIN_PASSWORD
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner, Result

from ocmanager.admin.models import Admin
from ocmanager.audit.models import AuditLog
from ocmanager.cli import app
from ocmanager.core import security
from ocmanager.core.config import Settings

runner = CliRunner()
Invoke = Callable[..., Awaitable[Result]]


@pytest.fixture
def invoke(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    fast_bcrypt: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Invoke:
    monkeypatch.setenv("OCM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("OCM_LOG_LEVEL", "WARNING")

    async def run(*args: str, stdin: str | None = None) -> Result:
        return await asyncio.to_thread(runner.invoke, app, list(args), input=stdin)

    return run


async def test_create_reads_the_password_from_stdin(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await invoke(
        "admin", "create", "alice", "--password-stdin", stdin=ADMIN_PASSWORD + "\n"
    )
    assert result.exit_code == 0, result.output
    async with committed_sessionmaker() as session:
        admin = await session.scalar(select(Admin))
        assert admin is not None
        assert admin.username == "alice"
        assert security.verify_password(ADMIN_PASSWORD, admin.password_hash)
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "admin.create"))
        assert audit is not None
        assert audit.actor_id == "cli"
    assert ADMIN_PASSWORD not in result.output


async def test_create_prompts_twice_without_the_flag(invoke: Invoke) -> None:
    result = await invoke("admin", "create", "bob", stdin=f"{ADMIN_PASSWORD}\n{ADMIN_PASSWORD}\n")
    assert result.exit_code == 0, result.output


async def test_repeat_create_fails_with_code_1(invoke: Invoke) -> None:
    args = ("admin", "create", "alice", "--password-stdin")
    assert (await invoke(*args, stdin=ADMIN_PASSWORD + "\n")).exit_code == 0
    again = await invoke(*args, stdin=ADMIN_PASSWORD + "\n")
    assert again.exit_code == 1
    assert "conflict" in again.output


async def test_weak_password_fails_with_code_1(invoke: Invoke) -> None:
    result = await invoke("admin", "create", "alice", "--password-stdin", stdin="short\n")
    assert result.exit_code == 1
    assert "validation_error" in result.output


async def test_passwd_changes_the_password_and_unknown_admin_fails(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await invoke("admin", "create", "alice", "--password-stdin", stdin=ADMIN_PASSWORD + "\n")
    new = "brand-new-password-1"
    ok = await invoke("admin", "passwd", "alice", "--password-stdin", stdin=new + "\n")
    assert ok.exit_code == 0, ok.output
    async with committed_sessionmaker() as session:
        admin = await session.scalar(select(Admin))
        assert admin is not None
        assert security.verify_password(new, admin.password_hash)
    missing = await invoke("admin", "passwd", "ghost", "--password-stdin", stdin=new + "\n")
    assert missing.exit_code == 1


async def test_list(invoke: Invoke) -> None:
    await invoke("admin", "create", "alice", "--password-stdin", stdin=ADMIN_PASSWORD + "\n")
    result = await invoke("admin", "list")
    assert result.exit_code == 0
    assert "alice" in result.output
    assert "не входил" in result.output
