import json

import pytest

from ocmanager.billing.testing import fixture_bytes, webhook_body
from scripts.tribute_tool import inspect_body, load_body


def test_a_good_fixture_resolves_every_field() -> None:
    report = "\n".join(inspect_body(fixture_bytes("new_subscription")))
    assert "subscription_started" in report
    assert "НЕ НАЙДЕНО" not in report
    assert "telegram_id = 7001" in report
    assert "amount = 19900" in report


def test_a_missing_field_is_flagged() -> None:
    report = "\n".join(inspect_body(webhook_body("new_subscription", telegram_user_id=None)))
    assert "telegram_id = None  ! НЕ НАЙДЕНО" in report


def test_an_unknown_event_is_flagged() -> None:
    assert "_KINDS" in "\n".join(inspect_body(fixture_bytes("new_donation")))


def test_a_spare_identifier_field_is_pointed_out() -> None:
    body = json.dumps(
        {
            "name": "new_subscription",
            "event_id": "e1",
            "payload": {"subscription_id": 1, "user_id": 2},
        }
    ).encode()
    report = "\n".join(inspect_body(body))
    assert "event_id" in report
    assert "user_id" in report


@pytest.mark.parametrize("body", [b"nope", b"[1]", b'{"name": 5}'])
def test_garbage_gives_a_report_not_a_crash(body: bytes) -> None:
    assert inspect_body(body)


def test_a_fixture_is_loaded_by_name_and_a_missing_one_is_refused() -> None:
    assert load_body("new_subscription") == fixture_bytes("new_subscription")
    with pytest.raises(SystemExit):
        load_body("no-such-thing")
