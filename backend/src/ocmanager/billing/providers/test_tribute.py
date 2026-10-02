import json
from typing import Any

import pytest

from ocmanager.billing.providers import checkout_url
from ocmanager.billing.providers.base import ProviderEvent, ProviderPayloadError
from ocmanager.billing.providers.tribute import SIGNATURE_HEADER, TributeProvider
from ocmanager.billing.testing import sign, webhook_body

provider = TributeProvider("test-key")

PAID_ID = "1001:7001:2026-10-30T10:00:00.000Z"


def parse(name: str, **overrides: Any) -> ProviderEvent:
    return provider.parse(json.loads(webhook_body(name, **overrides)))


def event(name: str, **payload: Any) -> dict[str, Any]:
    return {"name": name, "payload": payload}


# --- подпись и идентификатор ------------------------------------------------------------


def test_the_signature_is_hmac_sha256_of_the_exact_body() -> None:
    body = b'{"a": 1}'
    assert provider.verify(body, {SIGNATURE_HEADER: sign(body, "test-key")})
    assert not provider.verify(body + b" ", {SIGNATURE_HEADER: sign(body, "test-key")})
    assert not provider.verify(body, {SIGNATURE_HEADER: sign(body, "other-key")})
    assert not provider.verify(body, {})
    assert not provider.verify(body, {SIGNATURE_HEADER: ""})


def test_the_hex_case_of_the_signature_does_not_matter() -> None:
    body = b"{}"
    assert provider.verify(body, {SIGNATURE_HEADER: sign(body, "test-key").upper()})


def test_the_event_id_is_a_hash_of_the_body() -> None:
    a, b = webhook_body("new_subscription"), webhook_body("new_subscription", note="x")
    assert provider.event_id(a, {}) == provider.event_id(a, {})
    assert provider.event_id(a, {}) != provider.event_id(b, {})
    assert len(provider.event_id(a, {})) == 64


# --- маппинг событий: по фикстуре на каждое --------------------------------------------


def test_new_subscription() -> None:
    assert parse("new_subscription") == ProviderEvent(
        kind="subscription_started",
        telegram_id=7001,
        external_payment_id=PAID_ID,
        external_subscription_id="1001",
        product_ref="2001",
        amount=19900,
        currency="RUB",
        raw_name="new_subscription",
    )


def test_renewed_subscription_is_a_new_payment_of_the_same_subscription() -> None:
    renewed = parse("renewed_subscription")
    assert renewed.kind == "subscription_renewed"
    assert renewed.external_payment_id == "1001:7001:2026-11-29T10:00:00.000Z"
    assert renewed.external_payment_id != PAID_ID  # другой период — другой платёж
    assert renewed.product_ref == "2001"


def test_cancelled_subscription() -> None:
    cancelled = parse("cancelled_subscription")
    assert (cancelled.kind, cancelled.telegram_id) == ("subscription_cancelled", 7001)


def test_a_refund_points_at_the_purchase_it_refunds() -> None:
    refund = parse("digital_product_refund")  # в вебхуке он называется digital_product_refunded
    assert (refund.kind, refund.raw_name) == ("refund", "digital_product_refunded")
    assert refund.external_payment_id == "purchase:78901"
    assert (refund.amount, refund.currency) == (500, "USD")  # у цифровых товаров price нет


def test_both_refund_names_are_understood() -> None:
    for name in ("digital_product_refunded", "digitalProductRefund"):
        body = event(name, purchase_id=1, telegram_user_id=5, amount=100, currency="usd")
        assert provider.parse(body).kind == "refund"


def test_a_digital_product_purchase_is_not_handled_yet_and_is_ignored() -> None:
    assert parse("new_digital_product").kind == "ignored"


def test_the_revenue_is_what_the_client_paid_not_what_is_left_after_the_commission() -> None:
    body = json.loads(webhook_body("new_subscription"))["payload"]
    assert (body["price"], body["amount"]) == (19900, 15920)  # гросс и нетто в фикстуре
    assert parse("new_subscription").amount == 19900
    assert parse("new_subscription", price=None).amount == 15920  # нет price — берётся amount


def test_the_plan_is_matched_by_the_period_not_by_the_subscription() -> None:
    monthly = parse("new_subscription", period_id=2001)
    yearly = parse("new_subscription", period_id=2002)
    assert (monthly.product_ref, yearly.product_ref) == ("2001", "2002")
    assert monthly.external_subscription_id == yearly.external_subscription_id == "1001"
    assert parse("new_subscription", period_id=None).product_ref is None


