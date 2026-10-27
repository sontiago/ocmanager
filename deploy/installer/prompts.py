"""Ввод мастера. Три реализации: терминал (человек), файл ответов (автоматизация), сценарий
(тесты). У каждого вопроса есть ключ: по нему ответы берутся из файла."""

import getpass
from collections.abc import Callable
from typing import Any, Protocol

from installer.i18n import _

Validator = Callable[[str], str]

YES = {"y", "yes", "д", "да"}
NO = {"n", "no", "н", "нет"}


class Prompter(Protocol):
    def say(self, text: str) -> None: ...
    def ask(
        self, key: str, text: str, *, default: str | None = None, validate: Validator | None = None
    ) -> str: ...
    def ask_secret(self, key: str, text: str, *, validate: Validator | None = None) -> str: ...
    def confirm(self, key: str, text: str, *, default: bool = True) -> bool: ...


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in YES:
        return True
    if text in NO:
        return False
    return None


class TerminalPrompter:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        secret_fn: Callable[[str], str] = getpass.getpass,
        out: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._secret = secret_fn
        self._out = out

    def say(self, text: str) -> None:
        self._out(text)

    def ask(
        self, key: str, text: str, *, default: str | None = None, validate: Validator | None = None
    ) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            raw = self._input(f"{text}{suffix}: ").strip()
            if raw == "":
                if default is None:
                    self._out(_("Нужен ответ."))
                    continue
                raw = default
            try:
                return validate(raw) if validate else raw
            except ValueError as exc:
                self._out(str(exc))

    def ask_secret(self, key: str, text: str, *, validate: Validator | None = None) -> str:
        while True:
            raw = self._secret(f"{text}: ")
            try:
                return validate(raw) if validate else raw
            except ValueError as exc:
                self._out(str(exc))

    def confirm(self, key: str, text: str, *, default: bool = True) -> bool:
        hint = _("Д/н") if default else _("д/Н")
        while True:
            raw = self._input(f"{text} [{hint}]: ").strip()
            if raw == "":
                return default
            parsed = parse_bool(raw)
            if parsed is not None:
                return parsed
            self._out(_("Ответьте «да» или «нет»."))


class AnswersPrompter:
    """Ответы из словаря (файла). Обязательного ключа нет — `KeyError`; невалидный ответ —
    исключение, а не бесконечный цикл: автоматизации нечего переспрашивать."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self._answers = answers

    def say(self, text: str) -> None:
        print(text)

    def _get(self, key: str, default: Any) -> Any:
        if key in self._answers:
            return self._answers[key]
        if default is None:
            raise KeyError(_("в файле ответов нет ключа {key}", key=key))
        return default

    def ask(
        self, key: str, text: str, *, default: str | None = None, validate: Validator | None = None
    ) -> str:
        raw = str(self._get(key, default)).strip()
        return validate(raw) if validate else raw

    def ask_secret(self, key: str, text: str, *, validate: Validator | None = None) -> str:
        raw = str(self._get(key, None))
        return validate(raw) if validate else raw

    def confirm(self, key: str, text: str, *, default: bool = True) -> bool:
        parsed = parse_bool(self._get(key, default))
        return default if parsed is None else parsed


class ScriptedPrompter:
    """Тесты: ответы по порядку, спрошенные ключи записываются в `asked`."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = iter(answers)
        self.asked: list[str] = []
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def _next(self, key: str) -> Any:
        self.asked.append(key)
        return next(self._answers)

    def ask(
        self, key: str, text: str, *, default: str | None = None, validate: Validator | None = None
    ) -> str:
        raw = str(self._next(key))
        return validate(raw) if validate else raw

    def ask_secret(self, key: str, text: str, *, validate: Validator | None = None) -> str:
        raw = str(self._next(key))
        return validate(raw) if validate else raw

    def confirm(self, key: str, text: str, *, default: bool = True) -> bool:
        return bool(self._next(key))
