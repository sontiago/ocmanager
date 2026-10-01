"""Контракт провайдера оплаты. Домен работает с событиями провайдер-агностично: детали Tribute
(имена полей, подпись) живут только в providers/tribute.py."""

from collections.abc import Mapping
from typing import Any, Protocol


class ProviderPayloadError(ValueError):
    """Тело вебхука не соответствует ожидаемой форме. Повтор не поможет — вебхук уходит в dead."""


class PaymentProvider(Protocol):
    name: str

    def verify(self, body: bytes, headers: Mapping[str, str]) -> bool:
        """Подпись сходится. Заголовки приходят в нижнем регистре (Starlette нормализует)."""
        ...

    def event_id(self, body: bytes, payload: Mapping[str, Any]) -> str:
        """Идентификатор события для дедупликации повторных доставок."""
        ...
