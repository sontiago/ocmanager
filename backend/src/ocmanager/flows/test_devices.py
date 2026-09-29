import json
from datetime import UTC, datetime

import pytest
from conftest import MakeClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.core.errors import DeviceLimitReached, NotFound
from ocmanager.flows import devices
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.service import IssueResult

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
ACTOR = Actor("client", "1")


async def audit_rows(session: AsyncSession) -> list[AuditLog]:
    return list(await session.scalars(select(AuditLog).order_by(AuditLog.id)))


async def issue(
    session: AsyncSession, ca: CertificateAuthority, client_id: int, *, limit: int = 2
) -> IssueResult:
    return await devices.issue_device(
        session,
        client_id=client_id,
        name="Pixel",
        platform="android",
        device_limit=limit,
        ca=ca,
        actor=ACTOR,
        now=NOW,
    )


async def test_issue_is_audited_without_secrets(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    with capture_logs() as logs:
        result = await issue(session, test_ca, client.id)
    [row] = await audit_rows(session)
    assert row.action == "device.issue"
    assert (row.target_type, row.target_id) == ("device", str(result.device.id))
    assert row.details == {
        "client_id": client.id,
        "name": "Pixel",
        "platform": "android",
        "username": f"c{client.id}-d1",
    }
    # Ни пароль, ни содержимое .p12 не должны оказаться в аудите и в логах.
    haystack = json.dumps(row.details) + json.dumps(logs, default=str)
    assert result.password not in haystack
    assert result.p12.hex() not in haystack


async def test_failed_issue_is_not_audited(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    await issue(session, test_ca, client.id, limit=1)
    with pytest.raises(DeviceLimitReached):
        await issue(session, test_ca, client.id, limit=1)
    assert len(await audit_rows(session)) == 1


async def test_revoke_is_audited_once(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    client = await make_client()
    device = (await issue(session, test_ca, client.id)).device
    for _ in range(2):
        await devices.revoke_device(
            session,
            device.id,
            owner_client_id=client.id,
            reason="потерян",
            actor=ACTOR,
            now=NOW,
        )
    _, row = await audit_rows(session)
    assert row.action == "device.revoke"
    assert row.details == {
        "client_id": client.id,
        "username": device.ocserv_username,
        "reason": "потерян",
    }


async def test_foreign_revoke_is_not_audited(
    session: AsyncSession, make_client: MakeClient, test_ca: CertificateAuthority
) -> None:
    mine, other = await make_client(), await make_client()
    device = (await issue(session, test_ca, other.id)).device
    with pytest.raises(NotFound):
        await devices.revoke_device(
            session,
            device.id,
            owner_client_id=mine.id,
            reason="x",
            actor=ACTOR,
            now=NOW,
        )
    assert [r.action for r in await audit_rows(session)] == ["device.issue"]
