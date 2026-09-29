"""Примитивы безопасности админки: пароли, TOTP, токены. Без БД и без HTTP."""

import hashlib
import secrets
from datetime import datetime
from functools import lru_cache

import bcrypt
import pyotp

# Стоимость bcrypt. Тесты, которым не нужна настоящая стойкость, понижают её через фикстуру.
BCRYPT_ROUNDS = 12
# bcrypt смотрит только на первые 72 байта; библиотека на длинном пароле бросает ValueError.
MAX_PASSWORD_BYTES = 72
TOTP_ISSUER = "ocmanager"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # пароль длиннее 72 байт или испорченный хеш — это просто «нет»
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def dummy_verify() -> None:
    """Тратит столько же времени, сколько настоящая проверка: по времени ответа нельзя
    отличить несуществующий логин от неверного пароля."""
    verify_password("x", _dummy_hash())


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=TOTP_ISSUER)


def verify_totp(secret: str, code: str, *, now: datetime) -> bool:
    """Окно ±1 шаг (30 с): часы телефона и сервера не бывают точными."""
    if len(code) != 6 or not (code.isascii() and code.isdigit()):
        return False
    return bool(pyotp.TOTP(secret).verify(code, for_time=now, valid_window=1))
