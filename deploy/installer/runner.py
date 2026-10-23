"""Внешний мир установщика: команды и сеть. Всё, что трогает систему, идёт через эти два
интерфейса — поэтому логику можно проверять тестами с подменой, без Docker и без интернета."""

import json
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str = ""
    stderr: str = ""


class CommandError(Exception):
    """Команда завершилась с ошибкой. В сообщение попадает команда и stderr, но не stdin:
    через stdin передаются пароли."""

    def __init__(self, cmd: Sequence[str], code: int, stderr: str = "") -> None:
        self.cmd = list(cmd)
        self.code = code
        self.stderr = stderr
        tail = stderr.strip()[-500:]
        super().__init__(f"команда {' '.join(self.cmd)} завершилась с кодом {code}: {tail}")


class Runner(Protocol):
    def run(
        self,
        cmd: Sequence[str],
        *,
        input: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Result: ...


class SubprocessRunner:
    def run(
        self,
        cmd: Sequence[str],
        *,
        input: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Result:
        try:
            done = subprocess.run(  # noqa: S603 — команды собирает сам установщик
                list(cmd),
                input=input,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=None if env is None else {**_base_env(), **env},
                check=False,
            )
        except OSError as exc:
            if check:
                raise CommandError(cmd, 127, str(exc)) from exc
            return Result(127, "", str(exc))
        result = Result(done.returncode, done.stdout, done.stderr)
        if check and result.code != 0:
            raise CommandError(cmd, result.code, result.stderr)
        return result


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


Outcome = Result | BaseException | Callable[[list[str]], Result]


@dataclass
class FakeRunner:
    """Подмена для тестов: записывает вызовы, отвечает по подстроке команды."""

    calls: list[list[str]] = field(default_factory=list)
    inputs: list[str | None] = field(default_factory=list)
    _rules: list[tuple[str, Outcome]] = field(default_factory=list)

    def on(self, needle: str, outcome: Outcome) -> None:
        """Первое правило, чья подстрока входит в команду, выигрывает. Ответ — Result, исключение,
        которое нужно бросить, или функция от команды (побочные эффекты, например создание
        файла, который в жизни создала бы сама команда)."""
        self._rules.append((needle, outcome))

    def run(
        self,
        cmd: Sequence[str],
        *,
        input: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Result:
        self.calls.append(list(cmd))
        self.inputs.append(input)
        joined = " ".join(cmd)
        outcome: Outcome = Result(0)
        for needle, rule in self._rules:
            if needle in joined:
                outcome = rule
                break
        if callable(outcome):
            outcome = outcome(list(cmd))
        if isinstance(outcome, BaseException):
            raise outcome
        if check and outcome.code != 0:
            raise CommandError(cmd, outcome.code, outcome.stderr)
        return outcome

    def joined(self) -> list[str]:
        return [" ".join(c) for c in self.calls]


class NetError(Exception):
    """`unreachable` — нет связи с сервисом; иначе сервис ответил отказом (неверный токен)."""

    def __init__(self, message: str, *, unreachable: bool = False) -> None:
        super().__init__(message)
        self.unreachable = unreachable


class Net(Protocol):
    def public_ip(self) -> str | None: ...
    def resolve_a(self, host: str) -> list[str]: ...
    def telegram_get_me(self, token: str) -> str: ...


IP_ENDPOINTS = ("https://api.ipify.org", "https://ifconfig.me/ip")
TIMEOUT_S = 8


class SystemNet:
    def public_ip(self) -> str | None:
        for url in IP_ENDPOINTS:
            try:
                with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310
                    text = response.read().decode().strip()
            except (urllib.error.URLError, OSError, ValueError):
                continue
            try:
                socket.inet_aton(text)
            except OSError:
                continue
            return text
        return None

    def resolve_a(self, host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET)
        except OSError:
            return []
        return sorted({str(info[4][0]) for info in infos})

    def telegram_get_me(self, token: str) -> str:
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            # 401/404 от Telegram — токен не принят; сеть при этом работает.
            raise NetError("Telegram не принял токен") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise NetError("нет связи с Telegram", unreachable=True) from exc
        username = (payload.get("result") or {}).get("username")
        if not payload.get("ok") or not username:
            raise NetError("Telegram не принял токен")
        return str(username)


@dataclass
class FakeNet:
    public_ip_value: str | None = None
    a_records: dict[str, list[str]] = field(default_factory=dict)
    bots: dict[str, str] = field(default_factory=dict)
    telegram_down: bool = False

    def __init__(
        self,
        public_ip: str | None = None,
        a_records: dict[str, list[str]] | None = None,
        bots: dict[str, str] | None = None,
        telegram_down: bool = False,
    ) -> None:
        self.public_ip_value = public_ip
        self.a_records = a_records or {}
        self.bots = bots or {}
        self.telegram_down = telegram_down

    def public_ip(self) -> str | None:
        return self.public_ip_value

    def resolve_a(self, host: str) -> list[str]:
        return list(self.a_records.get(host, []))

    def telegram_get_me(self, token: str) -> str:
        if self.telegram_down:
            raise NetError("нет связи с Telegram", unreachable=True)
        try:
            return self.bots[token]
        except KeyError:
            raise NetError("Telegram не принял токен") from None
