from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient, MakeDevice
from cryptography import x509
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.audit.models import AuditLog
from ocmanager.core.config import Settings
from ocmanager.flows import revocations as flows
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.driver.fake import FakeNodeDriver
from ocmanager.provisioning import service
from ocmanager.provisioning.models import Device, Revocation
from ocmanager.provisioning.pki.ca import CertificateAuthority

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
DAY = timedelta(days=1)


def serials(pem: bytes | None) -> set[int]:
    assert pem is not None
    return {r.serial_number for r in x509.load_pem_x509_crl(pem)}


async def revoke(session: AsyncSession, device: Device) -> None:
    await service.revoke_device(session, device.id, owner_client_id=None, reason="x", now=NOW)


@pytest.fixture
async def node_ready(session: AsyncSession, settings: Settings) -> None:
    await registry.ensure_local_node(session, settings)


async def test_nothing_pending_means_nothing_done(
    session: AsyncSession, settings: Settings, test_ca: CertificateAuthority, node_ready: None
) -> None:
    fake = FakeNodeDriver()
    with registry.override_driver(fake):
        assert await flows.apply_revocations(session, settings, test_ca, NOW) == 0
    assert fake.calls == []


async def test_revocation_reaches_the_node_and_kicks_the_user(
    session: AsyncSession,
    settings: Settings,
    test_ca: CertificateAuthority,
    node_ready: None,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    device = await make_device(client)
    other = await make_device(client, seq=2)
    await revoke(session, device)
    fake = FakeNodeDriver()
    fake.add_session(device.ocserv_username)
    fake.add_session(other.ocserv_username)

    with registry.override_driver(fake):
        assert await flows.apply_revocations(session, settings, test_ca, NOW) == 1

    assert serials(fake.crl) == {int(device.cert_serial, 16)}
    assert [s.username for s in fake.sessions] == [other.ocserv_username]
    assert ("reload", ()) in fake.calls
    rev = await session.scalar(select(Revocation))
    assert rev is not None
    assert rev.applied_at == NOW
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "revocation.apply"))
    assert row is not None
    assert (row.actor_type, row.details) == (
        "system",
        {"count": 1, "usernames": [device.ocserv_username]},
    )


async def test_crl_always_contains_every_revoked_serial(
    session: AsyncSession,
    settings: Settings,
    test_ca: CertificateAuthority,
    node_ready: None,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    first, second = await make_device(client), await make_device(client, seq=2)
    fake = FakeNodeDriver()
    with registry.override_driver(fake):
        await revoke(session, first)
        await flows.apply_revocations(session, settings, test_ca, NOW)
        await revoke(session, second)
        assert await flows.apply_revocations(session, settings, test_ca, NOW + DAY) == 1
        assert await flows.apply_revocations(session, settings, test_ca, NOW + 2 * DAY) == 0
    assert serials(fake.crl) == {int(first.cert_serial, 16), int(second.cert_serial, 16)}


async def test_unreachable_node_keeps_the_revocation_pending(
    session: AsyncSession,
    settings: Settings,
    test_ca: CertificateAuthority,
    node_ready: None,
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    device = await make_device(await make_client())
    await revoke(session, device)
    fake = FakeNodeDriver(occtl_ok=False)
    with registry.override_driver(fake):
        with pytest.raises(NodeUnreachable):
            await flows.apply_revocations(session, settings, test_ca, NOW)
        rev = await session.scalar(select(Revocation))
        assert rev is not None
        assert rev.applied_at is None
        assert serials(fake.crl) == {int(device.cert_serial, 16)}  # файл уже лежит

        fake.occtl_ok = True  # нода ожила — следующий запуск довершает
        assert await flows.apply_revocations(session, settings, test_ca, NOW + DAY) == 1
    assert rev.applied_at == NOW + DAY


async def test_refresh_publishes_a_fresh_crl_even_without_revocations(
    session: AsyncSession, settings: Settings, test_ca: CertificateAuthority, node_ready: None
) -> None:
    fake = FakeNodeDriver()
    with registry.override_driver(fake):
        await flows.refresh_crl(session, settings, test_ca, NOW)
    assert fake.crl is not None
    crl = x509.load_pem_x509_crl(fake.crl)
    assert crl.next_update_utc == NOW + 7 * DAY
    assert list(crl) == []


async def test_refresh_does_not_need_occtl(
    session: AsyncSession, settings: Settings, test_ca: CertificateAuthority, node_ready: None
) -> None:
    """CRL — файл: он обновляется и при молчащем occtl (ocserv 1.3 читает его сам)."""
    fake = FakeNodeDriver(occtl_ok=False)
    with registry.override_driver(fake):
        await flows.refresh_crl(session, settings, test_ca, NOW)
    assert fake.crl is not None
