"""Выпуск клиентских и серверных сертификатов.

CN клиентского сертификата — это ocserv-username (cert-user-oid = CN),
поэтому он проходит ту же строгую регулярку, что и всё, что попадает
в allowed.list и аргументы occtl.
"""

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from ocmanager.provisioning.pki.ca import CertificateAuthority

USERNAME_RE: Final = re.compile(r"^c[1-9]\d{0,9}-d[1-9]\d{0,4}$")
LEAF_KEY_BITS = 2048
CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedCert:
    key: rsa.RSAPrivateKey
    cert: x509.Certificate

    @property
    def serial(self) -> int:
        return self.cert.serial_number

    @property
    def fingerprint_sha256(self) -> str:
        return self.cert.fingerprint(hashes.SHA256()).hex()

    @property
    def not_after(self) -> datetime:
        return self.cert.not_valid_after_utc.astimezone(UTC)


def _key_usage(*, digital_signature: bool, key_encipherment: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=digital_signature,
        content_commitment=False,
        key_encipherment=key_encipherment,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )


def _leaf_builder(
    ca: CertificateAuthority, cn: str, key: rsa.RSAPrivateKey, now: datetime, days: int
) -> x509.CertificateBuilder:
    ca_ski = ca.cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .issuer_name(ca.cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(digital_signature=True, key_encipherment=True), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )


def issue_client_cert(
    ca: CertificateAuthority, cn: str, now: datetime, *, days: int = 397
) -> IssuedCert:
    if not USERNAME_RE.fullmatch(cn):
        raise ValueError(f"invalid client CN {cn!r}")
    key = rsa.generate_private_key(public_exponent=65537, key_size=LEAF_KEY_BITS)
    cert = (
        _leaf_builder(ca, cn, key, now, days)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca.key, hashes.SHA256())
    )
    return IssuedCert(key=key, cert=cert)


def _san(host: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def issue_server_cert(
    ca: CertificateAuthority, hosts: Sequence[str], now: datetime, *, days: int = 397
) -> IssuedCert:
    """Только для dev: в production серверный сертификат — от публичного CA."""
    if not hosts:
        raise ValueError("at least one host is required")
    key = rsa.generate_private_key(public_exponent=65537, key_size=LEAF_KEY_BITS)
    cert = (
        _leaf_builder(ca, hosts[0], key, now, days)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([_san(h) for h in hosts]), critical=False)
        .sign(ca.key, hashes.SHA256())
    )
    return IssuedCert(key=key, cert=cert)
