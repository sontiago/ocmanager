from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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
    # Серверный сертификат ocserv, который выпускает и продлевает Caddy (общий том). Воркер следит
    # за файлом и просит ноду перечитать его при смене. Не задан — слежения нет (dev).
    server_cert_path: Path | None = None
    # Общий секрет ноды и панели: им disconnect.sh подписывает отчёт о сессии.
    # В контейнер ноды попадает как OCM_INTERNAL_TOKEN (dev-compose, entrypoint.sh).
    internal_token: SecretStr = Field(min_length=32)
    # Адрес VPN для клиентов (SNI-имя в проде). Пишется в nodes.public_host.
    vpn_host: str = "localhost"
    # Порт VPN на стороне клиента. 443 в адрес не пишется; в dev ocserv проброшен на 4443.
    vpn_port: int = Field(443, ge=1, le=65535)
    # Секрет камуфляжа ocserv: `https://<vpn_host>/?<секрет>` открывает шлюз, остальное — «сайт».
    # Совпадает с OCSERV_CAMOUFLAGE_SECRET контейнера ноды.
    camouflage_secret: SecretStr = Field(min_length=4)
    # Публичный адрес панели: от него строятся ссылки на скачивание .p12. Без слэша на конце.
    public_base_url: str = "http://localhost:8000"
    # Токен бота: им подписана initData, которую присылает TMA.
    bot_token: SecretStr = Field(min_length=10)
    # Срок годности initData. TMA шлёт одну и ту же строку весь сеанс (решение №6).
    tma_initdata_ttl_s: int = Field(86400, ge=60, le=7 * 86400)
    # Принимать поддельную initData из frontend/tma/src/telegram/mockEnv.ts. Только для dev.
    tma_allow_dev_initdata: bool = False
    # Ключ API Tribute (кабинет автора, раздел API): им подписаны вебхуки, заголовок trbt-signature.
    # Не задан или пуст — /webhooks/tribute отвечает 404, как будто провайдера нет.
    tribute_api_key: SecretStr | None = None

    @field_validator("public_base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("нужен адрес вида https://panel.example.com")
        return value

    @model_validator(mode="after")
    def _production_is_strict(self) -> Self:
        if self.env == "production":
            if self.tma_allow_dev_initdata:
                raise ValueError("tma_allow_dev_initdata нельзя включать в production")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("в production public_base_url должен быть https://")
        return self


def get_settings() -> Settings:
    """Настройки процесса. Вызывается только в точках входа (apps/, alembic/env.py);
    библиотечный код получает Settings параметром."""
    return Settings()
