"""Корневой удостоверяющий центр: создание, хранение, загрузка.

Приватный ключ CA — самый ценный секрет системы: с ним можно выпустить
доступ кому угодно. Поэтому файл создаётся сразу с правами 0600, никогда не
перезаписывается и не загружается, если права шире.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CA_KEY_FILE = "ca.key"
CA_CERT_FILE = "ca.crt"
CA_KEY_BITS = 3072


@dataclass(frozen=True)
class CertificateAuthority:
    key: rsa.RSAPrivateKey
    cert: x509.Certificate


class InsecureKeyFile(Exception):
    pass


def create_ca(common_name: str, now: datetime, *, days: int = 3650) -> CertificateAuthority:
    key = rsa.generate_private_key(public_exponent=65537, key_size=CA_KEY_BITS)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ski, critical=False)
        .sign(key, hashes.SHA256())
    )
    return CertificateAuthority(key=key, cert=cert)


def _write_new(path: Path, data: bytes, mode: int) -> None:
    """O_EXCL: файл создаётся сразу с нужными правами и никогда не перезаписывается."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, mode)  # umask мог срезать биты при создании


def save_ca(ca: CertificateAuthority, directory: Path) -> None:
    key_path, cert_path = directory / CA_KEY_FILE, directory / CA_CERT_FILE
    for path in (key_path, cert_path):
        if path.exists():
            raise FileExistsError(path)
    directory.mkdir(parents=True, exist_ok=True)
    key_pem = ca.key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    _write_new(key_path, key_pem, 0o600)
    _write_new(cert_path, ca.cert.public_bytes(serialization.Encoding.PEM), 0o644)


def load_ca(directory: Path) -> CertificateAuthority:
    key_path = directory / CA_KEY_FILE
    if key_path.stat().st_mode & 0o077:
        raise InsecureKeyFile(f"{key_path}: права шире 0600, выполните chmod 600")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError(f"{key_path}: ожидается RSA-ключ")
    cert = x509.load_pem_x509_certificate((directory / CA_CERT_FILE).read_bytes())
    return CertificateAuthority(key=key, cert=cert)
