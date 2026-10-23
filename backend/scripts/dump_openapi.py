"""Схема OpenAPI админ-API или публичного API без запуска серверов и баз.

    uv run python scripts/dump_openapi.py admin|public > openapi.json

Нужна для типов фронтенда (`make admin-types`) и для CI: типы в репозитории не должны отставать
от кода. Настройки — заглушки: `create_app` не подключается ни к базе, ни к Redis (это делает
lifespan, который здесь не запускается), поэтому реального окружения не требуется.
"""

import json
import sys
from pathlib import Path
from typing import Any

from ocmanager.apps import admin_api, public_api
from ocmanager.core.config import Settings

TARGETS = {"admin": admin_api.create_app, "public": public_api.create_app}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://stub:stub@127.0.0.1:1/stub",
        redis_url="redis://127.0.0.1:1/0",
        secret_key="0" * 32,
        pki_dir=Path("/nonexistent/pki"),
        ocserv_state_dir=Path("/nonexistent/state"),
        internal_token="0" * 32,
        camouflage_secret="stub-secret",  # noqa: S106 — заглушка, не секрет
        bot_token="000000:stub-token",  # noqa: S106 — заглушка, не секрет
    )


def build_schema(target: str) -> dict[str, Any]:
    return TARGETS[target](_settings()).openapi()


def main(argv: list[str]) -> None:
    if len(argv) != 1 or argv[0] not in TARGETS:
        raise SystemExit(f"usage: dump_openapi.py {'|'.join(TARGETS)}")
    print(json.dumps(build_schema(argv[0]), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
