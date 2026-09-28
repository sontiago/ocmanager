"""Контракт NodeDriver: одни и те же проверки для любого драйвера.

    class TestMyDriver(DriverContract):
        @pytest.fixture
        def driver(self) -> NodeDriver: ...

Фейк проверяется в driver/test_fake.py, LocalDockerDriver — на живом
ocserv в tests/integration/test_node_driver.py.
"""

from datetime import timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ocmanager.core.clock import utcnow
from ocmanager.nodes.driver.base import NodeDriver


def make_crl_pem() -> bytes:
    """Любой валидный CRL. nodes не импортирует provisioning, поэтому свой."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = utcnow()
    crl = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "contract")]))
        .last_update(now)
        .next_update(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return crl.public_bytes(serialization.Encoding.PEM)


class DriverContract:
    async def test_allowlist_roundtrip(self, driver: NodeDriver) -> None:
        await driver.publish_allowlist(["c2-d1", "c1-d1", "c1-d1"])
        assert await driver.read_allowlist() == {"c1-d1", "c2-d1"}

    async def test_allowlist_empty(self, driver: NodeDriver) -> None:
        await driver.publish_allowlist([])
        assert await driver.read_allowlist() == set()

    async def test_invalid_username_rejected_and_file_unchanged(self, driver: NodeDriver) -> None:
        await driver.publish_allowlist(["c1-d1"])
        with pytest.raises(ValueError, match="invalid ocserv username"):
            await driver.publish_allowlist(["c1-d1", "../etc/passwd"])
        assert await driver.read_allowlist() == {"c1-d1"}

    async def test_crl_roundtrip(self, driver: NodeDriver) -> None:
        pem = make_crl_pem()
        await driver.publish_crl(pem)
        assert await driver.read_crl() == pem

    async def test_crl_must_be_pem(self, driver: NodeDriver) -> None:
        with pytest.raises(ValueError, match="not a PEM-encoded CRL"):
            await driver.publish_crl(b"garbage")

    async def test_disconnect_unknown_user_is_noop(self, driver: NodeDriver) -> None:
        await driver.disconnect_user("c999999-d1")

    @pytest.mark.parametrize("username", ["-rf", "c1-d1 ; reboot", "all"])
    async def test_disconnect_rejects_invalid_username(
        self, driver: NodeDriver, username: str
    ) -> None:
        with pytest.raises(ValueError, match="invalid ocserv username"):
            await driver.disconnect_user(username)

    async def test_probe_running(self, driver: NodeDriver) -> None:
        probe = await driver.probe()
        assert probe.container_state == "running"
        assert probe.ocserv is not None
        assert probe.ocserv.up is True

    async def test_list_sessions_returns_list(self, driver: NodeDriver) -> None:
        assert isinstance(await driver.list_sessions(), list)

    async def test_reload(self, driver: NodeDriver) -> None:
        await driver.reload()

    async def test_stream_logs_yields_lines(self, driver: NodeDriver) -> None:
        async with driver.stream_logs(tail=5) as lines:
            first = await anext(lines)
        assert isinstance(first, str)
