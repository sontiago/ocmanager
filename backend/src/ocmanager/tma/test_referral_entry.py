"""Привязка пригласившего при первом заходе в Mini App (initData.start_param)."""

from conftest import MakeClient, TmaHeaders
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.subscriptions import service as subscriptions


async def referred_by(session: AsyncSession, telegram_id: int) -> int | None:
    client = await subscriptions.find_client_by_telegram_id(session, telegram_id)
    assert client is not None
    await session.refresh(client)
    return client.referred_by


async def test_the_first_visit_with_a_referral_link_binds_the_inviter(
    public_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    tma_headers: TmaHeaders,
) -> None:
    inviter = await make_client()
    headers = tma_headers(telegram_id=8101, start_param=f"ref_{inviter.referral_code}")
    assert (await public_client.get("/api/tma/me", headers=headers)).status_code == 200
    assert await referred_by(session, 8101) == inviter.id


async def test_a_later_link_does_not_rebind_an_existing_client(
    public_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    tma_headers: TmaHeaders,
) -> None:
    first, second = await make_client(), await make_client()
    await public_client.get("/api/tma/me", headers=tma_headers(telegram_id=8102))  # без ссылки
    await public_client.get(
        "/api/tma/me",
        headers=tma_headers(telegram_id=8102, start_param=f"ref_{first.referral_code}"),
    )
    assert await referred_by(session, 8102) is None  # привязка только при создании клиента
    await public_client.get(
        "/api/tma/me",
        headers=tma_headers(telegram_id=8103, start_param=f"ref_{first.referral_code}"),
    )
    await public_client.get(
        "/api/tma/me",
        headers=tma_headers(telegram_id=8103, start_param=f"ref_{second.referral_code}"),
    )
    assert await referred_by(session, 8103) == first.id


async def test_garbage_start_params_are_ignored(
    public_client: AsyncClient, session: AsyncSession, tma_headers: TmaHeaders
) -> None:
    for i, param in enumerate(["ref_nosuchco", "ref_", "hello", "ref_!!!!!!!!"]):
        telegram_id = 8110 + i
        headers = tma_headers(telegram_id=telegram_id, start_param=param)
        assert (await public_client.get("/api/tma/me", headers=headers)).status_code == 200
        assert await referred_by(session, telegram_id) is None


async def test_the_attachment_is_audited(
    public_client: AsyncClient,
    session: AsyncSession,
    make_client: MakeClient,
    tma_headers: TmaHeaders,
) -> None:
    from sqlalchemy import select

    from ocmanager.audit.models import AuditLog

    inviter = await make_client()
    headers = tma_headers(telegram_id=8120, start_param=f"ref_{inviter.referral_code}")
    await public_client.get("/api/tma/me", headers=headers)
    row = await session.scalar(select(AuditLog).where(AuditLog.action == "referral.attach"))
    assert row is not None
    assert row.details == {"inviter_id": inviter.id}
