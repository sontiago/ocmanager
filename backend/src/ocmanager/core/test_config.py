from pathlib import Path

import pytest
from pydantic import ValidationError

from ocmanager.core.config import Settings

BASE = {
    "OCM_DATABASE_URL": "postgresql+asyncpg://ocm:ocm@127.0.0.1:54320/ocmanager",
    "OCM_REDIS_URL": "redis://127.0.0.1:63790/0",
    "OCM_SECRET_KEY": "x" * 32,
    "OCM_PKI_DIR": "../.dev/pki",
    "OCM_OCSERV_STATE_DIR": "../.dev/ocserv-state",
    "OCM_INTERNAL_TOKEN": "t" * 32,
    "OCM_CAMOUFLAGE_SECRET": "devsecret",
    "OCM_BOT_TOKEN": "123456:bot-token-value",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ("OCM_ENV", "OCM_LOG_LEVEL", "OCM_LOG_FORMAT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in BASE.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_reads_env_with_defaults(env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert s.database_url.endswith("/ocmanager")
    assert s.secret_key.get_secret_value() == "x" * 32
    assert (s.env, s.log_level, s.log_format) == ("dev", "INFO", "json")


def test_secret_key_hidden_in_repr(env: pytest.MonkeyPatch) -> None:
    assert "x" * 32 not in repr(Settings(_env_file=None))


def test_short_secret_key_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("OCM_SECRET_KEY", "short")
    with pytest.raises(ValidationError, match="secret_key"):
        Settings(_env_file=None)


def test_missing_database_url_rejected(env: pytest.MonkeyPatch) -> None:
    env.delenv("OCM_DATABASE_URL")
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_unknown_env_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("OCM_ENV", "staging")
    with pytest.raises(ValidationError, match="env"):
        Settings(_env_file=None)


def test_paths_are_path_objects(env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert s.pki_dir == Path("../.dev/pki")
    assert s.ocserv_state_dir.name == "ocserv-state"


def test_missing_pki_dir_rejected(env: pytest.MonkeyPatch) -> None:
    env.delenv("OCM_PKI_DIR")
    with pytest.raises(ValidationError, match="pki_dir"):
        Settings(_env_file=None)


def test_internal_token_is_required_long_and_hidden(env: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).internal_token.get_secret_value() == "t" * 32
    assert "t" * 32 not in repr(Settings(_env_file=None))
    env.setenv("OCM_INTERNAL_TOKEN", "short")
    with pytest.raises(ValidationError, match="internal_token"):
        Settings(_env_file=None)
    env.delenv("OCM_INTERNAL_TOKEN")
    with pytest.raises(ValidationError, match="internal_token"):
        Settings(_env_file=None)


def test_tma_settings_have_safe_defaults_and_hide_secrets(env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert (s.vpn_port, s.tma_initdata_ttl_s, s.tma_allow_dev_initdata) == (443, 86400, False)
    assert s.public_base_url == "http://localhost:8000"
    assert "bot-token-value" not in repr(s)
    assert "devsecret" not in repr(s)


@pytest.mark.parametrize("name", ["OCM_BOT_TOKEN", "OCM_CAMOUFLAGE_SECRET"])
def test_bot_token_and_camouflage_secret_are_required(env: pytest.MonkeyPatch, name: str) -> None:
    env.delenv(name)
    with pytest.raises(ValidationError, match=name.removeprefix("OCM_").lower()):
        Settings(_env_file=None)


def test_public_base_url_loses_its_trailing_slash_and_needs_a_scheme(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("OCM_PUBLIC_BASE_URL", "https://panel.example.com/")
    assert Settings(_env_file=None).public_base_url == "https://panel.example.com"
    env.setenv("OCM_PUBLIC_BASE_URL", "panel.example.com")
    with pytest.raises(ValidationError, match="public_base_url"):
        Settings(_env_file=None)


def test_production_refuses_dev_initdata_and_plain_http(env: pytest.MonkeyPatch) -> None:
    env.setenv("OCM_ENV", "production")
    env.setenv("OCM_PUBLIC_BASE_URL", "https://panel.example.com")
    assert Settings(_env_file=None).env == "production"
    env.setenv("OCM_TMA_ALLOW_DEV_INITDATA", "true")
    with pytest.raises(ValidationError, match="tma_allow_dev_initdata"):
        Settings(_env_file=None)
    env.setenv("OCM_TMA_ALLOW_DEV_INITDATA", "false")
    env.setenv("OCM_PUBLIC_BASE_URL", "http://panel.example.com")
    with pytest.raises(ValidationError, match="https"):
        Settings(_env_file=None)


def test_the_tribute_key_is_optional_and_hidden(env: pytest.MonkeyPatch) -> None:
    env.delenv("OCM_TRIBUTE_API_KEY", raising=False)  # conftest задаёт его для остальных тестов
    assert Settings(_env_file=None).tribute_api_key is None
    env.setenv("OCM_TRIBUTE_API_KEY", "tribute-key-0123456789")
    settings = Settings(_env_file=None)
    assert settings.tribute_api_key is not None
    assert "tribute-key-0123456789" not in repr(settings)
