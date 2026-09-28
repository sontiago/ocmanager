"""Интерфейс управления нодой ocserv.

Всё, что панель делает с нодой, идёт через NodeDriver. Сейчас реализация
одна — LocalDockerDriver (docker exec + общий каталог состояния); удалённые
ноды получат свой драйвер с тем же контрактом (driver/contract.py).
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from ocmanager.nodes.occtl.parser import OcSession, OcStatus

ContainerAction = Literal["start", "stop", "restart"]


class NodeUnreachable(Exception):
    """Контейнер не запущен, docker недоступен, occtl не отвечает."""


@dataclass(frozen=True)
class NodeProbe:
    container_state: str  # running / exited / restarting / missing / …
    ocserv: OcStatus | None  # None — occtl не ответил


class NodeDriver(Protocol):
    async def probe(self) -> NodeProbe:
        """Никогда не бросает NodeUnreachable: сбой — это тоже ответ."""
        ...

    async def list_sessions(self) -> list[OcSession]: ...

    async def disconnect_user(self, username: str) -> None:
        """Неизвестный или не подключённый username — не ошибка.
        Невалидный username — ValueError до любого вызова."""
        ...

    async def reload(self) -> None: ...

    async def publish_allowlist(self, usernames: Iterable[str]) -> None:
        """Атомарно заменяет allowed.list. ValueError на невалидном username —
        файл при этом не меняется."""
        ...

    async def read_allowlist(self) -> set[str] | None:
        """None — файла нет."""
        ...

    async def publish_crl(self, pem: bytes) -> None:
        """Атомарно заменяет crl.pem. ValueError, если это не PEM-CRL.
        ocserv 1.3 применяет новый CRL к новым подключениям без reload."""
        ...

    async def read_crl(self) -> bytes | None: ...

    async def container_action(self, action: ContainerAction) -> None: ...

    def stream_logs(self, *, tail: int = 200) -> AbstractAsyncContextManager[AsyncIterator[str]]:
        """async with driver.stream_logs() as lines: async for line in lines: …
        Процесс чтения логов гарантированно завершается на выходе из блока."""
        ...
