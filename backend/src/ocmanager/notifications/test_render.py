from typing import Any

import pytest

from ocmanager.notifications import render

# Образец payload на каждый шаблон. Новый шаблон без образца роняет
# test_every_template_has_a_sample: так забытое поле находит тест, а не прод.
SAMPLES: dict[str, dict[str, Any]] = {
    "payment_accepted": {"amount": "199.00 RUB", "plan": "Месяц", "expires": "01.11.2026"},
    "device_issued": {"device": "iPhone"},
    "expiring_soon": {"days": 3, "expires": "05.10.2026"},
    "expired": {},
    "device_revoked": {"device": "iPhone"},
    "trial_started": {"days": 3, "expires": "05.10.2026"},
    "node_down": {"node": "local", "state": "offline"},
    "node_up": {"node": "local"},
    "webhook_dead": {"provider": "tribute", "id": 7, "reason": "no plan"},
    "webhook_bad_signature": {"provider": "tribute", "id": 8},
    "payment_new": {"amount": "199.00 RUB", "client": "@anna (5001)", "plan": "Месяц"},
    "payment_blocked_client": {"amount": "199.00 RUB", "client": "@anna (5001)"},
    "refund": {"amount": "199.00 RUB", "client": "@anna (5001)"},
    "internal_stuck": {"count": 2},
    "bot_start": {"name": "Anna"},
    "bot_hint": {},
    "bot_whoami": {"chat_id": 42},
    "bot_open_app": {},
}


def test_ru_and_en_have_the_same_keys() -> None:
    assert render.keys("ru") == render.keys("en")


def test_every_template_has_a_sample() -> None:
    assert set(SAMPLES) == render.keys("ru")


@pytest.mark.parametrize("lang", render.LANGS)
@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_every_template_renders_with_exactly_its_sample(key: str, lang: str) -> None:
    text = render.render(key, lang, SAMPLES[key])
    assert text.strip()
    assert "{" not in text
    # Образец — ровно те поля, что нужны шаблону: ни лишнего, ни недостающего.
    assert render.placeholders(key, lang) == set(SAMPLES[key])


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_both_languages_use_the_same_placeholders(key: str) -> None:
    assert render.placeholders(key, "ru") == render.placeholders(key, "en")


def test_a_missing_payload_key_is_an_error_naming_it() -> None:
    with pytest.raises(render.TemplateError, match="expires"):
        render.render("trial_started", "ru", {"days": 3})


def test_an_extra_payload_key_is_ignored() -> None:
    assert render.render("node_up", "en", {"node": "local", "spare": 1}).strip()


def test_braces_in_values_are_not_interpreted() -> None:
    text = render.render("bot_start", "ru", {"name": "{chat_id} {0}"})
    assert "{chat_id} {0}" in text


def test_unknown_template_or_language_is_an_error() -> None:
    with pytest.raises(render.TemplateError, match="no_such_key"):
        render.render("no_such_key", "ru", {})
    with pytest.raises(render.TemplateError, match="de"):
        render.render("expired", "de", {})
