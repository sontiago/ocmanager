"""Tribute: подпись вебхуков и разбор событий в ProviderEvent. Вся специфика Tribute — здесь.

Схема payload — по OpenAPI Tribute (tribute.tg/api/v1/openapi/en); подтверждение живым
вебхуком — Задача 5.8 (см. tests/fixtures/webhooks/tribute/README.md)."""

import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from ocmanager.billing.providers.base import ProviderEvent, ProviderEventKind, ProviderPayloadError

SIGNATURE_HEADER = "trbt-signature"
MAX_ID_LEN = 64
MAX_AMOUNT = 10**12  # как billing.plans.MAX_PRICE: больше — заведомо мусор

# Ключи — имена событий без `_`/`-` и в нижнем регистре: спека пишет newSubscription,
# документация Tribute — new_subscription (П5-3).
_KINDS: Final[dict[str, ProviderEventKind]] = {
    "newsubscription": "subscription_started",
    "renewedsubscription": "subscription_renewed",
    "cancelledsubscription": "subscription_cancelled",
    # Настоящее имя в OpenAPI Tribute — digital_product_refunded; короткое — про запас.
    "digitalproductrefunded": "refund",
    "digitalproductrefund": "refund",
}


def _normalize(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def _text(value: Any) -> str | None:
    """Идентификатор как непустая короткая строка; число допустимо."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        return value if value and len(value) <= MAX_ID_LEN else None
    return None


def _telegram_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value < 2**63 else None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 18:
        return int(value) or None
    return None


def _currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else None


def _minor_units(value: Any) -> int | None:
    """Сумма в минорных единицах — как пришла (П5-5). Без float-арифметики: значение идёт
    через Decimal, дробная часть, отрицательное, NaN и абсурдно большое — ошибка payload."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ProviderPayloadError("amount is not a number")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise ProviderPayloadError("amount is not a number") from None
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ProviderPayloadError("amount is not a whole number of minor units")
    if not 0 <= amount <= MAX_AMOUNT:
        raise ProviderPayloadError("amount is out of range")
    return int(amount)


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

    def parse(self, payload: Mapping[str, Any]) -> ProviderEvent:
        raw_name = payload.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ProviderPayloadError("event has no name")
        kind: ProviderEventKind = _KINDS.get(_normalize(raw_name), "ignored")
        if kind == "ignored":
            return ProviderEvent(kind, None, None, None, None, None, None, raw_name)

        body = payload.get("payload")
        if not isinstance(body, Mapping):
            raise ProviderPayloadError("event has no payload object")
        telegram_id = _telegram_id(body.get("telegram_user_id"))
        subscription_id = _text(body.get("subscription_id"))
        period_id = _text(body.get("period_id"))
        purchase_id = _text(body.get("purchase_id"))
        period_end = _text(body.get("expires_at")) or _text(payload.get("sent_at"))
        if purchase_id:
            # Цифровой товар: purchase_id уникален на покупку (так советует Tribute).
            external_payment_id = f"purchase:{purchase_id}"
        elif subscription_id and telegram_id and period_end:
            external_payment_id = f"{subscription_id}:{telegram_id}:{period_end}"
        else:
            external_payment_id = None
        # price — сколько заплатил клиент (выручка); amount — то, что осталось после комиссии
        # Tribute. Платёж фиксирует price, чистая сумма остаётся в raw_payload. У цифровых
        # товаров price нет — тогда берётся amount.
        gross = body.get("price")
        paid = _minor_units(gross if gross is not None else body.get("amount"))
        return ProviderEvent(
            kind=kind,
            telegram_id=telegram_id,
            external_payment_id=external_payment_id,
            external_subscription_id=subscription_id,
            product_ref=period_id,  # период (месяц/год) определяет срок и цену — по нему и тариф
            amount=paid,
            currency=_currency(body.get("currency")),
            raw_name=raw_name,
        )


MAX_LINK_LEN = 2048


def checkout_url(product: object) -> str | None:
    """Ссылка на оплату из `provider_product_ids["tribute"]["link"]`. Только https: значение
    вводит админ, но попадает в кнопку Mini App — `javascript:` и `//host` туда попасть не должны.
    Ключ API не нужен: кнопка «Купить» работает и там, где вебхуки ещё не настроены."""
    if not isinstance(product, Mapping):
        return None
    link = product.get("link")
    if not isinstance(link, str):
        return None
    link = link.strip()
    return link if link.startswith("https://") and len(link) <= MAX_LINK_LEN else None
