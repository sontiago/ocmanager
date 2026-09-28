"""Помощники интеграционных тестов: VPN-клиенты в контейнерах vpn-client."""

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from ocmanager.core import shell
from ocmanager.nodes.driver.local_docker import LocalDockerDriver

REPO = Path(__file__).parents[3]
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "docker-compose.dev.yml")]
CERTS_DIR = REPO / ".dev" / "client-certs"
SERVER_URL = "https://ocserv/?devsecret"


class ConnectFailed(Exception):
    pass


async def eventually(check: Callable[[], Awaitable[bool]], *, within: float = 15) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.5)


async def online(driver: LocalDockerDriver) -> set[str]:
    return {s.username for s in await driver.list_sessions()}


@dataclass(frozen=True)
class ClientCert:
    cn: str
    password: str
    serial: int

    def openconnect(self, *extra: str) -> list[str]:
        return [
            "openconnect",
            *extra,
            "--certificate",
            f"/certs/{self.cn}.p12",
            "--key-password",
            self.password,
            "--cafile",
            "/ca.crt",
            SERVER_URL,
        ]


@dataclass
class VpnClient:
    driver: LocalDockerDriver
    containers: dict[str, str] = field(default_factory=dict)  # username → контейнер

    async def connect(self, cert: ClientCert, *, within: float = 15) -> None:
        """Полное подключение: туннель + connect-script. Ждёт сессию в occtl."""
        name = f"ocm-vpn-{cert.cn}-{secrets.token_hex(3)}"
        run = [*COMPOSE, "run", "-d", "--name", name, "vpn-client", *cert.openconnect()]
        await shell.run(run, timeout=300)
        self.containers[cert.cn] = name

        async def up() -> bool:
            state = await shell.run(["docker", "inspect", "-f", "{{.State.Running}}", name])
            if state.stdout.strip() != "true":
                raise ConnectFailed(f"{cert.cn}: openconnect exited")
            return cert.cn in await online(self.driver)

        try:
            await eventually(up, within=within)
        except TimeoutError:
            raise ConnectFailed(f"{cert.cn}: no session after {within}s") from None

    async def authenticate_only(self, cert: ClientCert) -> bool:
        """TLS + проверка сертификата (CRL), без туннеля: connect-script не вызывается,
        поэтому allowlist так не проверить."""
        run = [
            *COMPOSE,
            "run",
            "--rm",
            "-T",
            "vpn-client",
            *cert.openconnect("--authenticate"),
        ]
        result = await shell.run(run, timeout=120, check=False)
        return result.returncode == 0

    async def ping(self, username: str, host: str, *, count: int = 1, size: int = 56) -> None:
        """Трафик через туннель: ping из контейнера клиента."""
        argv = ["docker", "exec", self.containers[username], "ping", "-c", str(count)]
        await shell.run([*argv, "-s", str(size), "-W", "2", host], timeout=30)

    async def stop(self) -> None:
        if self.containers:
            argv = ["docker", "rm", "-f", *self.containers.values()]
            await shell.run(argv, timeout=60, check=False)
        # Убитый клиент не прощается: без disconnect сессия висела бы до DPD.
        for username in self.containers:
            await self.driver.disconnect_user(username)
        self.containers.clear()
