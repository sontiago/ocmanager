from collections.abc import Mapping
from typing import Any

from ocmanager.billing.providers.base import PaymentProvider
from ocmanager.billing.providers.tribute import TributeProvider
from ocmanager.billing.providers.tribute import checkout_url as _tribute_checkout_url
from ocmanager.core.config import Settings

PROVIDER_NAMES = ("tribute",)


def get_provider(name: str, settings: Settings) -> PaymentProvider | None:
    """Провайдер, способный проверять вебхуки. Нет ключа API — нет и провайдера (П5-11)."""
    if name == "tribute":
        key = settings.tribute_api_key
        if key is not None and key.get_secret_value():
            return TributeProvider(key.get_secret_value())
    return None


def build_providers(settings: Settings) -> dict[str, PaymentProvider]:
    return {
        name: provider
        for name in PROVIDER_NAMES
        if (provider := get_provider(name, settings)) is not None
    }


def checkout_url(provider: str, product: Mapping[str, Any] | None) -> str | None:
    """Ссылка на оплату продукта у провайдера; None — продукта нет или ссылка небезопасна (П5-2)."""
    if provider == "tribute":
        return _tribute_checkout_url(product)
    return None