def test_an_event_we_do_not_need_is_ignored_not_an_error() -> None:
    assert parse("new_donation") == ProviderEvent(
        kind="ignored",
        telegram_id=None,
        external_payment_id=None,
        external_subscription_id=None,
        product_ref=None,
        amount=None,
        currency=None,
        raw_name="new_donation",
    )


@pytest.mark.parametrize("name", ["newSubscription", "new_subscription", "NEW-SUBSCRIPTION"])
def test_event_names_are_matched_regardless_of_style(name: str) -> None:
    body = event(
        name, subscription_id=1, telegram_user_id=5, expires_at="x", amount=100, currency="rub"
    )
    assert provider.parse(body).kind == "subscription_started"
    assert provider.parse(body).raw_name == name


# --- поля -------------------------------------------------------------------------------


def test_the_payment_id_falls_back_to_sent_at_when_there_is_no_period_end() -> None:
    body = event("new_subscription", subscription_id=1, telegram_user_id=5)
    body["sent_at"] = "2026-10-01T00:00:00.000Z"
    assert provider.parse(body).external_payment_id == "1:5:2026-10-01T00:00:00.000Z"


def test_a_payment_without_its_parts_has_no_id_and_processing_will_say_why() -> None:
    assert provider.parse(event("new_subscription", telegram_user_id=5)).external_payment_id is None
    assert provider.parse(event("new_subscription", subscription_id=1)).external_payment_id is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (7001, 7001),
        ("7001", 7001),
        (None, None),
        (0, None),
        (-5, None),
        (True, None),
        ("abc", None),
        ("７００１", None),
        (2**63, None),
        ("9" * 5000, None),
        (70.5, None),
    ],
)
def test_the_telegram_id_is_a_positive_integer_or_nothing(raw: Any, expected: int | None) -> None:
    body = event("new_subscription", telegram_user_id=raw)
    assert provider.parse(body).telegram_id == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(19900, 19900), ("19900", 19900), (19900.0, 19900), ("19900.00", 19900), (0, 0), (None, None)],
)
def test_the_amount_is_whole_minor_units_without_float_arithmetic(
    raw: Any, expected: int | None
) -> None:
    assert provider.parse(event("new_subscription", amount=raw)).amount == expected


@pytest.mark.parametrize(
    "raw", [199.99, "199.5", "abc", -1, "NaN", "Infinity", True, [1], {"a": 1}, 10**13]
)
def test_an_amount_we_cannot_trust_is_an_error_not_a_guess(raw: Any) -> None:
    with pytest.raises(ProviderPayloadError):
        provider.parse(event("new_subscription", amount=raw))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rub", "RUB"),
        (" Usd ", "USD"),
        ("RUBLES", None),
        ("р", None),
        (None, None),
        (5, None),
        ("", None),
    ],
)
def test_the_currency_is_a_three_letter_code_or_nothing(raw: Any, expected: str | None) -> None:
    assert provider.parse(event("new_subscription", currency=raw)).currency == expected


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": 5},
        {"payload": {}},
        {"name": "new_subscription"},
        {"name": "new_subscription", "payload": [1]},
    ],
    ids=["empty", "blank-name", "name-not-str", "no-name", "no-payload", "payload-not-object"],
)
def test_a_body_of_the_wrong_shape_is_a_payload_error(body: dict[str, Any]) -> None:
    with pytest.raises(ProviderPayloadError):
        provider.parse(body)


def test_the_checkout_link_comes_from_the_plan_product() -> None:
    link = "https://t.me/tribute/app?startapp=s1"
    assert checkout_url("tribute", {"product_ref": "1", "link": link}) == link
    assert checkout_url("tribute", {"link": f"  {link}  "}) == link


@pytest.mark.parametrize(
    "product",
    [
        None,
        {},
        {"link": ""},
        {"link": "http://t.me/x"},
        {"link": "javascript:alert(1)"},
        {"link": 5},
        {"link": "https://" + "a" * 3000},
    ],
    ids=["none", "empty", "blank", "plain-http", "javascript", "not-str", "too-long"],
)
def test_a_product_without_a_safe_link_has_no_checkout(product: Any) -> None:
    assert checkout_url("tribute", product) is None


def test_an_unknown_provider_has_no_checkout() -> None:
    assert checkout_url("stars", {"link": "https://t.me/x"}) is None


def test_the_dashboard_test_ping_is_ignored_not_an_error() -> None:
    event = provider.parse({"test_event": "test_event"})
    assert (event.kind, event.raw_name) == ("ignored", "test_event")
