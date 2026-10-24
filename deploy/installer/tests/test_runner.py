import pytest

from installer.runner import CommandError, FakeNet, FakeRunner, NetError, Result, SubprocessRunner


def test_the_fake_runner_records_calls_and_input() -> None:
    fake = FakeRunner()
    fake.run(["docker", "compose", "up"], input="secret\n")
    assert fake.calls == [["docker", "compose", "up"]]
    assert fake.inputs == ["secret\n"]


def test_the_fake_runner_answers_by_substring_of_the_command() -> None:
    fake = FakeRunner()
    fake.on("pki init", Result(0, "created"))
    assert fake.run(["docker", "compose", "run", "--rm", "cli", "pki", "init"]).stdout == "created"
    assert fake.run(["ls"]).stdout == ""


def test_a_failing_command_raises_unless_check_is_off() -> None:
    fake = FakeRunner()
    fake.on("boom", Result(2, "", "it broke"))
    with pytest.raises(CommandError) as err:
        fake.run(["boom"])
    assert err.value.code == 2
    assert "it broke" in str(err.value)
    assert fake.run(["boom"], check=False).code == 2


def test_a_rule_can_raise_an_exception() -> None:
    fake = FakeRunner()
    fake.on("pg_dump", OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        fake.run(["pg_dump"])


def test_the_error_message_never_contains_the_stdin() -> None:
    fake = FakeRunner()
    fake.on("create", Result(1, "", "bad"))
    with pytest.raises(CommandError) as err:
        fake.run(["create", "owner"], input="hunter2-hunter2\n")
    assert "hunter2" not in str(err.value)


def test_the_real_runner_runs_a_command() -> None:
    result = SubprocessRunner().run(["echo", "x"])
    assert (result.code, result.stdout.strip()) == (0, "x")


def test_the_real_runner_reports_a_missing_binary_as_a_command_error() -> None:
    with pytest.raises(CommandError):
        SubprocessRunner().run(["definitely-not-a-binary-xyz"])


def test_the_real_runner_passes_stdin() -> None:
    assert SubprocessRunner().run(["cat"], input="hello").stdout == "hello"


def test_the_fake_net_answers_from_its_tables() -> None:
    net = FakeNet(public_ip="1.2.3.4", a_records={"app.example.com": ["1.2.3.4"]})
    assert net.public_ip() == "1.2.3.4"
    assert net.resolve_a("app.example.com") == ["1.2.3.4"]
    assert net.resolve_a("none.example.com") == []


def test_telegram_get_me_returns_the_bot_name_or_raises() -> None:
    net = FakeNet(bots={"123456:abcdefghijklmnopqrstuvwx": "ocbot"})
    assert net.telegram_get_me("123456:abcdefghijklmnopqrstuvwx") == "ocbot"
    with pytest.raises(NetError) as err:
        net.telegram_get_me("999999:zzzzzzzzzzzzzzzzzzzzzzzz")
    assert err.value.unreachable is False


def test_an_unreachable_telegram_is_told_apart_from_a_wrong_token() -> None:
    net = FakeNet(telegram_down=True)
    with pytest.raises(NetError) as err:
        net.telegram_get_me("123456:abcdefghijklmnopqrstuvwx")
    assert err.value.unreachable is True


def test_a_rule_can_be_a_function_with_side_effects(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "made-by-the-command"

    def create(cmd: list[str]) -> Result:
        target.write_text(cmd[-1])
        return Result(0, "done")

    fake = FakeRunner()
    fake.on("make-file", create)
    assert fake.run(["make-file", "payload"]).stdout == "done"
    assert target.read_text() == "payload"
