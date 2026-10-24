import pytest

from installer.prompts import AnswersPrompter, ScriptedPrompter, TerminalPrompter


def terminal(inputs: list[str], secrets: list[str] | None = None):
    said: list[str] = []
    it, st = iter(inputs), iter(secrets or [])
    prompter = TerminalPrompter(
        input_fn=lambda _prompt: next(it),
        secret_fn=lambda _prompt: next(st),
        out=said.append,
    )
    return prompter, said


def must_be_number(value: str) -> str:
    if not value.isdigit():
        raise ValueError("нужно число")
    return value


def test_ask_repeats_until_the_answer_is_valid() -> None:
    prompter, said = terminal(["abc", "12"])
    assert prompter.ask("n", "Число?", validate=must_be_number) == "12"
    assert any("нужно число" in line for line in said)


def test_ask_returns_the_validators_normalized_value() -> None:
    prompter, _ = terminal(["  HELLO "])
    assert prompter.ask("x", "?", validate=lambda v: v.strip().lower()) == "hello"


def test_an_empty_answer_takes_the_default() -> None:
    prompter, _ = terminal([""])
    assert prompter.ask("x", "?", default="d") == "d"


def test_an_empty_answer_without_a_default_asks_again() -> None:
    prompter, _ = terminal(["", "ok"])
    assert prompter.ask("x", "?") == "ok"


def test_ask_secret_goes_through_the_secret_function_and_is_never_echoed() -> None:
    prompter, said = terminal([], secrets=["s3cret-s3cret"])
    assert prompter.ask_secret("p", "Пароль?") == "s3cret-s3cret"
    assert not any("s3cret" in line for line in said)


def test_ask_secret_validates_and_repeats() -> None:
    prompter, said = terminal([], secrets=["short", "long-enough-password"])

    def at_least_12(value: str) -> str:
        if len(value) < 12:
            raise ValueError("слишком короткий")
        return value

    assert prompter.ask_secret("p", "?", validate=at_least_12) == "long-enough-password"
    assert any("слишком короткий" in line for line in said)


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "да", "Да", "д"])
def test_confirm_understands_yes(answer: str) -> None:
    prompter, _ = terminal([answer])
    assert prompter.confirm("c", "?", default=False) is True


@pytest.mark.parametrize("answer", ["n", "N", "no", "нет", "Нет", "н"])
def test_confirm_understands_no(answer: str) -> None:
    prompter, _ = terminal([answer])
    assert prompter.confirm("c", "?", default=True) is False


def test_confirm_empty_takes_the_default_and_garbage_asks_again() -> None:
    prompter, _ = terminal([""])
    assert prompter.confirm("c", "?", default=True) is True
    prompter, _ = terminal(["maybe", "y"])
    assert prompter.confirm("c", "?", default=False) is True


def test_answers_prompter_reads_by_key_and_validates() -> None:
    prompter = AnswersPrompter({"domain_app": "App.Example.com", "admin_password": "x" * 12})
    assert prompter.ask("domain_app", "?", validate=lambda v: v.lower()) == "app.example.com"
    assert prompter.ask_secret("admin_password", "?") == "x" * 12


def test_answers_prompter_fails_on_a_missing_required_key() -> None:
    with pytest.raises(KeyError, match="domain_vpn"):
        AnswersPrompter({}).ask("domain_vpn", "?")


def test_answers_prompter_uses_the_default_for_an_optional_key() -> None:
    assert AnswersPrompter({}).ask("tribute_key", "?", default="") == ""


def test_answers_prompter_fails_on_an_invalid_answer_instead_of_looping() -> None:
    prompter = AnswersPrompter({"n": "abc"})
    with pytest.raises(ValueError, match="нужно число"):
        prompter.ask("n", "?", validate=must_be_number)


def test_answers_prompter_confirm_reads_booleans() -> None:
    prompter = AnswersPrompter({"use_env": True, "swap": "no"})
    assert prompter.confirm("use_env", "?") is True
    assert prompter.confirm("swap", "?") is False
    assert prompter.confirm("missing", "?", default=True) is True


def test_scripted_prompter_returns_answers_in_order_and_records_keys() -> None:
    prompter = ScriptedPrompter(["a", "b"])
    assert prompter.ask("k1", "?") == "a"
    assert prompter.ask_secret("k2", "?") == "b"
    assert prompter.asked == ["k1", "k2"]
