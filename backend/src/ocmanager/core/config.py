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


def get_settings() -> Settings:
    """Настройки процесса. Вызывается только в точках входа (apps/, alembic/env.py);
    библиотечный код получает Settings параметром."""
    return Settings()
