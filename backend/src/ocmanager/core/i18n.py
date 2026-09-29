from collections.abc import Mapping


def pick(i18n: Mapping[str, str] | None, lang: str, *, fallback: str = "ru") -> str | None:
    """Строка на языке клиента; нет её — на языке по умолчанию; нет и той — None.
    Пустая строка считается отсутствующей."""
    if not i18n:
        return None
    return i18n.get(lang) or i18n.get(fallback) or None
