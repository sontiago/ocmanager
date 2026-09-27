"""Список отозванных сертификатов (CRL).

ocserv (GnuTLS) отвергает все клиентские сертификаты, если CRL просрочен,
поэтому next_update — неделя, а перевыпуск — ежедневно (решение №10).
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from ocmanager.provisioning.pki.ca import CertificateAuthority


def build_crl(
    ca: CertificateAuthority,
    revoked: Iterable[tuple[int, datetime]],
    now: datetime,
    *,
    next_update_days: int = 7,
) -> bytes:
    """revoked — пары (серийный номер, момент отзыва). Возвращает PEM."""
    ca_ski = ca.cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca.cert.subject)
        .last_update(now)
        .next_update(now + timedelta(days=next_update_days))
        # Номер CRL обязан расти; секунды Unix растут сами.
        .add_extension(x509.CRLNumber(int(now.timestamp())), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski),
            critical=False,
        )
    )
    for serial, revoked_at in revoked:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(revoked_at)
            .build()
        )
    crl = builder.sign(ca.key, hashes.SHA256())
    return crl.public_bytes(serialization.Encoding.PEM)
