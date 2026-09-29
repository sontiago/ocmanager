from ocmanager.core.i18n import pick

TEXT = {"ru": "Месяц", "en": "Month"}


def test_picks_requested_language() -> None:
    assert pick(TEXT, "en") == "Month"


def test_missing_language_falls_back_to_default() -> None:
    assert pick({"ru": "Месяц"}, "en") == "Месяц"


def test_custom_fallback() -> None:
    assert pick({"en": "Month"}, "ru", fallback="en") == "Month"


def test_empty_string_counts_as_missing() -> None:
    assert pick({"ru": "Месяц", "en": ""}, "en") == "Месяц"


def test_nothing_to_pick() -> None:
    assert pick(None, "ru") is None
    assert pick({}, "ru") is None
    assert pick({"de": "Monat"}, "ru") is None
