"""NodeDriver в памяти — для юнит-тестов сервисов и flows.

Состояние контейнера задаётся полями: container_state != "running" или
occtl_ok=False — методы, которым нужен occtl, бросают NodeUnreachable.
Файлы состояния, как и у LocalDockerDriver, доступны при остановленном
контейнере.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ocmanager.core.clock import utcnow
from ocmanager.nodes import files
from ocmanager.nodes.driver.base import ContainerAction, NodeProbe, NodeUnreachable
from ocmanager.nodes.occtl.parser import OcSession, OcStatus


@dataclass
class FakeNodeDriver:
    sessions: list[OcSession] = field(default_factory=list)
    allowlist: set[str] | None = field(default_factory=set)
    crl: bytes | None = None
    container_state: str = "running"
    occtl_ok: bool = True
    log_lines: list[str] = field(default_factory=lambda: ["ocserv started"])
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    _next_id: int = 1

    def _occtl(self) -> None:
        if self.container_state != "running" or not self.occtl_ok:
            raise NodeUnreachable(f"container {self.container_state}, occtl_ok={self.occtl_ok}")

    def add_session(
        self,
        username: str,
        *,
        bytes_in: int = 0,
        bytes_out: int = 0,
        session_id: str | None = None,
        connected_at: datetime | None = None,
    ) -> OcSession:
        if session_id is None:
            session_id = str(self._next_id)
            self._next_id += 1
        s = OcSession(
            session_id=session_id,
            username=username,
            remote_ip="203.0.113.1",
            vpn_ip="10.77.0.2",
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            connected_at=connected_at or utcnow(),
            user_agent="fake",
        )
        self.sessions.append(s)
        return s

    async def probe(self) -> NodeProbe:
        self.calls.append(("probe", ()))
        if self.container_state != "running" or not self.occtl_ok:
            return NodeProbe(self.container_state, None)
        status = OcStatus(
            up=True,
            active_sessions=len(self.sessions),
            uptime_s=60,
            raw={"Status": "online"},
        )
        return NodeProbe("running", status)

    async def list_sessions(self) -> list[OcSession]:
        self.calls.append(("list_sessions", ()))
        self._occtl()
        return list(self.sessions)

    async def disconnect_user(self, username: str) -> None:
        files.validate_username(username)
        self.calls.append(("disconnect_user", (username,)))
        self._occtl()
        self.sessions = [s for s in self.sessions if s.username != username]

    async def reload(self) -> None:
        self.calls.append(("reload", ()))
        self._occtl()

    async def publish_allowlist(self, usernames: Iterable[str]) -> None:
        data = files.render_allowlist(usernames)
        self.calls.append(("publish_allowlist", (data,)))
        self.allowlist = files.parse_allowlist(data)

    async def read_allowlist(self) -> set[str] | None:
        self.calls.append(("read_allowlist", ()))
        return None if self.allowlist is None else set(self.allowlist)

    async def publish_crl(self, pem: bytes) -> None:
        files.validate_crl(pem)
        self.calls.append(("publish_crl", (pem,)))
        self.crl = pem

    async def read_crl(self) -> bytes | None:
        self.calls.append(("read_crl", ()))
        return self.crl

    async def container_action(self, action: ContainerAction) -> None:
        self.calls.append(("container_action", (action,)))
        self.container_state = "exited" if action == "stop" else "running"

    @asynccontextmanager
    async def stream_logs(self, *, tail: int = 200) -> AsyncIterator[AsyncIterator[str]]:
        self.calls.append(("stream_logs", (tail,)))
        if self.container_state == "missing":  # логи есть и у остановленного контейнера
            raise NodeUnreachable("container missing")

        async def lines() -> AsyncIterator[str]:
            for line in self.log_lines[-tail:]:
                yield line

        yield lines()
