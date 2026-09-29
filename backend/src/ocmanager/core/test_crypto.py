import pytest
from cryptography.fernet import InvalidToken

from ocmanager.core.crypto import derive_fernet

SECRET = "s" * 32


def test_roundtrip() -> None:
    f = derive_fernet(SECRET, purpose=b"p12")
    assert f.decrypt(f.encrypt(b"data")) == b"data"


def test_deterministic_per_secret_and_purpose() -> None:
    token = derive_fernet(SECRET, purpose=b"p12").encrypt(b"data")
    assert derive_fernet(SECRET, purpose=b"p12").decrypt(token) == b"data"


def test_purpose_separates_keys() -> None:
    token = derive_fernet(SECRET, purpose=b"p12").encrypt(b"data")
    with pytest.raises(InvalidToken):
        derive_fernet(SECRET, purpose=b"other").decrypt(token)


def test_secret_separates_keys() -> None:
    token = derive_fernet(SECRET, purpose=b"p12").encrypt(b"data")
    with pytest.raises(InvalidToken):
        derive_fernet("t" * 32, purpose=b"p12").decrypt(token)
