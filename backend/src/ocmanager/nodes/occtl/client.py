"""occtl внутри контейнера ноды: `docker exec <container> occtl -j …`.

Имя контейнера — только из Settings; username проходит USERNAME_RE до вызова.
"""

import structlog

from ocmanager.core import shell
from ocmanager.nodes import files
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.occtl.parser import OcSession, OcStatus, parse_status, parse_users

log = structlog.get_logger(__name__)

# occtl пишет это в stdout с кодом 1, если такого пользователя нет среди подключённых.
NOT_CONNECTED = "could not disconnect user"


class OcctlClient:
    def __init__(self, container: str, *, timeout: float = 10.0) -> None:
        self.container = container
        self.timeout = timeout

    async def _run(self, *args: str) -> shell.CommandResult:
        argv = ["docker", "exec", self.container, "occtl", *args]
        try:
            return await shell.run(argv, timeout=self.timeout)
        except shell.CommandFailed as exc:
            out = (exc.result.stdout + exc.result.stderr).strip()
            raise NodeUnreachable(f"occtl {' '.join(args)}: {out[:300]}") from exc
        except (shell.CommandTimeout, shell.CommandNotFound) as exc:
            raise NodeUnreachable(str(exc)) from exc

    async def show_users(self) -> list[OcSession]:
        return parse_users((await self._run("-j", "show", "users")).stdout)

    async def show_status(self) -> OcStatus:
        return parse_status((await self._run("-j", "show", "status")).stdout)

    async def disconnect_user(self, username: str) -> None:
        files.validate_username(username)
        try:
            await self._run("disconnect", "user", username)
        except NodeUnreachable as exc:
            if NOT_CONNECTED in str(exc):
                log.info("occtl_disconnect_not_connected", username=username)
                return
            raise

    async def reload(self) -> None:
        await self._run("reload")
