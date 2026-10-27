"""LocalDockerDriver без Docker: shell.run подменён, проверяем точный argv
и отображение сбоев. Живой ocserv — в tests/integration."""

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from ocmanager.core import shell
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.driver.local_docker import LocalDockerDriver

FIXTURES = Path(__file__).parents[1] / "occtl" / "fixtures"

Reply = shell.CommandResult | Exception
Responder = Callable[[tuple[str, ...]], Reply]


class FakeShell:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.replies: dict[tuple[str, ...], Reply] = {}

    def reply(self, argv: Sequence[str], *, code: int = 0, out: str = "", err: str = "") -> None:
        self.replies[tuple(argv)] = shell.CommandResult(tuple(argv), code, out, err)

    def fail(self, argv: Sequence[str], exc: Exception) -> None:
        self.replies[tuple(argv)] = exc

    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 10.0,  # noqa: ASYNC109 — сигнатура shell.run
        input: bytes | None = None,
        check: bool = True,
    ) -> shell.CommandResult:
        args = tuple(argv)
        self.calls.append(args)
        reply = self.replies.get(args, shell.CommandResult(args, 0, "", ""))
        if isinstance(reply, Exception):
            raise reply
        if check and reply.returncode != 0:
            raise shell.CommandFailed(reply)
        return reply


@pytest.fixture
def sh(monkeypatch: pytest.MonkeyPatch) -> FakeShell:
    fake = FakeShell()
    monkeypatch.setattr(shell, "run", fake.run)
    return fake


@pytest.fixture
def driver(tmp_path: Path) -> LocalDockerDriver:
    return LocalDockerDriver(container="ocm-ocserv", state_dir=tmp_path)


EXEC = ("docker", "exec", "ocm-ocserv", "occtl")
INSPECT = ("docker", "inspect", "-f", "{{.State.Status}}", "ocm-ocserv")


