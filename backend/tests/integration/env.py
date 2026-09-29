"""Полный стенд для главных интеграционных тестов: БД, живая нода, VPN-клиенты,
публичный API (его вызывает хук disconnect.sh) и CLI оператора."""

import asyncio
import re
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.serialization import pkcs12
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner

from ocmanager.cli import app
from ocmanager.core import shell
from ocmanager.core.clock import utcnow
from ocmanager.core.config import Settings
from ocmanager.flows import traffic as traffic_flows
from ocmanager.nodes.driver.local_docker import LocalDockerDriver
from ocmanager.nodes.models import SessionLog, TrafficSample
from ocmanager.subscriptions.models import Subscription
from tests.integration.stand import CERTS_DIR, ClientCert, VpnClient, eventually, online


@dataclass(frozen=True)
class Issued:
    cert: ClientCert
    device_id: int


@dataclass
class Env:
    settings: Settings
    driver: LocalDockerDriver
    vpn: VpnClient
    sessionmaker: async_sessionmaker[AsyncSession]

    async def cli(self, *args: str) -> str:
        """Команда оператора, как её набрал бы человек. CLI вызывает asyncio.run,
        поэтому запускается в потоке."""
        result = await asyncio.to_thread(CliRunner().invoke, app, list(args))
        assert result.exit_code == 0, f"ocmanager {' '.join(args)}\n{result.output}"
        return result.output

    async def paid_client(self, telegram_id: int, *, devices: int = 2) -> None:
        """Клиент с месячным тарифом. Тариф m1 создаётся при первом вызове."""
        if telegram_id == 5001:
            await self.cli(
                *("plan", "create", "--code", "m1", "--name-ru", "Месяц", "--name-en", "Month"),
                *("--days", "30", "--devices", str(devices), "--price", "19900"),
            )
        await self.cli("client", "add", "--telegram-id", str(telegram_id), "--first-name", "T")
        await self.cli("client", "grant", str(telegram_id), "m1")

    async def issue_device(
        self, telegram_id: int, name: str = "laptop", platform: str = "linux"
    ) -> Issued:
        """Устройство через CLI; .p12 кладётся туда, где его видит контейнер vpn-client."""
        CERTS_DIR.mkdir(parents=True, exist_ok=True)
        pending = CERTS_DIR / f"pending-{secrets.token_hex(4)}.p12"
        out = await self.cli(
            *("device", "issue", str(telegram_id), "--name", name, "--platform", platform),
            *("--out", str(pending)),
        )
        fields = dict(re.findall(r"^(\w+):\s+(\S+)$", out, flags=re.MULTILINE))
        username, password = fields["username"], fields["password"]
        pending.rename(CERTS_DIR / f"{username}.p12")
        _, cert, _ = pkcs12.load_key_and_certificates(
            (CERTS_DIR / f"{username}.p12").read_bytes(), password.encode()
        )
        assert cert is not None
        return Issued(ClientCert(username, password, cert.serial_number), int(fields["device"]))

    async def collect_traffic(self) -> None:
        async with self.sessionmaker() as session:
            await traffic_flows.collect_traffic(session, self.settings, utcnow())
            await session.commit()

    async def eventually_disconnected(self, username: str, *, within: float = 10) -> None:
        async def gone() -> bool:
            return username not in await online(self.driver)

        await eventually(gone, within=within)

    async def session_log(self, username: str) -> SessionLog | None:
        async with self.sessionmaker() as session:
            log: SessionLog | None = await session.scalar(
                select(SessionLog).where(SessionLog.username == username)
            )
            return log

    async def eventually_final(self, username: str, *, within: float = 10) -> SessionLog:
        """Ждёт, пока disconnect.sh пришлёт финальные счётчики."""

        async def received() -> bool:
            log = await self.session_log(username)
            return log is not None and log.final_received

        await eventually(received, within=within)
        log = await self.session_log(username)
        assert log is not None
        return log

    async def counted_bytes_in(self, username: str) -> int:
        """Сумма всех сэмплов пользователя — сколько трафика панель в итоге учла."""
        async with self.sessionmaker() as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(TrafficSample.bytes_in_delta), 0)).where(
                    TrafficSample.username == username
                )
            )
            return int(total or 0)

    async def subscription(self) -> Subscription:
        async with self.sessionmaker() as session:
            sub = await session.scalar(select(Subscription))
            assert sub is not None
            return sub

    async def stop_client_gracefully(self, username: str) -> None:
        """SIGTERM openconnect: он честно прощается с сервером, и ocserv запускает
        disconnect.sh. `docker rm -f` (VpnClient.stop) так не умеет."""
        await shell.run(["docker", "stop", "-t", "10", self.vpn.containers[username]], timeout=30)
