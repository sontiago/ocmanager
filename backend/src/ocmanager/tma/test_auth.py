from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

import pytest

from ocmanager.core.errors import InitDataExpired, Unauthorized
from ocmanager.tma.auth import DEV_HASH, validate_init_data
from ocmanager.tma.testing import make_init_data

TOKEN = "123456:test-bot-token-not-real"
NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
USER = {"id": 99281932, "first_name": "Иван", "username": "ivan", "language_code": "ru"}
TTL = 3600


def signed(**over: Any) -> str:
    args: dict[str, Any] = {"user": USER, "auth_date": int(NOW.timestamp())} | over
    return make_init_data(TOKEN, **args)


def check(raw: str, **over: Any) -> Any:
    kwargs: dict[str, Any] = {"ttl_s": TTL, "now": NOW} | over
    return validate_init_data(raw, TOKEN, **kwargs)


def test_a_signed_string_gives_the_identity() -> None:
    data = check(signed())
    assert (data.user.telegram_id, data.user.first_name) == (99281932, "Иван")
    assert (data.user.username, data.user.language_code) == ("ivan", "ru")
    assert data.auth_date == NOW


def test_changing_any_field_breaks_the_signature() -> None:
    fields = dict(parse_qsl(signed()))
    for key in ("user", "auth_date"):
        forged = {**fields, key: fields[key] + " "}
        with pytest.raises(Unauthorized, match="bad hash"):
            check(urlencode(forged))


def test_another_bot_token_does_not_validate() -> None:
    with pytest.raises(Unauthorized, match="bad hash"):
        validate_init_data(signed(), "999999:other-token-value", ttl_s=TTL, now=NOW)


def test_the_signature_field_is_part_of_the_signed_text() -> None:
    raw = signed(extra={"signature": "abc", "chat_type": "private"})
    assert check(raw).user.telegram_id == 99281932
    tampered = raw.replace("signature=abc", "signature=abd")
    with pytest.raises(Unauthorized, match="bad hash"):
        check(tampered)


@pytest.mark.parametrize("raw", ["", "garbage", "a=1&a=2&hash=00", "user=%7B%7D", "x" * 5000])
def test_malformed_strings_are_unauthorized(raw: str) -> None:
    with pytest.raises(Unauthorized):
        check(raw)


def test_a_repeated_field_is_refused_even_when_the_signature_is_still_valid() -> None:
    raw = signed(extra={"chat_type": "private"})
    check(raw)
    with pytest.raises(Unauthorized, match="malformed"):
        check(raw + "&chat_type=private")  # значение то же, подпись по-прежнему сходится


def test_a_non_ascii_hash_is_a_clean_401_not_a_crash() -> None:
    fields = dict(parse_qsl(signed()))
    with pytest.raises(Unauthorized, match="bad hash"):
        check(urlencode({**fields, "hash": "хэш"}))


def test_expiry_is_a_separate_error_with_its_own_code() -> None:
    old = signed(auth_date=int((NOW - timedelta(seconds=TTL + 1)).timestamp()))
    with pytest.raises(InitDataExpired) as caught:
        check(old)
    assert caught.value.code == "initdata_expired"
    check(signed(auth_date=int((NOW - timedelta(seconds=TTL)).timestamp())))  # ровно на границе


def test_a_date_far_in_the_future_is_refused() -> None:
    with pytest.raises(Unauthorized, match="future"):
        check(signed(auth_date=int((NOW + timedelta(hours=1)).timestamp())))
    check(
        signed(auth_date=int((NOW + timedelta(minutes=1)).timestamp()))
    )  # небольшой разнобой часов


@pytest.mark.parametrize(
    "user",
    [
        {"first_name": "x"},
        {"id": "1", "first_name": "x"},
        {"id": True, "first_name": "x"},
        {"id": -5, "first_name": "x"},
        {"id": 2**60, "first_name": "x"},
        {"id": 5},
        [],
    ],
)
def test_a_user_without_a_sane_id_and_name_is_refused(user: Any) -> None:
    with pytest.raises(Unauthorized, match="malformed"):
        check(signed(user=user))


def test_optional_fields_are_optional_and_junk_types_are_ignored() -> None:
    data = check(signed(user={"id": 7, "first_name": " ", "username": 5, "language_code": None}))
    assert (data.user.first_name, data.user.username, data.user.language_code) == ("7", None, None)


def test_the_mock_signature_passes_only_when_dev_is_allowed() -> None:
    fields = {
        "user": '{"id":1,"first_name":"Ivan"}',
        "auth_date": str(int(NOW.timestamp())),
        "signature": "dev-mock-signature",
        "hash": DEV_HASH,
    }
    raw = urlencode(fields)
    with pytest.raises(Unauthorized, match="bad hash"):
        check(raw)
    assert check(raw, allow_dev=True).user.telegram_id == 1


def test_dev_mode_does_not_switch_off_the_check_for_real_hashes() -> None:
    fields = dict(parse_qsl(signed()))
    with pytest.raises(Unauthorized, match="bad hash"):
        check(urlencode({**fields, "hash": "0" * 64}), allow_dev=True)


def test_a_dev_hash_still_has_to_be_fresh() -> None:
    fields = {
        "user": '{"id":1,"first_name":"Ivan"}',
        "auth_date": str(int((NOW - timedelta(days=30)).timestamp())),
        "hash": DEV_HASH,
    }
    with pytest.raises(InitDataExpired):
        check(urlencode(fields), allow_dev=True)
