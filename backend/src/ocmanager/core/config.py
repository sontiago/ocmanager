from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "production"] = "dev"
    database_url: str
    redis_url: str
    secret_key: SecretStr = Field(min_length=32)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    # ca.key (0600) и ca.crt. Только для бэкенда: в контейнер ноды не монтируется.
    pki_dir: Path
    # Общий с контейнером ocserv каталог: ca.crt, crl.pem, allowed.list,
    # в dev ещё server.crt/server.key.
    ocserv_state_dir: Path
    # Имя контейнера ноды для docker exec/inspect/logs. Никогда не из запроса.
    ocserv_container: str = "ocm-ocserv"
    # Адрес VPN для клиентов (SNI-имя в проде). Пишется в nodes.public_host.
    vpn_host: str = "localhost"


def get_settings() -> Settings:
    """Настройки процесса. Вызывается только в точках входа (apps/, alembic/env.py);
    библиотечный код получает Settings параметром."""
    return Settings()
