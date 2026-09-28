"""CLI node без БД: команды, которым хватает драйвера. status и действия
с аудитом проверяются вручную (Задача 1.6, шаг 6) и тестами flows/test_nodes.py."""

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from ocmanager.cli import app
from ocmanager.nodes import registry
from ocmanager.nodes.driver.fake import FakeNodeDriver

runner = CliRunner()


@pytest.fixture
def fake() -> Iterator[FakeNodeDriver]:
    driver = FakeNodeDriver()
    with registry.override_driver(driver):
        yield driver


def test_allow_publishes_list(fake: FakeNodeDriver) -> None:
    result = runner.invoke(app, ["node", "allow", "c2-d1", "c1-d1"])
    assert result.exit_code == 0, result.output
    assert fake.allowlist == {"c1-d1", "c2-d1"}


def test_allow_rejects_bad_username(fake: FakeNodeDriver) -> None:
    result = runner.invoke(app, ["node", "allow", "c1-d1", "root"])
    assert result.exit_code == 1
    assert fake.allowlist == set()


def test_allow_refused_in_production(fake: FakeNodeDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCM_ENV", "production")
    assert runner.invoke(app, ["node", "allow", "c1-d1"]).exit_code == 1


def test_sessions_lists_users(fake: FakeNodeDriver) -> None:
    fake.add_session("c1-d1", bytes_in=10)
    result = runner.invoke(app, ["node", "sessions"])
    assert result.exit_code == 0, result.output
    assert "c1-d1" in result.output
    assert "in=10" in result.output


def test_sessions_when_node_down(fake: FakeNodeDriver) -> None:
    fake.container_state = "exited"
    result = runner.invoke(app, ["node", "sessions"])
    assert result.exit_code == 1
    assert "нода недоступна" in result.output
