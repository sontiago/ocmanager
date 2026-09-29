"""Команды оператора на настоящей БД (тестовой) и фейковой ноде.

CLI вызывает asyncio.run, поэтому в async-тесте он запускается в потоке.
Данные коммитятся по-настоящему — после теста таблицы очищает committed_sessionmaker.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner, Result

from ocmanager.audit.models import AuditLog
from ocmanager.cli import app
from ocmanager.core.config import Settings
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority, save_ca
from ocmanager.subscriptions.models import Subscription

runner = CliRunner()
Invoke = Callable[..., Awaitable[Result]]


@pytest.fixture
def fake() -> Iterator[FakeNodeDriver]:
    driver = FakeNodeDriver()
    with registry.override_driver(driver):
        yield driver


@pytest.fixture
def invoke(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    test_ca: CertificateAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeNodeDriver,
) -> Invoke:
    pki = tmp_path / "pki"
    save_ca(test_ca, pki)
    monkeypatch.setenv("OCM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("OCM_PKI_DIR", str(pki))
    monkeypatch.setenv("OCM_LOG_LEVEL", "WARNING")

    async def run(*args: str) -> Result:
        return await asyncio.to_thread(runner.invoke, app, list(args))

    return run


async def ok(invoke: Invoke, *args: str) -> str:
    result = await invoke(*args)
    assert result.exit_code == 0, result.output
    return result.output


PLAN = ["plan", "create", "--code", "m1", "--name-ru", "Месяц", "--name-en", "Month"]
PLAN += ["--days", "30", "--devices", "2", "--price", "19900"]


async def test_the_whole_operator_path(
    invoke: Invoke,
    fake: FakeNodeDriver,
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await ok(invoke, *PLAN)
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    granted = await ok(invoke, "client", "grant", "5001", "m1")
    assert "active" in granted

    p12_path = tmp_path / "laptop.p12"
    issued = await ok(
        invoke,
        *("device", "issue", "5001", "--name", "laptop", "--platform", "linux"),
        *("--out", str(p12_path)),
    )
    fields = dict(line.split(":", 1) for line in issued.strip().splitlines())
    username, password = fields["username"].strip(), fields["password"].strip()
    assert re.fullmatch(r"c\d+-d1", username)
    assert p12_path.stat().st_mode & 0o777 == 0o600
    key, cert, _ = pkcs12.load_key_and_certificates(p12_path.read_bytes(), password.encode())
    assert (key is not None, cert is not None) == (True, True)
    assert fake.allowlist == {username}  # синхронизация сразу после команды

    listing = await ok(invoke, "device", "list", "5001")
    assert username in listing
    assert "активно" in listing

    fake.add_session(username)
    device_id = fields["device"].strip()
    assert "отозвано" in await ok(invoke, "device", "revoke", device_id)
    assert (fake.allowlist, fake.sessions) == (set(), [])
    assert fake.crl is not None
    assert cert is not None
    assert [r.serial_number for r in x509.load_pem_x509_crl(fake.crl)] == [cert.serial_number]
    assert "отозвано" in await ok(invoke, "device", "list", "5001")

    async with committed_sessionmaker() as session:
        actions = list(await session.scalars(select(AuditLog.action).order_by(AuditLog.id)))
    assert actions == [
        "plan.create",
        "client.create",
        "subscription.activate",
        "device.issue",
        "device.revoke",
        "revocation.apply",
    ]


async def test_expire_now_cuts_access_and_grant_restores_it(
    invoke: Invoke,
    fake: FakeNodeDriver,
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await ok(invoke, *PLAN)
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    await ok(invoke, "client", "grant", "5001", "m1")
    out = ["--out", str(tmp_path / "d.p12")]
    issued = await ok(
        invoke, *("device", "issue", "5001", "--name", "a", "--platform", "ios"), *out
    )
    username = re.search(r"username:\s+(\S+)", issued)
    assert username is not None
    assert fake.allowlist == {username.group(1)}

    fake.add_session(username.group(1))
    await ok(invoke, "subscription", "expire-now", "5001")
    assert (fake.allowlist, fake.sessions) == (set(), [])
    async with committed_sessionmaker() as session:
        sub = await session.scalar(select(Subscription))
        assert sub is not None
        assert sub.status == "expired"

    await ok(invoke, "client", "grant", "5001", "m1")
    assert fake.allowlist == {username.group(1)}  # тот же сертификат снова допущен


async def test_no_sync_leaves_the_node_alone(
    invoke: Invoke, fake: FakeNodeDriver, tmp_path: Path
) -> None:
    await ok(invoke, *PLAN)
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    await ok(invoke, "client", "grant", "5001", "m1", "--no-sync")
    await ok(
        invoke,
        *("device", "issue", "5001", "--name", "a", "--platform", "ios"),
        *("--out", str(tmp_path / "d.p12"), "--no-sync"),
    )
    assert fake.calls == []


async def test_grant_with_days(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await ok(invoke, *PLAN)
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    await ok(invoke, "client", "grant", "5001", "m1", "--days", "7", "--no-sync")
    async with committed_sessionmaker() as session:
        sub = await session.scalar(select(Subscription))
        assert sub is not None
        assert (sub.expires_at - sub.started_at).days == 7


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["client", "grant", "404", "m1"], "не найден"),
        (["device", "list", "404"], "не найден"),
        (["subscription", "expire-now", "404"], "не найден"),
        (["device", "revoke", "999999"], "not_found"),
    ],
)
async def test_unknown_things_fail_cleanly(invoke: Invoke, args: list[str], expected: str) -> None:
    result = await invoke(*args)
    assert result.exit_code == 1
    assert expected in result.output


async def test_client_without_subscription_gets_no_device(invoke: Invoke, tmp_path: Path) -> None:
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    out = tmp_path / "d.p12"
    result = await invoke(
        *("device", "issue", "5001", "--name", "a", "--platform", "ios"), *("--out", str(out))
    )
    assert result.exit_code == 1
    assert "subscription_inactive" in result.output
    assert not out.exists()


async def test_unknown_plan_fails_cleanly(invoke: Invoke) -> None:
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    result = await invoke("client", "grant", "5001", "nope")
    assert (result.exit_code, "not_found" in result.output) == (1, True)


async def test_dev_only_commands_are_refused_in_production(
    invoke: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OCM_ENV", "production")
    for args in (
        [
            "device",
            "issue",
            "5001",
            "--name",
            "a",
            "--platform",
            "ios",
            "--out",
            str(tmp_path / "x"),
        ],
        ["subscription", "expire-now", "5001"],
    ):
        result = await invoke(*args)
        assert result.exit_code == 1
        assert "только для dev" in result.output


async def test_device_count_matches_after_the_walk(
    invoke: Invoke, committed_sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await ok(invoke, *PLAN)
    await ok(invoke, "client", "add", "--telegram-id", "5001", "--first-name", "Анна")
    await ok(invoke, "client", "grant", "5001", "m1", "--no-sync")
    for n in range(2):
        await ok(
            invoke,
            *("device", "issue", "5001", "--name", f"d{n}", "--platform", "ios"),
            *("--out", str(tmp_path / f"{n}.p12"), "--no-sync"),
        )
    third = await invoke(
        *("device", "issue", "5001", "--name", "d3", "--platform", "ios"),
        *("--out", str(tmp_path / "3.p12"), "--no-sync"),
    )
    assert third.exit_code == 1
    assert "device_limit_reached" in third.output
    async with committed_sessionmaker() as session:
        assert len(list(await session.scalars(select(Device)))) == 2
