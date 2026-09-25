import pytest
from pydantic import ValidationError

from ocmanager.core.config import Settings

BASE = {
    "OCM_DATABASE_URL": "postgresql+asyncpg://ocm:ocm@127.0.0.1:54320/ocmanager",
    "OCM_REDIS_URL": "redis://127.0.0.1:63790/0",
    "OCM_SECRET_KEY": "x" * 32,
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
