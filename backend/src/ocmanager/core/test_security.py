from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from ocmanager.core import security

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def test_default_cost_is_12() -> None:
    assert security.BCRYPT_ROUNDS == 12
    assert security.hash_password("correct horse").startswith("$2b$12$")


def test_password_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    hashed = security.hash_password("correct horse battery")
    assert security.verify_password("correct horse battery", hashed)
    assert not security.verify_password("correct horse batterz", hashed)


def test_same_password_gives_different_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    assert security.hash_password("same") != security.hash_password("same")


def test_verify_never_raises_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    hashed = security.hash_password("pw")
    assert not security.verify_password("x" * 100, hashed)  # длиннее 72 байт
    assert not security.verify_password("pw", "not-a-bcrypt-hash")


def test_dummy_verify_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    security._dummy_hash.cache_clear()
    security.dummy_verify()


def test_tokens_are_random_and_hash_is_stable() -> None:
    assert security.new_token() != security.new_token()
    assert len(security.new_token()) >= 43
    assert security.sha256_hex("a") == security.sha256_hex("a") != security.sha256_hex("b")
    assert len(security.sha256_hex("a")) == 64


@pytest.mark.parametrize(
    ("shift", "ok"),
    [(0, True), (-30, True), (30, True), (90, False), (-90, False)],
)
def test_totp_window_is_one_step(shift: int, ok: bool) -> None:
    secret = security.new_totp_secret()
    code = pyotp.TOTP(secret).at(NOW + timedelta(seconds=shift))
    assert security.verify_totp(secret, code, now=NOW) is ok


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "12345a", "١٢٣٤٥٦", " 123456"])
def test_totp_rejects_malformed_codes(bad: str) -> None:
    assert not security.verify_totp(security.new_totp_secret(), bad, now=NOW)


def test_totp_uri_names_the_account() -> None:
    uri = security.totp_uri(security.new_totp_secret(), "alice")
    assert uri.startswith("otpauth://totp/")
    assert "alice" in uri
    assert "issuer=ocmanager" in uri
