"""LocalDockerDriver на живом ocserv: контракт + то, ради чего всё затевалось —
сертификат нашего PKI пускает, allowlist и CRL не пускают."""

from collections.abc import Callable

import pytest

from ocmanager.core.clock import utcnow
from ocmanager.nodes.driver.base import NodeDriver
from ocmanager.nodes.driver.contract import DriverContract
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.provisioning.pki.ca import CertificateAuthority
from ocmanager.provisioning.pki.crl import build_crl
from tests.integration.stand import (
    ClientCert,
    ConnectFailed,
    VpnClient,
    eventually,
    online,
)

pytestmark = pytest.mark.ocserv

IssueCert = Callable[[str], ClientCert]


class TestLocalDockerDriver(DriverContract):
    """Фикстура driver — из conftest.py: живая нода."""


async def test_allowed_cert_connects(
    driver: LocalDockerDriver, vpn_client: VpnClient, issue_cert: IssueCert
) -> None:
    cert = issue_cert("c9001-d11")
    await driver.publish_allowlist([cert.cn])
    await vpn_client.connect(cert)
    [session] = [s for s in await driver.list_sessions() if s.username == cert.cn]
    assert session.vpn_ip is not None
    assert session.vpn_ip.startswith("10.77.0.")


async def test_not_in_allowlist_is_refused(
    driver: LocalDockerDriver, vpn_client: VpnClient, issue_cert: IssueCert
) -> None:
    cert = issue_cert("c9001-d12")
    await driver.publish_allowlist(["c9001-d1"])
    with pytest.raises(ConnectFailed):
        await vpn_client.connect(cert)


async def test_disconnect_user_drops_session(
    driver: LocalDockerDriver, vpn_client: VpnClient, issue_cert: IssueCert
) -> None:
    cert = issue_cert("c9001-d13")
    await driver.publish_allowlist([cert.cn])
    await vpn_client.connect(cert)
    await driver.disconnect_user(cert.cn)

    async def gone() -> bool:
        return cert.cn not in await online(driver)

    await eventually(gone, within=5)


async def test_revoked_cert_rejected_without_reload(
    driver: NodeDriver,
    vpn_client: VpnClient,
    issue_cert: IssueCert,
    dev_ca: CertificateAuthority,
) -> None:
    """ocserv 1.3 перечитывает CRL при изменении файла; reload не нужен."""
    cert = issue_cert("c9001-d14")
    await driver.publish_allowlist([cert.cn])
    assert await vpn_client.authenticate_only(cert) is True
    now = utcnow()
    await driver.publish_crl(build_crl(dev_ca, [(cert.serial, now)], now))
    assert await vpn_client.authenticate_only(cert) is False


async def test_revoked_cert_stays_rejected_after_reload(
    driver: NodeDriver,
    vpn_client: VpnClient,
    issue_cert: IssueCert,
    dev_ca: CertificateAuthority,
) -> None:
    cert = issue_cert("c9001-d15")
    now = utcnow()
    await driver.publish_crl(build_crl(dev_ca, [(cert.serial, now)], now))
    await driver.reload()
    assert await vpn_client.authenticate_only(cert) is False


async def test_traffic_counters_grow(
    driver: LocalDockerDriver, vpn_client: VpnClient, issue_cert: IssueCert
) -> None:
    cert = issue_cert("c9001-d16")
    await driver.publish_allowlist([cert.cn])
    await vpn_client.connect(cert)
    await vpn_client.ping(cert.cn, "10.77.0.1", count=3, size=1000)
    [session] = [s for s in await driver.list_sessions() if s.username == cert.cn]
    assert session.bytes_in >= 3000
