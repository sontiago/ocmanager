import pytest

from ocmanager.nodes.driver.base import NodeDriver, NodeUnreachable
from ocmanager.nodes.driver.contract import DriverContract
from ocmanager.nodes.driver.fake import FakeNodeDriver


class TestFakeDriver(DriverContract):
    @pytest.fixture
    def driver(self) -> NodeDriver:
        return FakeNodeDriver()


def test_fake_satisfies_protocol() -> None:
    driver: NodeDriver = FakeNodeDriver()  # mypy проверяет совместимость с Protocol
    assert driver is not None


async def test_stopped_container_breaks_occtl_but_not_probe() -> None:
    fake = FakeNodeDriver(container_state="exited")
    with pytest.raises(NodeUnreachable):
        await fake.list_sessions()
    probe = await fake.probe()
    assert (probe.container_state, probe.ocserv) == ("exited", None)


async def test_broken_occtl_gives_running_without_status() -> None:
    fake = FakeNodeDriver(occtl_ok=False)
    probe = await fake.probe()
    assert (probe.container_state, probe.ocserv) == ("running", None)


async def test_files_work_while_container_stopped() -> None:
    fake = FakeNodeDriver(container_state="exited")
    await fake.publish_allowlist(["c1-d1"])
    assert await fake.read_allowlist() == {"c1-d1"}


async def test_disconnect_removes_only_that_user() -> None:
    fake = FakeNodeDriver()
    fake.add_session("c1-d1")
    fake.add_session("c1-d2")
    await fake.disconnect_user("c1-d1")
    assert [s.username for s in await fake.list_sessions()] == ["c1-d2"]


async def test_container_action_changes_state_and_is_logged() -> None:
    fake = FakeNodeDriver()
    await fake.container_action("stop")
    assert fake.container_state == "exited"
    await fake.container_action("start")
    assert fake.container_state == "running"
    assert ("container_action", ("stop",)) in fake.calls


def test_add_session_assigns_distinct_ids() -> None:
    fake = FakeNodeDriver()
    assert fake.add_session("c1-d1").session_id != fake.add_session("c1-d2").session_id
