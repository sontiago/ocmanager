"""Tribute: подпись вебхуков и (с Задачи 5.2) разбор событий."""

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any

SIGNATURE_HEADER = "trbt-signature"


class TributeProvider:
    name = "tribute"

    def __init__(self, api_key: str) -> None:
        self._key = api_key.encode()

    def verify(self, body: bytes, headers: Mapping[str, str]) -> bool:
        sent = headers.get(SIGNATURE_HEADER, "").strip().lower()
        expected = hmac.new(self._key, body, hashlib.sha256).hexdigest()
        # Байты, а не строки: compare_digest(str, str) падает TypeError на не-ASCII.
        return hmac.compare_digest(sent.encode(), expected.encode())

    def event_id(self, body: bytes, payload: Mapping[str, Any]) -> str:
        """У вебхука Tribute нет собственного уникального идентификатора (гипотеза, 5.8): повтор
        доставки — побайтно то же тело, значит хеш тела — и есть идентификатор."""
        return hashlib.sha256(body).hexdigest()
