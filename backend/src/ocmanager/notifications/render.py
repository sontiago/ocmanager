"""Шаблоны уведомлений. Тексты — в templates/{ru,en}.json: правка текста не трогает код.

Подстановка — str.format_map: значения вставляются как есть, фигурные скобки внутри
значений не интерпретируются. Все сообщения — простой текст, parse_mode не используется.
"""

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any

LANGS = ("ru", "en")
TEMPLATES_DIR = Path(__file__).with_name("templates")


class TemplateError(Exception):
    """Нет шаблона, нет языка или payload не подходит к шаблону."""


@lru_cache
def _catalog(lang: str) -> dict[str, str]:
    if lang not in LANGS:
        raise TemplateError(f"unknown language {lang!r}")
    catalog: dict[str, str] = json.loads((TEMPLATES_DIR / f"{lang}.json").read_text("utf-8"))
    return catalog


def _template(template_key: str, lang: str) -> str:
    try:
        return _catalog(lang)[template_key]
    except KeyError:
        raise TemplateError(f"no template {template_key!r} for {lang!r}") from None


def keys(lang: str) -> frozenset[str]:
    return frozenset(_catalog(lang))


def placeholders(template_key: str, lang: str) -> frozenset[str]:
    """Имена полей, которые шаблон требует от payload."""
    parsed = Formatter().parse(_template(template_key, lang))
    return frozenset(name for _, name, _, _ in parsed if name)


def render(template_key: str, lang: str, payload: Mapping[str, Any]) -> str:
    """Лишние ключи payload игнорируются (в проде они безвредны), недостающие — ошибка:
    сообщение с дырой хуже, чем отказ поставить его в очередь."""
    text = _template(template_key, lang)
    missing = placeholders(template_key, lang) - payload.keys()
    if missing:
        raise TemplateError(f"{template_key}/{lang}: payload lacks {sorted(missing)}")
    return text.format_map(payload)
