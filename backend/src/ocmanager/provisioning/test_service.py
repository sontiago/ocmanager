import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import MakeClient
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.errors import Conflict, DeviceLimitReached, InvalidInput, NotFound
from ocmanager.events.models import EventOutbox
from ocmanager.provisioning import service
from ocmanager.provisioning.models import Revocation
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.certs import USERNAME_RE

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


async def issue(
    session: AsyncSession,
    ca: CertificateAuthority,
    client_id: int,
    *,
    limit: int = 3,
    **over: str,
) -> service.IssueResult:
    args = {"name": "Телефон", "platform": "ios"} | over
    return await service.issue_device(
        session, client_id=client_id, device_limit=limit, ca=ca, now=NOW, **args
    )


async def events(session: AsyncSession) -> list[tuple[str, dict[str, object]]]:
    rows = await session.scalars(select(EventOutbox).order_by(EventOutbox.id))
    return [(r.name, r.payload) for r in rows]


async def test_issue_creates_device_with_working_p12(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    result = await issue(session, test_ca, client.id, name="  Телефон Ани ")
    d = result.device
    assert d.ocserv_username == f"c{client.id}-d1"
    assert USERNAME_RE.fullmatch(d.ocserv_username)
    assert (d.seq, d.name, d.platform, d.client_id) == (
        1,
        "Телефон Ани",
        "ios",
        client.id,
    )
    assert (d.issued_at, d.revoked_at) == (NOW, None)
    assert d.cert_expires_at == NOW + timedelta(days=397)

    key, cert, extra = pkcs12.load_key_and_certificates(result.p12, result.password.encode())
    assert key is not None
    assert cert is not None
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == d.ocserv_username
    assert d.cert_serial == format(cert.serial_number, "x")
    assert extra is not None
    assert [c.subject for c in extra] == [test_ca.cert.subject]
    assert await events(session) == [("device.issued", {"client_id": client.id, "device_id": d.id})]


async def test_serials_and_usernames_are_unique(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    a, b = await make_client(), await make_client()
    devices = [
        (await issue(session, test_ca, a.id)).device,
        (await issue(session, test_ca, a.id)).device,
        (await issue(session, test_ca, b.id)).device,
    ]
    assert len({d.cert_serial for d in devices}) == 3
    assert [d.ocserv_username for d in devices] == [
        f"c{a.id}-d1",
        f"c{a.id}-d2",
        f"c{b.id}-d1",
    ]


async def test_limit_counts_only_active_and_numbers_are_never_reused(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    first = (await issue(session, test_ca, client.id, limit=2)).device
    await issue(session, test_ca, client.id, limit=2)
    with pytest.raises(DeviceLimitReached):
        await issue(session, test_ca, client.id, limit=2)
    await service.revoke_device(session, first.id, owner_client_id=None, reason="lost", now=NOW)
    third = (await issue(session, test_ca, client.id, limit=2)).device
    assert third.seq == 3  # d1 отозван, но его номер не возвращается
    assert await service.count_active(session, client.id) == 2


async def test_limit_is_per_client(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    a, b = await make_client(), await make_client()
    await issue(session, test_ca, a.id, limit=1)
    await issue(session, test_ca, b.id, limit=1)


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "a\x00b", "a\nb", "zero​width"])
async def test_bad_names_are_refused(
    session: AsyncSession,
    make_client: MakeClient,
    test_ca: CertificateAuthority,
    name: str,
) -> None:
    client = await make_client()
    with pytest.raises(InvalidInput):
        await issue(session, test_ca, client.id, name=name)
    assert await events(session) == []


async def test_border_names_are_accepted(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    assert (await issue(session, test_ca, client.id, name="x" * 40)).device.name == "x" * 40
    assert (await issue(session, test_ca, client.id, name="📱 Pixel")).device.name == "📱 Pixel"


async def test_unknown_platform_is_refused(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    with pytest.raises(InvalidInput):
        await issue(session, test_ca, client.id, platform="symbian")


async def test_number_space_exhaustion(
    session: AsyncSession,
    make_client: MakeClient,
    test_ca: CertificateAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "MAX_SEQ", 1)
    client = await make_client()
    first = (await issue(session, test_ca, client.id)).device
    await service.revoke_device(session, first.id, owner_client_id=None, reason="x", now=NOW)
    with pytest.raises(Conflict):
        await issue(session, test_ca, client.id)


async def test_revoke_records_revocation_and_event(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    device = (await issue(session, test_ca, client.id)).device
    later = NOW + timedelta(days=1)
    result = await service.revoke_device(
        session, device.id, owner_client_id=client.id, reason=" потерян ", now=later
    )
    assert result.changed
    assert (device.revoked_at, device.revocation_reason) == (later, "потерян")
    rev = await session.scalar(select(Revocation))
    assert rev is not None
    assert (rev.device_id, rev.cert_serial, rev.revoked_at, rev.applied_at) == (
        device.id,
        device.cert_serial,
        later,
        None,
    )
    assert (await events(session))[-1] == (
        "device.revoked",
        {
            "client_id": client.id,
            "device_id": device.id,
            "username": device.ocserv_username,
        },
    )


async def test_revoking_twice_is_idempotent(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    device = (await issue(session, test_ca, client.id)).device
    await service.revoke_device(session, device.id, owner_client_id=None, reason="a", now=NOW)
    again = await service.revoke_device(
        session,
        device.id,
        owner_client_id=None,
        reason="b",
        now=NOW + timedelta(days=1),
    )
    assert not again.changed
    assert device.revocation_reason == "a"  # первая причина не затирается
    assert [n for n, _ in await events(session)].count("device.revoked") == 1
    assert len((await session.scalars(select(Revocation))).all()) == 1


async def test_foreign_and_unknown_devices_look_the_same(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    mine, other = await make_client(), await make_client()
    theirs = (await issue(session, test_ca, other.id)).device
    with pytest.raises(NotFound):
        await service.revoke_device(
            session, theirs.id, owner_client_id=mine.id, reason="x", now=NOW
        )
    with pytest.raises(NotFound):
        await service.revoke_device(session, 999_999, owner_client_id=mine.id, reason="x", now=NOW)
    assert theirs.revoked_at is None


@pytest.mark.parametrize("reason", ["", "  ", "x" * 201])
async def test_revoke_needs_a_sane_reason(
    session: AsyncSession,
    make_client: MakeClient,
    test_ca: CertificateAuthority,
    reason: str,
) -> None:
    client = await make_client()
    device = (await issue(session, test_ca, client.id)).device
    with pytest.raises(InvalidInput):
        await service.revoke_device(
            session, device.id, owner_client_id=None, reason=reason, now=NOW
        )


async def test_list_devices(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    a = (await issue(session, test_ca, client.id)).device
    b = (await issue(session, test_ca, client.id)).device
    await service.revoke_device(session, a.id, owner_client_id=None, reason="x", now=NOW)
    assert [d.id for d in await service.list_devices(session, client.id)] == [b.id]
    everything = await service.list_devices(session, client.id, include_revoked=True)
    assert [d.id for d in everything] == [a.id, b.id]


async def test_parallel_issuing_respects_the_limit(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    test_ca: CertificateAuthority,
) -> None:
    """Advisory lock на клиента: при лимите 1 из пяти одновременных запросов успевает один."""
    async with committed_sessionmaker() as s, s.begin():
        client_id = await s.scalar(
            text(
                "INSERT INTO clients (telegram_id, first_name, lang)"
                " VALUES (777, 'A', 'ru') RETURNING id"
            )
        )
    assert client_id is not None

    async def one() -> service.IssueResult:
        async with committed_sessionmaker() as s, s.begin():
            return await issue(s, test_ca, client_id, limit=1)

    results = await asyncio.gather(*(one() for _ in range(5)), return_exceptions=True)
    assert sum(isinstance(r, service.IssueResult) for r in results) == 1
    assert sum(isinstance(r, DeviceLimitReached) for r in results) == 4


def test_ca_fixture_is_a_real_ca(test_ca: CertificateAuthority) -> None:
    bc = test_ca.cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca


async def test_double_click_on_revoke_revokes_once(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    test_ca: CertificateAuthority,
) -> None:
    """Два одновременных отзыва одного устройства (двойной тап в TMA): одна запись об отзыве,
    одно событие, второй запрос получает «уже отозвано»."""
    async with committed_sessionmaker() as s, s.begin():
        client_id = await s.scalar(
            text(
                "INSERT INTO clients (telegram_id, first_name, lang)"
                " VALUES (888, 'A', 'ru') RETURNING id"
            )
        )
        assert client_id is not None
        device_id = (await issue(s, test_ca, client_id)).device.id

    async def revoke() -> service.RevokeResult:
        async with committed_sessionmaker() as s, s.begin():
            return await service.revoke_device(
                s, device_id, owner_client_id=client_id, reason="tap", now=NOW
            )

    results = await asyncio.gather(revoke(), revoke())
    assert sorted(r.changed for r in results) == [False, True]
    async with committed_sessionmaker() as s:
        assert len((await s.scalars(select(Revocation))).all()) == 1
        names = [n for n, _ in await events(s)]
        assert names.count("device.revoked") == 1
