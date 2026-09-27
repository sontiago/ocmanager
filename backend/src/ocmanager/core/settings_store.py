"""Runtime-настройки: то, что владелец меняет из админки без перезапуска (дизайн §5).

Хранятся в таблице settings по ключу на поле. Пересечения с .env (Settings)
нет. Чтение терпит мусор в БД (поле откатывается к умолчанию), запись —
нет (InvalidInput).
"""

from dataclasses import dataclass
from typing import Any, Literal

import structlog
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.errors import InvalidInput
from ocmanager.core.models import SettingRow

log = structlog.get_logger(__name__)


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_days: int = Field(3, ge=1, le=30)
    trial_traffic_bytes: int = Field(5 * 1024**3, ge=0)
    default_lang: Literal["ru", "en"] = "ru"
    support_url: AnyHttpUrl | None = None
    admin_chat_ids: list[int] = Field(default_factory=list)
    expiry_reminder_days: list[int] = Field(default_factory=lambda: [3, 1])
    traffic_retention_days: int = Field(90, ge=7)


@dataclass(frozen=True)
class SettingsChange:
    settings: RuntimeSettings
    changed: dict[str, tuple[Any, Any]]  # ключ → (старое, новое) в JSON-виде


async def _stored(session: AsyncSession) -> dict[str, Any]:
    rows = await session.scalars(select(SettingRow))
    return {r.key: r.value for r in rows if r.key in RuntimeSettings.model_fields}


async def load(session: AsyncSession) -> RuntimeSettings:
    data = await _stored(session)
    try:
        return RuntimeSettings.model_validate(data)
    except ValidationError as exc:
        bad = {str(err["loc"][0]) for err in exc.errors() if err["loc"]}
        log.error("runtime_settings_invalid_in_db", keys=sorted(bad))
        return RuntimeSettings.model_validate({k: v for k, v in data.items() if k not in bad})


async def update(session: AsyncSession, patch: dict[str, Any]) -> SettingsChange:
    """Применяет частичное изменение. Валидируется весь результат, пишутся
    только изменённые ключи. Аудит (`settings.update` с `changed`) пишет вызывающий."""
    unknown = sorted(set(patch) - set(RuntimeSettings.model_fields))
    if unknown:
        raise InvalidInput(f"unknown settings: {', '.join(unknown)}")
    current = (await load(session)).model_dump(mode="json")
    try:
        new = RuntimeSettings.model_validate({**current, **patch})
    except ValidationError as exc:
        err = exc.errors()[0]
        raise InvalidInput(f"{'.'.join(map(str, err['loc']))}: {err['msg']}") from None
    new_json = new.model_dump(mode="json")
    changed = {k: (current[k], new_json[k]) for k in patch if current[k] != new_json[k]}
    for key in changed:
        stmt = insert(SettingRow).values(key=key, value=new_json[key])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SettingRow.key], set_={"value": stmt.excluded.value}
            )
        )
    return SettingsChange(settings=new, changed=changed)
