"""Упаковка ключа и сертификата клиента в PKCS#12 (.p12).

Шифрование legacy (PBES1 SHA1 + 3DES, MAC SHA1) — решение №8: iOS и часть
клиентов AnyConnect не импортируют PKCS#12 с AES/PBES2. Эталон r4ven-me
делает то же для iOS: `certtool --to-p12 --pkcs-cipher 3des-pkcs12 --hash SHA1`.
"""

import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import PrivateFormat, pkcs12

from ocmanager.provisioning.pki.certs import IssuedCert

# Без 0/O, 1/l/I: пароль вводят руками с экрана телефона.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def pack_p12(
    issued: IssuedCert, ca_cert: x509.Certificate, password: str, *, friendly_name: str
) -> bytes:
    encryption = (
        PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(50_000)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())  # noqa: S303 — требование совместимости iOS
        .build(password.encode())
    )
    return pkcs12.serialize_key_and_certificates(
        friendly_name.encode(), issued.key, issued.cert, [ca_cert], encryption
    )
