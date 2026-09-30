"""Подпись initData так же, как это делает Telegram. Нужна тестам и ручной проверке."""

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode


def sign(fields: dict[str, str], bot_token: str) -> str:
    """hash = HMAC_SHA256(HMAC_SHA256("WebAppData", bot_token), data-check-string)."""
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def make_init_data(
    bot_token: str,
    *,
    user: dict[str, Any],
    auth_date: int,
    extra: dict[str, str] | None = None,
) -> str:
    """Строка `initData`, которую примет `validate_init_data`. `extra` — дополнительные
    подписанные поля (`signature`, `chat_type`, …): они входят в data-check-string."""
    fields = {
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(auth_date),
        **(extra or {}),
    }
    return urlencode({**fields, "hash": sign(fields, bot_token)})
