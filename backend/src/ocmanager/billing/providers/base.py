"""Контракт провайдера оплаты. Домен работает с событиями провайдер-агностично: детали Tribute
(имена полей, подпись) живут только в providers/tribute.py."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

ProviderEventKind = Literal[
    "subscription_started",
    "subscription_renewed",
    "subscription_cancelled",
    "refund",
    "ignored",
]


class ProviderPayloadError(ValueError):
    """Тело вебхука не соответствует ожидаемой форме. Повтор не поможет — вебхук уходит в dead."""


@dataclass(frozen=True)
class ProviderEvent:
    """То, что домен понимает в событии провайдера. Любое поле может отсутствовать: решает ли
    это беду, определяет обработка (flows/purchase.py), а не разбор."""

    kind: ProviderEventKind
    telegram_id: int | None
    external_payment_id: str | None  # ключ идемпотентности: payments UNIQUE(provider, external_id)
    external_subscription_id: str | None
    product_ref: str | None  # чем тариф связан с продуктом провайдера
    amount: int | None  # минорные единицы
    currency: str | None  # ISO 4217, верхний регистр
    raw_name: str  # исходное имя события — для логов и разбора


class PaymentProvider(Protocol):
    name: str

    def verify(self, body: bytes, headers: Mapping[str, str]) -> bool:
        """Подпись сходится. Заголовки приходят в нижнем регистре (Starlette нормализует)."""
        ...

    def event_id(self, body: bytes, payload: Mapping[str, Any]) -> str:
        """Идентификатор события для дедупликации повторных доставок."""
        ...

    def parse(self, payload: Mapping[str, Any]) -> ProviderEvent:
        """ProviderPayloadError — форма не та (повтор не поможет)."""
        ...
