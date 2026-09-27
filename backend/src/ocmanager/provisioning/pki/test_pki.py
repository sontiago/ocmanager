from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from ocmanager.provisioning.pki import ca as ca_mod
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.certs import issue_client_cert, issue_server_cert
from ocmanager.provisioning.pki.crl import build_crl
from ocmanager.provisioning.pki.p12 import ALPHABET, generate_password, pack_p12

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)

# DER-кодировка OID: pbeWithSHAAnd3-KeyTripleDES-CBC (1.2.840.113549.1.12.1.3)
# и PBES2 (1.2.840.113549.1.5.13).
OID_PBE_SHA1_3DES = bytes.fromhex("060a2a864886f70d010c0103")
OID_PBES2 = bytes.fromhex("06092a864886f70d01050d")


@pytest.fixture(scope="module")
def ca() -> CertificateAuthority:
    return ca_mod.create_ca("ocmanager test CA", NOW)


def cn_of(cert: x509.Certificate) -> str:
    value = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert isinstance(value, str)
    return value


def test_ca_is_ca(ca: CertificateAuthority) -> None:
    bc = ca.cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert bc.path_length == 0
    assert ca.key.key_size == 3072


def test_client_cert_has_cn_and_client_auth(ca: CertificateAuthority) -> None:
    issued = issue_client_cert(ca, "c42-d3", NOW)
    assert cn_of(issued.cert) == "c42-d3"
    eku = issued.cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.CLIENT_AUTH in eku
    assert issued.not_after == NOW + timedelta(days=397)
    assert issued.cert.not_valid_before_utc == NOW - timedelta(minutes=5)
    assert issued.key.key_size == 2048


def test_client_cert_signed_by_ca(ca: CertificateAuthority) -> None:
    issued = issue_client_cert(ca, "c1-d1", NOW)
    public_key = ca.cert.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    assert issued.cert.signature_hash_algorithm is not None
    public_key.verify(
        issued.cert.signature,
        issued.cert.tbs_certificate_bytes,
        padding.PKCS1v15(),
        issued.cert.signature_hash_algorithm,
    )


@pytest.mark.parametrize(
    "cn", ["", "c0-d1", "c1-d0", "admin", "c1-d1\n", "c1-d1;rm", "C1-D1", "c1-d123456"]
)
def test_bad_cn_rejected(ca: CertificateAuthority, cn: str) -> None:
    with pytest.raises(ValueError, match="invalid client CN"):
        issue_client_cert(ca, cn, NOW)


def test_serials_are_unique(ca: CertificateAuthority) -> None:
    serials = {issue_client_cert(ca, f"c1-d{i}", NOW).serial for i in range(1, 20)}
    assert len(serials) == 19


def test_fingerprint_is_lowercase_hex(ca: CertificateAuthority) -> None:
    fp = issue_client_cert(ca, "c1-d1", NOW).fingerprint_sha256
    assert len(fp) == 64
    assert fp == fp.lower()
    assert ":" not in fp


def test_server_cert_has_sans(ca: CertificateAuthority) -> None:
    issued = issue_server_cert(ca, ["ocserv", "localhost", "127.0.0.1"], NOW)
    san = issued.cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["ocserv", "localhost"]
    assert [str(ip) for ip in san.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]
    eku = issued.cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku


def test_p12_roundtrip_with_password(ca: CertificateAuthority) -> None:
    issued = issue_client_cert(ca, "c7-d1", NOW)
    password = generate_password()
    blob = pack_p12(issued, ca.cert, password, friendly_name="iPhone")
    _key, cert, extra = pkcs12.load_key_and_certificates(blob, password.encode())
    assert cert is not None
    assert cert.serial_number == issued.serial
    assert [c.subject for c in extra] == [ca.cert.subject]


def test_p12_uses_legacy_encryption(ca: CertificateAuthority) -> None:
    blob = pack_p12(issue_client_cert(ca, "c7-d3", NOW), ca.cert, "pw", friendly_name="x")
    assert OID_PBE_SHA1_3DES in blob
    assert OID_PBES2 not in blob


def test_p12_wrong_password_fails(ca: CertificateAuthority) -> None:
    blob = pack_p12(issue_client_cert(ca, "c7-d2", NOW), ca.cert, "right", friendly_name="x")
    with pytest.raises(ValueError, match="password"):
        pkcs12.load_key_and_certificates(blob, b"wrong")


def test_password_alphabet_unambiguous() -> None:
    pw = generate_password()
    assert len(pw) == 12
    assert set(pw) <= set(ALPHABET)
    assert not set(ALPHABET) & set("0O1lI")


def test_crl_lists_revoked_and_expires_in_7_days(ca: CertificateAuthority) -> None:
    pem = build_crl(ca, [(1234, NOW - timedelta(hours=1))], NOW)
    crl = x509.load_pem_x509_crl(pem)
    assert crl.get_revoked_certificate_by_serial_number(1234) is not None
    assert crl.next_update_utc == NOW + timedelta(days=7)
    public_key = ca.cert.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    assert crl.is_signature_valid(public_key)


def test_empty_crl_is_valid(ca: CertificateAuthority) -> None:
    crl = x509.load_pem_x509_crl(build_crl(ca, [], NOW))
    assert len(list(crl)) == 0


def test_crl_number_grows(ca: CertificateAuthority) -> None:
    def number(pem: bytes) -> int:
        crl = x509.load_pem_x509_crl(pem)
        return crl.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number

    assert number(build_crl(ca, [], NOW + timedelta(seconds=1))) > number(build_crl(ca, [], NOW))


def test_save_ca_mode_and_no_overwrite(ca: CertificateAuthority, tmp_path: Path) -> None:
    ca_mod.save_ca(ca, tmp_path)
    assert (tmp_path / "ca.key").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "ca.crt").stat().st_mode & 0o777 == 0o644
    before = (tmp_path / "ca.key").read_bytes()
    with pytest.raises(FileExistsError):
        ca_mod.save_ca(ca_mod.create_ca("other", NOW), tmp_path)
    assert (tmp_path / "ca.key").read_bytes() == before
    assert ca_mod.load_ca(tmp_path).cert == ca.cert


def test_load_ca_refuses_world_readable_key(ca: CertificateAuthority, tmp_path: Path) -> None:
    ca_mod.save_ca(ca, tmp_path)
    (tmp_path / "ca.key").chmod(0o644)
    with pytest.raises(ca_mod.InsecureKeyFile):
        ca_mod.load_ca(tmp_path)
