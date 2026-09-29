import json
from datetime import UTC, datetime, timedelta

import pytest
from arq import ArqRedis
from conftest import MakeClient, MakePlan, MakeSubscription
from cryptography.hazmat.primitives.serialization import pkcs12
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from ocmanager.audit.models import AuditLog
from ocmanager.audit.service import Actor
from ocmanager.core.crypto import derive_fernet
from ocmanager.core.errors import DeviceLimitReached, NotFound, SubscriptionInactive
from ocmanager.flows import devices
from ocmanager.flows import subscriptions as sub_flows
from ocmanager.provisioning import delivery
from ocmanager.provisioning.models import Device
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.service import IssueResult
from ocmanager.subscriptions import service as subscriptions

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


# --- issue_for_client ------------------------------------------------------

FERNET = derive_fernet("k" * 32, purpose=b"p12-delivery")
DAY = timedelta(days=1)


async def bundle(
    session: AsyncSession,
    redis: ArqRedis,
    ca: CertificateAuthority,
    client_id: int,
    *,
    now: datetime = NOW,
) -> devices.IssuedDeviceBundle:
    return await devices.issue_for_client(
        session,
        redis,
        client_id=client_id,
        name="Pixel",
        platform="android",
        ca=ca,
        fernet=FERNET,
        actor=ACTOR,
        now=now,
    )


async def test_client_with_a_live_subscription_gets_a_device_and_a_link(
    session: AsyncSession,
    redis: ArqRedis,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    test_ca: CertificateAuthority,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    result = await bundle(session, redis, test_ca, client.id)
    assert result.device.ocserv_username == f"c{client.id}-d1"
    assert result.ticket.expires_at == NOW + timedelta(minutes=15)
    filename, p12 = await delivery.take_p12(redis, FERNET, result.ticket.token) or ("", b"")
    assert filename == f"c{client.id}-d1.p12"
    key, cert, _ = pkcs12.load_key_and_certificates(p12, result.password.encode())
    assert key is not None
    assert cert is not None
    assert await delivery.take_p12(redis, FERNET, result.ticket.token) is None  # одноразовая


async def test_the_limit_comes_from_the_subscription_snapshot(
    session: AsyncSession,
    redis: ArqRedis,
    make_client: MakeClient,
    make_plan: MakePlan,
    test_ca: CertificateAuthority,
) -> None:
    client, plan = await make_client(), await make_plan(device_limit=1)
    await sub_flows.activate(
        session,
        client.id,
        sub_flows.terms_from_plan(plan),
        ACTOR,
        NOW,
        auto_renew=False,
    )
    await bundle(session, redis, test_ca, client.id)
    with pytest.raises(DeviceLimitReached):
        await bundle(session, redis, test_ca, client.id)


@pytest.mark.parametrize("state", ["none", "expired", "blocked"])
async def test_no_device_without_access(
    session: AsyncSession,
    redis: ArqRedis,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    test_ca: CertificateAuthority,
    state: str,
) -> None:
    client = await make_client()
    if state != "none":
        await make_subscription(client, days=1, now=NOW)
    if state == "blocked":
        await subscriptions.set_blocked(session, client.id, True, NOW)
    when = NOW + 2 * DAY if state == "expired" else NOW  # срок вышел, cron ещё не отработал
    with pytest.raises(SubscriptionInactive) as info:
        await bundle(session, redis, test_ca, client.id, now=when)
    assert info.value.status == (403 if state == "blocked" else 409)
    assert list(await session.scalars(select(Device))) == []
    assert await redis.keys("p12:*") == []


async def test_redis_failure_leaves_no_device_behind(
    session: AsyncSession,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    test_ca: CertificateAuthority,
) -> None:
    class BrokenRedis:
        async def set(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("redis down")

    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    with pytest.raises(ConnectionError):
        async with session.begin_nested():  # как транзакция запроса: ошибка откатывает всё
            await bundle(session, BrokenRedis(), test_ca, client.id)  # type: ignore[arg-type]
    assert list(await session.scalars(select(Device))) == []


async def test_client_revokes_only_their_own_device(
    session: AsyncSession,
    redis: ArqRedis,
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    test_ca: CertificateAuthority,
) -> None:
    mine, other = await make_client(), await make_client()
    await make_subscription(mine, days=30, now=NOW)
    device = (await bundle(session, redis, test_ca, mine.id)).device
    with pytest.raises(NotFound):
        await devices.revoke_for_client(
            session, client_id=other.id, device_id=device.id, actor=ACTOR, now=NOW
        )
    await devices.revoke_for_client(
        session, client_id=mine.id, device_id=device.id, actor=ACTOR, now=NOW
    )
    assert device.revoked_at == NOW
    assert device.revocation_reason == "revoked by client"
