from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

import ocmanager
from ocmanager.admin.deps import CurrentAdmin, SettingsDep
from ocmanager.audit import service as audit
from ocmanager.core import settings_store
from ocmanager.core.db import SessionDep
from ocmanager.nodes import registry
from ocmanager.nodes.driver.base import NodeUnreachable

log = structlog.get_logger(__name__)

router = APIRouter(tags=["settings"])


class EnvironmentOut(BaseModel):
    """Что процесс получил из `.env`. Только то, что безопасно показать: ни ключей,
    ни токенов, ни адресов баз с паролями."""

    env: str
    vpn_host: str
    ocserv_container: str
    version: str


class SettingsOut(BaseModel):
    runtime: dict[str, Any]  # меняется из админки без перезапуска
    environment: EnvironmentOut  # только для чтения: правится в .env


def _out(runtime: settings_store.RuntimeSettings, settings: SettingsDep) -> SettingsOut:
    return SettingsOut(
        runtime=runtime.model_dump(mode="json"),
        environment=EnvironmentOut(
            env=settings.env,
            vpn_host=settings.vpn_host,
            ocserv_container=settings.ocserv_container,
            version=ocmanager.__version__,
        ),
    )


@router.get("/settings")
async def get_settings(ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep) -> SettingsOut:
    return _out(await settings_store.load(db), settings)


@router.patch("/settings")
async def patch_settings(
    patch: dict[str, Any], ctx: CurrentAdmin, db: SessionDep, settings: SettingsDep
) -> SettingsOut:
    """Частичное обновление: валидируется весь результат, пишутся только изменившиеся ключи.
    Неизвестный ключ или недопустимое значение — 422. Аудит — только если что-то изменилось."""
    change = await settings_store.update(db, patch)
    if change.changed:
        await audit.record(
            db,
            ctx.actor,
            "settings.update",
            target_type="settings",
            details={"changed": {k: [old, new] for k, (old, new) in change.changed.items()}},
        )
    await db.commit()
    if "bypass_routes" in change.changed:
        # Нода недоступна — настройка уже сохранена, а сверка (раз в 5 минут) доставит файл.
        try:
            await registry.local_driver(settings).publish_routes(change.settings.bypass_routes)
        except (NodeUnreachable, OSError) as exc:
            log.warning("bypass_routes_publish_failed", error=str(exc)[:300])
    return _out(change.settings, settings)