async def test_list_sessions_argv_and_parse(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.reply([*EXEC, "-j", "show", "users"], out=(FIXTURES / "users_two.json").read_text())
    sessions = await driver.list_sessions()
    assert {s.username for s in sessions} == {"c9001-d1", "c9001-d2"}
    assert sh.calls == [(*EXEC, "-j", "show", "users")]


async def test_disconnect_argv(sh: FakeShell, driver: LocalDockerDriver) -> None:
    await driver.disconnect_user("c1-d1")
    assert sh.calls == [(*EXEC, "disconnect", "user", "c1-d1")]


async def test_disconnect_not_connected_is_noop(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.reply(
        [*EXEC, "disconnect", "user", "c1-d1"],
        code=1,
        out="could not disconnect user 'c1-d1'\n",
    )
    await driver.disconnect_user("c1-d1")


async def test_disconnect_invalid_username_never_runs(
    sh: FakeShell, driver: LocalDockerDriver
) -> None:
    with pytest.raises(ValueError, match="invalid ocserv username"):
        await driver.disconnect_user("c1-d1; reboot")
    assert sh.calls == []


CAT = ("docker", "exec", "ocm-ocserv", "cat", "/caddy-data/server.crt")
CERT = Path("/caddy-data/server.crt")


async def test_read_server_cert_runs_cat_in_the_container(
    sh: FakeShell, driver: LocalDockerDriver
) -> None:
    sh.reply(CAT, out="-----BEGIN CERTIFICATE-----\n")
    assert await driver.read_server_cert(CERT) == b"-----BEGIN CERTIFICATE-----\n"
    assert sh.calls == [CAT]


async def test_read_server_cert_missing_file_is_none(
    sh: FakeShell, driver: LocalDockerDriver
) -> None:
    sh.reply(CAT, code=1, err="cat: /caddy-data/server.crt: No such file or directory")
    assert await driver.read_server_cert(CERT) is None


async def test_read_server_cert_other_failures_are_unreachable(
    sh: FakeShell, driver: LocalDockerDriver
) -> None:
    sh.reply(CAT, code=1, err="Error response from daemon: container is not running")
    with pytest.raises(NodeUnreachable):
        await driver.read_server_cert(CERT)


async def test_reload_argv(sh: FakeShell, driver: LocalDockerDriver) -> None:
    await driver.reload()
    assert sh.calls == [(*EXEC, "reload")]


@pytest.mark.parametrize(
    "err",
    [
        "Error response from daemon: No such container: ocm-ocserv",
        "Error response from daemon: container abc is not running",
        "error connecting to ocserv socket '/run/occtl.socket': No such file or directory",
    ],
)
async def test_occtl_failures_become_unreachable(
    sh: FakeShell, driver: LocalDockerDriver, err: str
) -> None:
    sh.reply([*EXEC, "-j", "show", "users"], code=1, err=err)
    with pytest.raises(NodeUnreachable):
        await driver.list_sessions()


@pytest.mark.parametrize(
    "exc", [shell.CommandTimeout(("docker",), 10), shell.CommandNotFound(("docker",))]
)
async def test_timeout_and_missing_docker_become_unreachable(
    sh: FakeShell, driver: LocalDockerDriver, exc: Exception
) -> None:
    sh.fail([*EXEC, "reload"], exc)
    with pytest.raises(NodeUnreachable):
        await driver.reload()


async def test_probe_running(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.reply(INSPECT, out="running\n")
    sh.reply([*EXEC, "-j", "show", "status"], out=(FIXTURES / "status.json").read_text())
    probe = await driver.probe()
    assert probe.container_state == "running"
    assert probe.ocserv is not None
    assert probe.ocserv.up is True


async def test_probe_missing_container(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.reply(INSPECT, code=1, err="error: no such object: ocm-ocserv")
    probe = await driver.probe()
    assert (probe.container_state, probe.ocserv) == ("missing", None)
    assert sh.calls == [INSPECT]


async def test_probe_exited_skips_occtl(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.reply(INSPECT, out="exited\n")
    assert (await driver.probe()).container_state == "exited"
    assert sh.calls == [INSPECT]


@pytest.mark.parametrize("out", ["", "garbage"])
async def test_probe_broken_occtl_is_running_without_status(
    sh: FakeShell, driver: LocalDockerDriver, out: str
) -> None:
    sh.reply(INSPECT, out="running\n")
    sh.reply([*EXEC, "-j", "show", "status"], code=1 if not out else 0, out=out)
    probe = await driver.probe()
    assert (probe.container_state, probe.ocserv) == ("running", None)


async def test_probe_without_docker_cli(sh: FakeShell, driver: LocalDockerDriver) -> None:
    sh.fail(INSPECT, shell.CommandNotFound(("docker",)))
    assert (await driver.probe()).container_state == "unknown"


async def test_container_action_argv(sh: FakeShell, driver: LocalDockerDriver) -> None:
    await driver.container_action("restart")
    assert sh.calls == [("docker", "restart", "ocm-ocserv")]


async def test_files_live_in_state_dir(driver: LocalDockerDriver, tmp_path: Path) -> None:
    assert await driver.read_allowlist() is None
    assert await driver.read_crl() is None
    await driver.publish_allowlist(["c2-d1", "c1-d1"])
    assert (tmp_path / "allowed.list").read_bytes() == b"c1-d1\nc2-d1\n"


async def test_publish_routes_rebuilds_the_conf_and_reloads_when_running(
    sh: FakeShell, driver: LocalDockerDriver, tmp_path: Path
) -> None:
    sh.reply(("docker", "inspect", "-f", "{{.State.Status}}", "ocm-ocserv"), out="running\n")
    await driver.publish_routes(["85.142.247.47"])
    assert "no-route = 85.142.247.47/32" in (tmp_path / "default-user.conf").read_text()
    assert sh.calls[-2:] == [("docker", "exec", "ocm-ocserv", "ocm-render-conf"), (*EXEC, "reload")]


async def test_publish_routes_on_a_stopped_node_only_writes_the_file(
    sh: FakeShell, driver: LocalDockerDriver, tmp_path: Path
) -> None:
    sh.reply(("docker", "inspect", "-f", "{{.State.Status}}", "ocm-ocserv"), out="exited\n")
    await driver.publish_routes(["85.142.247.47"])
    assert (tmp_path / "default-user.conf").exists()
    assert all("ocm-render-conf" not in call for call in sh.calls)


async def test_a_failing_render_is_a_node_error_but_the_file_stays(
    sh: FakeShell, driver: LocalDockerDriver, tmp_path: Path
) -> None:
    sh.reply(("docker", "inspect", "-f", "{{.State.Status}}", "ocm-ocserv"), out="running\n")
    sh.reply(("docker", "exec", "ocm-ocserv", "ocm-render-conf"), code=1, err="bad conf")
    with pytest.raises(NodeUnreachable):
        await driver.publish_routes(["85.142.247.47"])
    assert (tmp_path / "default-user.conf").exists()
