import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.core.errors import InvalidInput
from ocmanager.core.models import SettingRow
from ocmanager.core.settings_store import RuntimeSettings


async def stored(session: AsyncSession) -> dict[str, object]:
    return {r.key: r.value for r in await session.scalars(select(SettingRow))}


async def test_empty_table_gives_defaults(session: AsyncSession) -> None:
    s = await settings_store.load(session)
    assert s == RuntimeSettings()
    assert (s.trial_days, s.default_lang, s.expiry_reminder_days) == (3, "ru", [3, 1])


async def test_update_writes_only_changed_keys(session: AsyncSession) -> None:
    change = await settings_store.update(session, {"trial_days": 7, "default_lang": "ru"})
    assert change.settings.trial_days == 7
    assert change.changed == {"trial_days": (3, 7)}
    assert await stored(session) == {"trial_days": 7}
    assert (await settings_store.load(session)).trial_days == 7


async def test_update_overwrites_existing_key(session: AsyncSession) -> None:
    await settings_store.update(session, {"trial_days": 7})
    change = await settings_store.update(session, {"trial_days": 10})
    assert change.changed == {"trial_days": (7, 10)}
    assert await stored(session) == {"trial_days": 10}


async def test_noop_update_changes_nothing(session: AsyncSession) -> None:
    change = await settings_store.update(session, {"trial_days": 3})
    assert change.changed == {}
    assert await stored(session) == {}


async def test_url_is_normalized_to_json(session: AsyncSession) -> None:
    change = await settings_store.update(session, {"support_url": "https://t.me/help"})
    assert change.changed == {"support_url": (None, "https://t.me/help")}


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"trial_days": 0}, "trial_days"),
        ({"default_lang": "de"}, "default_lang"),
        ({"support_url": "not a url"}, "support_url"),
        ({"nope": 1}, "unknown settings: nope"),
    ],
)
async def test_invalid_update_rejected(
    session: AsyncSession, patch: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidInput, match=message):
        await settings_store.update(session, patch)
    assert await stored(session) == {}


async def test_garbage_in_db_falls_back_to_default(session: AsyncSession) -> None:
    session.add(SettingRow(key="trial_days", value="many"))
    session.add(SettingRow(key="default_lang", value="en"))
    session.add(SettingRow(key="removed_setting", value=1))
    await session.flush()
    s = await settings_store.load(session)
    assert (s.trial_days, s.default_lang) == (3, "en")


async def test_nullable_setting_can_be_cleared(session: AsyncSession) -> None:
    await settings_store.update(session, {"support_url": "https://t.me/help"})
    change = await settings_store.update(session, {"support_url": None})
    assert change.changed == {"support_url": ("https://t.me/help", None)}
    assert (await settings_store.load(session)).support_url is None
