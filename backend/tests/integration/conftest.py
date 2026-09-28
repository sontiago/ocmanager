"""Стенд для интеграционных тестов с живым ocserv.

    make ocserv-up          # из backend/, после ocmanager pki init / dev-server-cert
    make test-ocserv

Тесты меняют allowed.list и crl.pem в .dev/ocserv-state и возвращают их
после каждого теста. Клиенты — контейнеры vpn-client из dev-compose.
"""

from collections.abc import AsyncIterator, Callable

import pytest

from ocmanager.core import shell
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca
from ocmanager.provisioning.pki.certs import issue_client_cert
from ocmanager.provisioning.pki.p12 import generate_password, pack_p12
from tests.integration.stand import CERTS_DIR, ClientCert, VpnClient


@pytest.fixture(scope="session")
async def stand(settings: Settings) -> None:
    result = await shell.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", settings.ocserv_container],
        check=False,
    )
    if result.stdout.strip() != "running":
        pytest.skip("ocserv не запущен: cd backend && make ocserv-up")


@pytest.fixture
async def driver(stand: None, settings: Settings) -> AsyncIterator[LocalDockerDriver]:
    """Драйвер живой ноды; allowed.list и crl.pem восстанавливаются после теста."""
    drv = LocalDockerDriver.from_settings(settings)
    saved = {p: p.read_bytes() for p in settings.ocserv_state_dir.glob("*") if p.is_file()}
    yield drv
    for path in ("allowed.list", "crl.pem"):
        p = settings.ocserv_state_dir / path
        if p in saved:
            p.write_bytes(saved[p])


@pytest.fixture
def dev_ca(settings: Settings) -> CertificateAuthority:
    return load_ca(settings.pki_dir)


@pytest.fixture
def issue_cert(dev_ca: CertificateAuthority) -> Callable[[str], ClientCert]:
    def issue(cn: str) -> ClientCert:
        issued = issue_client_cert(dev_ca, cn, utcnow())
        password = generate_password()
        CERTS_DIR.mkdir(parents=True, exist_ok=True)
        blob = pack_p12(issued, dev_ca.cert, password, friendly_name=cn)
        (CERTS_DIR / f"{cn}.p12").write_bytes(blob)
        return ClientCert(cn, password, issued.serial)

    return issue


@pytest.fixture
async def vpn_client(driver: LocalDockerDriver) -> AsyncIterator[VpnClient]:
    client = VpnClient(driver)
    yield client
    await client.stop()
