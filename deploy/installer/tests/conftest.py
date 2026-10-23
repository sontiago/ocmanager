from pathlib import Path

import pytest

from installer.runner import FakeNet, FakeRunner


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def net() -> FakeNet:
    return FakeNet(public_ip="203.0.113.10")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Копия каталога установки: deploy/.env.example нужен для render_env."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    example = Path(__file__).resolve().parents[2] / ".env.example"
    (deploy / ".env.example").write_text(example.read_text())
    return tmp_path


GIB = 1024**3
UBUNTU_2204 = 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.4 LTS"\n'


def meminfo(mem_gib: float, swap_gib: float = 0) -> str:
    return (
        f"MemTotal:       {int(mem_gib * GIB / 1024)} kB\n"
        f"SwapTotal:      {int(swap_gib * GIB / 1024)} kB\n"
    )


class Keyed:
    """Prompter для тестов: ответ по ключу вопроса, а не по порядку. Значение-список
    отдаётся по одному элементу на каждый повторный вопрос (проверка переспрашивания)."""

    def __init__(self, answers: dict[str, object]) -> None:
        self._answers = {k: list(v) if isinstance(v, list) else v for k, v in answers.items()}
        self.asked: list[str] = []
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def _value(self, key: str, default: object) -> object:
        self.asked.append(key)
        if key not in self._answers:
            if default is None:
                raise KeyError(f"тест не задал ответ на вопрос {key}")
            return default
        value = self._answers[key]
        if isinstance(value, list):
            return value.pop(0)
        return value

    def ask(self, key, text, *, default=None, validate=None):  # type: ignore[no-untyped-def]
        while True:
            raw = str(self._value(key, default))
            try:
                return validate(raw) if validate else raw
            except ValueError as exc:
                self.said.append(str(exc))

    def ask_secret(self, key, text, *, validate=None):  # type: ignore[no-untyped-def]
        return self.ask(key, text, validate=validate)

    def confirm(self, key, text, *, default=True):  # type: ignore[no-untyped-def]
        return bool(self._value(key, default))
