"""Помощники тестов платежей: подпись и фикстуры вебхуков."""

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

# billing/testing.py → parents: billing, ocmanager, src, backend
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "webhooks" / "tribute"


def sign(body: bytes, api_key: str) -> str:
    """trbt-signature: HMAC-SHA256 тела запроса ключом API, hex."""
    return hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def webhook_body(name: str, **payload_overrides: Any) -> bytes:
    """Фикстура как есть или с подменой полей внутри `payload`.
    Подмена меняет тело, а значит и идентификатор события: так тесты получают «другой вебхук»
    про тот же платёж."""
    raw = fixture_bytes(name)
    if not payload_overrides:
        return raw
    data = json.loads(raw)
    data["payload"].update(payload_overrides)
    return json.dumps(data, separators=(",", ":")).encode()
