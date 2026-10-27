"""Язык интерфейса установщика и `ocm`: английский по умолчанию, русский по `--lang ru`.

Исходный текст в коде русский, английский берётся из `messages_en.py`. Нет перевода — показывается
русский текст (тест не даёт такому случиться). Подстановки: `_("… {name} …", name=value)`."""

import os
from typing import Final

from installer.messages_en import EN

DEFAULT: Final = "en"
LANGUAGES: Final = ("en", "ru")
ENV_VAR: Final = "OCM_LANG"

_current = DEFAULT


def set_lang(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language {code!r}: {', '.join(LANGUAGES)}")
    _current = code


def get_lang() -> str:
    return _current


def from_env() -> str | None:
    value = os.environ.get(ENV_VAR, "").strip().lower()
    return value if value in LANGUAGES else None


def _(text: str, **values: object) -> str:
    out = text if _current == "ru" else EN.get(text, text)
    return out.format(**values) if values else out
