"""Стенд для интеграционных тестов с живым ocserv.

    make ocserv-up          # из backend/, после ocmanager pki init / dev-server-cert
    make test-ocserv

Тесты меняют allowed.list и crl.pem в .dev/ocserv-state и возвращают их
после каждого теста. Клиенты — контейнеры vpn-client из dev-compose.
"""

import asyncio
import os
import socket
import sys
from collections.abc import AsyncIterator, Callable
from subprocess import DEVNULL

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core import shell
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.provisioning.pki.ca import CertificateAuthority, load_ca
from ocmanager.provisioning.pki.certs import issue_client_cert
from ocmanager.provisioning.pki.p12 import generate_password, pack_p12
from tests.integration.env import Env
from tests.integration.stand import CERTS_DIR, ClientCert, VpnClient, eventually


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


# --- полный стенд (Задача 2.10) ---------------------------------------------

PUBLIC_API_PORT = 8000  # его ждёт хук: OCM_SESSION_END_URL в deploy/docker-compose.dev.yml


@pytest.fixture(scope="session")
async def public_api(settings: Settings, db_engine: object, stand: None) -> AsyncIterator[None]:
    """Публичный API на 0.0.0.0:8000 с тестовой БД — принимает отчёты disconnect.sh из
    контейнера ноды (host.docker.internal). Токен берётся из самой ноды: что бы ни было
    в её окружении, API проверит именно его."""
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PUBLIC_API_PORT)) == 0:
            pytest.skip(f"порт {PUBLIC_API_PORT} занят — остановите dev-сервер")
    token = (
        await shell.run(
            [
                "docker",
                "exec",
                settings.ocserv_container,
                "cat",
                "/etc/ocmanager/runtime/internal_token",
            ]
        )
    ).stdout
    env = {
        **os.environ,
        "OCM_DATABASE_URL": settings.database_url,
        "OCM_REDIS_URL": settings.redis_url,
        "OCM_INTERNAL_TOKEN": token,
    }
    argv = [sys.executable, "-m", "uvicorn", "ocmanager.apps.public_api:create_app", "--factory"]
    argv += ["--host", "0.0.0.0", "--port", str(PUBLIC_API_PORT)]  # noqa: S104 — ждёт контейнер
    proc = await asyncio.create_subprocess_exec(*argv, env=env, stdout=DEVNULL, stderr=DEVNULL)
    try:

        async def ready() -> bool:
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"http://127.0.0.1:{PUBLIC_API_PORT}/api/health")
            except httpx.TransportError:
                return False
            return r.status_code == 200

        await eventually(ready, within=30)
        yield
    finally:
        proc.terminate()
        await proc.wait()


@pytest.fixture
async def env(
    public_api: None,
    driver: LocalDockerDriver,
    vpn_client: VpnClient,
    settings: Settings,
    committed_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> Env:
    """CLI и воркероподобные вызовы смотрят в тестовую БД; нода — настоящая."""
    monkeypatch.setenv("OCM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("OCM_LOG_LEVEL", "WARNING")
    return Env(settings, driver, vpn_client, committed_sessionmaker)
