import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.errors import NotFound
from ocmanager.subscriptions import service
from ocmanager.subscriptions.schemas import TelegramIdentity


def ident(
    telegram_id: int = 5001,
    first_name: str = "Anna",
    username: str | None = "anna",
    language_code: str | None = "ru",
) -> TelegramIdentity:
    return TelegramIdentity(telegram_id, first_name, username, language_code)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("RU", "ru"),
        ("en", "en"),
        ("uk", "en"),
        (None, "en"),
    ],
)
def test_lang_from_telegram(code: str | None, expected: str) -> None:
    assert service.lang_from_telegram(code) == expected


async def test_upsert_creates_client(session: AsyncSession) -> None:
    result = await service.upsert_client(session, ident())
    assert result.created
    c = result.client
    assert (c.telegram_id, c.first_name, c.username, c.lang) == (
        5001,
        "Anna",
        "anna",
        "ru",
    )
    assert (c.is_blocked, c.trial_used_at) == (False, None)


async def test_upsert_updates_profile_and_keeps_id(session: AsyncSession) -> None:
    first = await service.upsert_client(session, ident())
    second = await service.upsert_client(
        session, ident(first_name="Anya", username=None, language_code="en")
    )
    assert not second.created
    c = second.client
    assert c.id == first.client.id
    assert (c.first_name, c.username, c.lang) == ("Anya", None, "en")


async def test_upsert_does_not_touch_block_or_trial(session: AsyncSession) -> None:
    c = (await service.upsert_client(session, ident())).client
    c.is_blocked = True
    await session.flush()
    again = (await service.upsert_client(session, ident())).client
    assert again.is_blocked


async def test_get_and_find(session: AsyncSession) -> None:
    c = (await service.upsert_client(session, ident())).client
    assert (await service.get_client(session, c.id)).id == c.id
    found = await service.find_client_by_telegram_id(session, 5001)
    assert found is not None
    assert found.id == c.id
    assert await service.find_client_by_telegram_id(session, 404) is None
    with pytest.raises(NotFound):
        await service.get_client(session, 999_999)
