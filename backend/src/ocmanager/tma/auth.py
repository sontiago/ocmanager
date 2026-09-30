"""Проверка initData из Telegram Mini Apps.

Алгоритм — из документации Telegram: в data-check-string входят все поля, кроме `hash`
(включая `signature`), отсортированные по имени.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import parse_qsl

from ocmanager.core.errors import InitDataExpired, Unauthorized
from ocmanager.subscriptions.schemas import TelegramIdentity

# initData из mockEnv фронтенда: подпись заведомо недействительна.
DEV_HASH: Final = "dev-mock-hash"
MAX_RAW_LEN: Final = 4096
# Часы Telegram и наши могут расходиться, но не на минуты.
MAX_FUTURE_SKEW: Final = timedelta(minutes=5)
# Telegram-id помещаются в 52 бита; всё, что больше, — не он.
MAX_TELEGRAM_ID: Final = 2**52


@dataclass(frozen=True)
class InitData:
    user: TelegramIdentity
    auth_date: datetime


def _malformed() -> Unauthorized:
    # Без подробностей и без самой строки: в ответ и в логи initData попадать не должна.
    return Unauthorized("malformed initData")


def _identity(user: Any) -> TelegramIdentity:
    if not isinstance(user, dict):
        raise _malformed()
    tg_id, first_name = user.get("id"), user.get("first_name")
    if isinstance(tg_id, bool) or not isinstance(tg_id, int) or not 0 < tg_id < MAX_TELEGRAM_ID:
        raise _malformed()
    if not isinstance(first_name, str):
        raise _malformed()
    username, language = user.get("username"), user.get("language_code")
    return TelegramIdentity(
        telegram_id=tg_id,
        first_name=first_name.strip()[:128] or str(tg_id),
        username=username[:64] if isinstance(username, str) and username else None,
        language_code=language[:16] if isinstance(language, str) else None,
    )


def validate_init_data(
    raw: str, bot_token: str, *, ttl_s: int, now: datetime, allow_dev: bool = False
) -> InitData:
    if not raw or len(raw) > MAX_RAW_LEN:
        raise _malformed()
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise _malformed() from None
    data = dict(pairs)
    if len(data) != len(pairs):  # повторяющееся поле: подпись бы «выбрала» последнее
        raise _malformed()
    received = data.pop("hash", None)
    if not received:
        raise Unauthorized("no hash")

    if not (allow_dev and received == DEV_HASH):
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        # Байты, а не строки: compare_digest падает с TypeError на не-ASCII в str.
        if not hmac.compare_digest(expected.encode(), received.encode()):
            raise Unauthorized("bad hash")

    try:
        auth_date = datetime.fromtimestamp(int(data["auth_date"]), UTC)
        user = json.loads(data["user"])
    except (KeyError, ValueError, OverflowError, OSError):
        raise _malformed() from None
    if auth_date - now > MAX_FUTURE_SKEW:
        raise Unauthorized("auth_date is in the future")
    if now - auth_date > timedelta(seconds=ttl_s):
        raise InitDataExpired("initData expired")
    return InitData(user=_identity(user), auth_date=auth_date)
