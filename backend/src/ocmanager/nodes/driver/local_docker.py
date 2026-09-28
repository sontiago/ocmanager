"""Нода ocserv в соседнем Docker-контейнере на этом же хосте.

occtl — через `docker exec`, файлы состояния — напрямую в общем каталоге
(bind mount в контейнер). Файлы доступны и при остановленном контейнере.
"""

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Self

from ocmanager.core import shell
from ocmanager.core.config import Settings
from ocmanager.nodes import files
from ocmanager.nodes.driver.base import ContainerAction, NodeProbe, NodeUnreachable
from ocmanager.nodes.occtl.client import OcctlClient
from ocmanager.nodes.occtl.parser import OcctlParseError, OcSession

ALLOWLIST_FILE = "allowed.list"
CRL_FILE = "crl.pem"
CONTAINER_ACTION_TIMEOUT_S = 60.0


async def _read(path: Path) -> bytes | None:
    try:
        return await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        return None


class LocalDockerDriver:
    def __init__(self, *, container: str, state_dir: Path) -> None:
        self.container = container
        self.state_dir = state_dir
        self.occtl = OcctlClient(container)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(container=settings.ocserv_container, state_dir=settings.ocserv_state_dir)

    async def _container_state(self) -> str:
        argv = ["docker", "inspect", "-f", "{{.State.Status}}", self.container]
        try:
            result = await shell.run(argv, check=False)
        except (shell.CommandTimeout, shell.CommandNotFound):
            return "unknown"
        if result.returncode != 0:
            return "missing" if "no such object" in result.stderr.lower() else "unknown"
        return result.stdout.strip() or "unknown"

    async def probe(self) -> NodeProbe:
        state = await self._container_state()
        if state != "running":
            return NodeProbe(state, None)
        try:
            return NodeProbe(state, await self.occtl.show_status())
        except (NodeUnreachable, OcctlParseError):
            return NodeProbe(state, None)

    async def list_sessions(self) -> list[OcSession]:
        return await self.occtl.show_users()

    async def disconnect_user(self, username: str) -> None:
        await self.occtl.disconnect_user(username)

    async def reload(self) -> None:
        await self.occtl.reload()

    async def publish_allowlist(self, usernames: Iterable[str]) -> None:
        data = files.render_allowlist(usernames)  # ValueError — до записи
        await asyncio.to_thread(files.atomic_write, self.state_dir / ALLOWLIST_FILE, data)

    async def read_allowlist(self) -> set[str] | None:
        data = await _read(self.state_dir / ALLOWLIST_FILE)
        return None if data is None else files.parse_allowlist(data)

    async def publish_crl(self, pem: bytes) -> None:
        files.validate_crl(pem)
        await asyncio.to_thread(files.atomic_write, self.state_dir / CRL_FILE, pem)

    async def read_crl(self) -> bytes | None:
        return await _read(self.state_dir / CRL_FILE)

    async def container_action(self, action: ContainerAction) -> None:
        argv = ["docker", action, self.container]
        try:
            await shell.run(argv, timeout=CONTAINER_ACTION_TIMEOUT_S)
        except shell.CommandError as exc:
            raise NodeUnreachable(str(exc)) from exc

    @asynccontextmanager
    async def stream_logs(self, *, tail: int = 200) -> AsyncIterator[AsyncIterator[str]]:
        argv = ["docker", "logs", "-f", "--tail", str(tail), self.container]
        try:
            async with shell.stream(argv) as lines:
                yield lines
        except shell.CommandNotFound as exc:
            raise NodeUnreachable(str(exc)) from exc
