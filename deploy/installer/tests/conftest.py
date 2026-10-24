import shutil
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path as _Path

import pytest

from installer.backup import BackupPaths
from installer.runner import CommandError as _CommandError
from installer.runner import FakeNet, FakeRunner
from installer.runner import Result as _Result
from installer.runner import SubprocessRunner as _SubprocessRunner


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


NOW = datetime(2026, 10, 23, 3, 30, tzinfo=timezone.utc)
DUMP_BYTES = b"PGDMP-pretend-custom-format-dump"
PKI_BYTES = b"pretend-pki-tarball"


class Stack(FakeRunner):
    """Подмена docker/git для бэкапа: «команды» создают файлы, как создали бы настоящие, а
    openssl настоящий — иначе шифрование не проверить."""

    def __init__(self, paths: "BackupPaths") -> None:
        super().__init__()
        self._real = _SubprocessRunner()
        self.paths = paths
        self.pki_restored: bytes | None = None
        self.dump_loaded: bytes | None = None
        self.on("compose cp postgres:", self._dump_out)
        self.on("compose cp ", self._dump_in)
        self.on("alpine tar czf", self._pki_out)
        self.on("alpine sh -c", self._pki_in)
        self.on("git rev-parse", _Result(0, "abc1234\n"))

    def run(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[0] == "openssl":
            self.calls.append(list(cmd))
            self.inputs.append(kwargs.get("input"))
            return self._real.run(cmd, **{k: v for k, v in kwargs.items() if k != "cwd"})
        return super().run(cmd, **kwargs)

    @staticmethod
    def _mount_dir(cmd: list[str], target: str) -> _Path:
        for i, part in enumerate(cmd):
            if part == "-v" and cmd[i + 1].split(":")[1] == target:
                return _Path(cmd[i + 1].split(":")[0])
        raise AssertionError(f"нет монтирования {target} в {cmd}")

    def _dump_out(self, cmd: list[str]) -> _Result:
        _Path(cmd[-1]).write_bytes(DUMP_BYTES)
        return _Result(0)

    def _dump_in(self, cmd: list[str]) -> _Result:
        self.dump_loaded = _Path(cmd[-2]).read_bytes()
        return _Result(0)

    def _pki_out(self, cmd: list[str]) -> _Result:
        (self._mount_dir(cmd, "/out") / "pki.tgz").write_bytes(PKI_BYTES)
        return _Result(0)

    def _pki_in(self, cmd: list[str]) -> _Result:
        self.pki_restored = (self._mount_dir(cmd, "/in") / "pki.tgz").read_bytes()
        return _Result(0)


requires_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="нет openssl")
_ = (_CommandError,)
