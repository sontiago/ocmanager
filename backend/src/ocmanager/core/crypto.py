from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def derive_fernet(secret: str, *, purpose: bytes) -> Fernet:
    """Ключ Fernet из SECRET_KEY. `purpose` разделяет назначения: ключ для .p12 в Redis
    не подойдёт ни для чего другого, даже при одном SECRET_KEY."""
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(
        secret.encode()
    )
    return Fernet(urlsafe_b64encode(key))


def p12_fernet(secret_key: str) -> Fernet:
    """Ключ для .p12 в Redis. Один и тот же в api-admin и api-public: выпустить и скачать
    можно в разных процессах."""
    return derive_fernet(secret_key, purpose=b"ocmanager.p12-delivery")
