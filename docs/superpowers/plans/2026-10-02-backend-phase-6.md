# Бэкенд ocmanager — Фаза 6 «Уведомления и бот»: пошаговый план

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ САБ-СКИЛЛ — используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения плана задача за задачей.
> Шаги размечены чекбоксами (`- [ ]`) для отслеживания прогресса.
>
> **Этот план исполняется вручную:** код из каждого шага набирается руками,
> Claude проверяет результат по команде («проверь задачу 6.N»).

**Дата:** 2026-10-02
**Основание:** [дорожная карта бэкенда](2026-09-22-backend-implementation.md) (Фаза 6,
Global Constraints, таблица решений) · [план Фазы 5](2026-09-30-backend-phase-5.md) (события платежей) ·
[план Фазы 4](2026-09-30-backend-phase-4.md) (события устройств) ·
[SaaS-дизайн](../specs/2026-09-02-ocmanager-saas-design.md) §10 (уведомления) ·
[стек и структура](../specs/2026-09-02-ocmanager-stack-and-structure.md)

**Goal:** Клиенты получают сообщения о ключевых событиях (оплата, ключ выдан, подписка заканчивается и
закончилась, устройство отозвано, пробный период), админ — алерты в Telegram (нода упала и вернулась, оплата,
возврат, вебхук не обработан или с неверной подписью, застрявшие события). Ни одно сообщение не теряется из-за
лимитов и сбоев Telegram API и не уходит дважды. Бот открывает Mini App и подсказывает админу его `chat_id`.

**Architecture:** Новый домен `notifications` (импортирует только `core` и `events`): таблица
`outbox_messages`, `enqueue()` с дедупликацией, шаблоны ru/en, клиент Bot API и задача доставки. Склейка
«событие → кому и что отправить» живёт в `flows/notify.py` (читает клиентов, платежи, ноды) и подписывается на
шину так же, как `flows/handlers.py`. Обработчики **только кладут** сообщения в `outbox_messages` в транзакции
доставки события; отправляет их cron воркера (`send_outbox`, каждые 5 с) — по одному сообщению в транзакции, с
учётом лимитов Telegram. Бот — отдельный процесс на aiogram 3 (long polling), сам ничего не рассылает: рестарт
бота не теряет уведомления.

**Tech Stack:** Python 3.12 · SQLAlchemy 2 async · Alembic · arq · httpx · **aiogram 3 (новая зависимость)** ·
pytest (`httpx.MockTransport` вместо respx — новых dev-зависимостей нет).

---

## Статус проверки — прочтите перед началом

Как и план Фазы 5, **этот план не прогонялся по задачам на чистой копии**: код написан по фактическим сигнатурам
из репозитория на коммите `0a4420f` (прочитаны `events/bus.py`, `events/types.py`, `flows/handlers.py`,
`flows/purchase.py`, `apps/worker.py`, `core/settings_store.py`, `nodes/service.py`, `conftest.py` и
фикстуры тестов), но `make check` на нём не запускался. Поэтому:

- перед `make check` всегда `make fmt` — он расставляет импорты и форматирует;
- если тест или `mypy` краснеет не так, как написано в шаге «Ожидается», — **пришлите вывод**, исправим план и
  код вместе; не подгоняйте тесты молча;
- Задача 6.6 (бот) опирается на API aiogram 3, который я не сверял с установленной версией: если имя или
  сигнатура не совпали — пришлите ошибку, поправим по актуальной документации.

---

## Global Constraints

Действуют **все** пункты Global Constraints [дорожной карты](2026-09-22-backend-implementation.md#global-constraints).
Для Фазы 6 ключевые из них:

- В конце каждой задачи зелёный `make check` (ruff, ruff format, mypy --strict, границы модулей, pytest).
- TDD: тест пишется первым, запускается и наблюдается падающим.
- **Границы модулей:** `notifications` импортирует только `core` и `events`. Клиентов, платежи, ноды и
  подписки читает `flows/notify.py`. Проверяется `make boundaries`.
- **Время — только `core/clock.utcnow()`**; в БД `timestamptz`.
- **Деньги — целые числа в минорных единицах**; в текст сообщения сумма форматируется целочисленно (без `float`).
- **Секреты не попадают в логи:** токен бота лежит в URL запроса к Telegram (`/bot<token>/sendMessage`) —
  его не должно быть ни в логах, ни в `last_error`, ни в аудите. Проверяется тестом (Задача 6.4).
- **Обработчики событий идемпотентны и не делают commit/rollback** (контракт `events/bus.py`).
- **Обработчик событий не ходит в сеть.** Сеть — только в задаче доставки: упавший Telegram не должен
  откатывать доставку доменного события и ретраить его.
- **Все сообщения — простой текст** (без `parse_mode`): имя клиента и название тарифа подставляются как есть,
  экранировать нечего.
- Коммит в конце каждой задачи: `feat(backend): …` / `test(backend): …` / `chore(backend): …`.
  Файлы в `docs/` — через `git add -f`.

---

## Review Focus

Входы, которые спека подразумевает, но которые не очевидны из описания задач и больше всего угрожают человеку,
пользующемуся сервисом. Ожидаемое поведение и тест, который его закрепляет:

1. **Одно событие доходит до обработчика дважды или одна оплата порождает два события.** Ожидается: клиент и
   каждый админ получают одно сообщение. *Тесты:* `test_the_same_payment_event_twice_queues_one_message`,
   `test_enqueue_with_the_same_dedupe_key_for_the_same_chat_is_a_duplicate`.
2. **Telegram просит притормозить (429), бот заблокирован пользователем (403), Telegram лежит (5xx).**
   Ожидается: 429 переносит отправку и останавливает пачку, не сжигая попыток; 403 — `undeliverable` без
   повторов; 5xx — нарастающая пауза и после 10 попыток `failed`; остальные сообщения не страдают.
   *Тесты:* `test_429_reschedules_by_retry_after_and_stops_the_batch`, `test_403_is_undeliverable_and_never_retried`,
   `test_a_server_error_backs_off_and_the_tenth_failure_is_final`, `test_an_unrenderable_message_fails_without_blocking_the_queue`.
3. **Кто-то флудит подделанными вебхуками** (Фаза 5 пишет их до 30 в минуту). Ожидается: админ получает не
   больше одного алерта в час на провайдера, а не 30 в минуту. *Тест:* `test_bad_signature_alerts_are_throttled_to_one_per_hour`.
4. **Напоминание об истечении приходит не вовремя:** триал на 3 дня («осталось 3 дня» через час после старта),
   автопродление включено, клиент заблокирован, подписку продлили между истечением и обработкой события.
   Ожидается: ни одного лишнего сообщения. *Тесты:* `test_a_short_trial_skips_the_reminder_longer_than_itself`,
   `test_auto_renewing_subscriptions_get_no_reminder`, `test_a_blocked_client_gets_no_client_messages`,
   `test_expired_is_silent_if_the_subscription_was_renewed_meanwhile`.
5. **В данные, подставляемые в шаблон, попадают фигурные скобки или не хватает ключа.** Ожидается: скобки в
   имени клиента остаются скобками; ошибка шаблона падает в обработчике при постановке в очередь (видно в логах
   и в `event_outbox.last_error`), а не молча при отправке через минуту. *Тесты:*
   `test_braces_in_values_are_not_interpreted`, `test_enqueue_refuses_a_payload_the_template_cannot_render`.

Плюс два входа про ноду: **первый статус ноды (`unknown → online`) не шлёт «нода снова в сети»**, а переход
`degraded → offline` не шлёт второй алерт `node_down` (`test_node_transitions`).

---

## Решения, принятые при детализации

| # | Решение | Почему | Где живёт |
|---|---|---|---|
| П6-1 | **Миграция `0013_outbox_messages`**, а не `0012_outbox` из дорожной карты | `0012` уже занята `checkout_intents` | `alembic/versions/` |
| П6-2 | **Таблица `outbox_messages`, уникальность `(chat_id, dedupe_key)`**, а не одного `dedupe_key` | Алерт админам — это по сообщению на каждый `admin_chat_id` с одним и тем же событием; при уникальном `dedupe_key` второй админ ничего бы не получил. NULL-ключи не конфликтуют (Postgres считает их разными) | `notifications/models.py` |
| П6-3 | **`enqueue()` рендерит шаблон «вхолостую»** | Опечатка в шаблоне или забытый ключ payload падает в обработчике события (видно в `event_outbox`, событие ретраится), а не молча при отправке | `notifications/service.py` |
| П6-4 | **Шаблоны и `render` — Задача 6.1, таблица — 6.2** (в карте было наоборот) | Рендер — чистая функция без БД: быстрый TDD; `enqueue` зависит от `render` | — |
| П6-5 | **`send_pending(sessionmaker, …)`, а не `(session, …)`**; одно сообщение — одна транзакция | Коммит после каждого сообщения: падение процесса между отправкой и записью статуса дублирует максимум одно сообщение, а не пачку. Тот же приём, что в `bus.dispatch_pending` | `notifications/tasks.py` |
| П6-6 | **`attempts` считает только неудачи.** `429` попытку не сжигает и останавливает пачку | Telegram просит паузу всю очередь, а не одно сообщение; десять `429` подряд не должны превратить письмо в `failed` | `notifications/tasks.py` |
| П6-7 | **Напоминания и алерт «застряли события» — в `flows/notify.py`**, а не в `subscriptions/tasks.py` | Такого файла нет, а читать подписки + клиентов + писать в `notifications` может только слой `flows/` | `flows/notify.py` |
| П6-8 | **Молчим:** `ClientBlocked/Unblocked`, `SubscriptionRenewed`, `SubscriptionAutoRenewCancelled`, активацию не-trial; заблокированным клиентам не пишем вовсе | Список шаблонов этапа 1 (спека §10) их не содержит; «оплата принята» уже говорит о продлении. Появятся — добавятся шаблон и обработчик | `flows/notify.py` |
| П6-9 | **`trial_started` определяется по статусу подписки** при обработке `SubscriptionActivated` | Отдельного события «начался trial» нет; активация из trial и из оплаты — одно событие | `flows/notify.py` |
| П6-10 | **Алерты ноды — по переходам:** `node_down`, когда `old ∈ {unknown, online}` и `new ∈ {offline, degraded}`; `node_up`, когда `old ∈ {offline, degraded}` и `new = online` | `unknown → online` при первом старте — не «снова в сети»; `degraded → offline` — тот же сбой, второй алерт не нужен. Флаппинг online↔degraded алертит каждый переход — это настоящий сигнал | `flows/notify.py` |
| П6-11 | **Алерт `webhook_bad_signature` — не чаще раза в час на провайдера** (`dedupe_key` с часовым «ведром») | Иначе флуд из Фазы 5 превращается во флуд админу | `flows/notify.py` |
| П6-12 | **`chat_id` клиента = `clients.telegram_id`** | Личный чат с ботом имеет id пользователя | `flows/notify.py` |
| П6-13 | **Известный дубль:** оплата заблокированного клиента даёт два алерта (`payment_blocked_client` и `webhook_dead`) | Это два события Фазы 5 об одном происшествии; склеивать по тексту `last_error` хрупко. Принято: лучше два алерта, чем ноль | — |
| П6-14 | **Кнопка Mini App — только при `https://` в `public_base_url`** | Telegram отвергает `web_app` с http-адресом (`BUTTON_URL_INVALID`) и всё сообщение не уходит; в dev бот должен работать без туннеля | `apps/bot.py` |
| П6-15 | **Уведомления не пишутся в `audit_log`** | Аудит фиксирует изменения доступа и денег; письмо — следствие, а не изменение. Сама очередь — журнал с `status`, `attempts`, `last_error` | — |
| П6-16 | **Суммы форматируются через `//` и `%`**, без дробных типов; валюты с нулём знаков после запятой (JPY) не поддержаны | Тарифы этапа 1 — RUB/EUR/USD | `flows/notify.py: money` |

### Отложено (не входит в фазу)

- Очистка `outbox_messages` от старых `sent` — по образцу `purge_event_outbox`, когда таблица вырастет.
- Клиентские сообщения «автопродление выключено» / «подписка продлена» — см. П6-8.
- Шаблоны на других языках — `clients.lang` ограничен `ru`/`en` (CHECK в БД).

---

## Карта файлов

```
backend/
├── alembic/versions/0013_outbox_messages.py                  (6.2, автогенерация)
├── pyproject.toml  uv.lock                                   (6.6: aiogram)
├── Makefile                                                  (6.6: цель bot)
└── src/ocmanager/
    ├── models.py                                             (6.2: реестр)
    ├── notifications/
    │   ├── __init__.py                                       (6.1)
    │   ├── render.py  test_render.py                         (6.1)
    │   ├── templates/ru.json  templates/en.json              (6.1)
    │   ├── models.py  service.py  test_service.py            (6.2)
    │   ├── telegram.py  test_telegram.py                     (6.4)
    │   └── tasks.py  test_tasks.py                           (6.4)
    ├── flows/
    │   ├── notify.py  test_notify.py                         (6.3; 6.5 дописывает)
    │   └── test_notify_schedule.py                           (6.5)
    └── apps/
        ├── worker.py  test_worker.py  test_entrypoints.py    (6.3, 6.4, 6.5, 6.6)
        └── bot.py  test_bot.py                               (6.6)
```

---

### Задача 6.1: Шаблоны ru/en и `render`

**Files:**
- Create: `backend/src/ocmanager/notifications/__init__.py` (пустой)
- Create: `backend/src/ocmanager/notifications/render.py`
- Create: `backend/src/ocmanager/notifications/templates/ru.json`, `en.json`
- Test: `backend/src/ocmanager/notifications/test_render.py`

**Interfaces:**
- Produces:

```python
LANGS = ("ru", "en")
class TemplateError(Exception): ...
def keys(lang: str) -> frozenset[str]: ...
def placeholders(template_key: str, lang: str) -> frozenset[str]: ...
def render(template_key: str, lang: str, payload: Mapping[str, Any]) -> str: ...
```

Ключи шаблонов — контракт для остальных задач (имена не менять):

| Ключ | Кому | Плейсхолдеры |
|---|---|---|
| `payment_accepted` | клиент | `amount`, `plan`, `expires` |
| `device_issued` | клиент | `device` |
| `expiring_soon` | клиент | `days`, `expires` |
| `expired` | клиент | — |
| `device_revoked` | клиент | `device` |
| `trial_started` | клиент | `days`, `expires` |
| `node_down` | админ | `node`, `state` |
| `node_up` | админ | `node` |
| `webhook_dead` | админ | `provider`, `id`, `reason` |
| `webhook_bad_signature` | админ | `provider`, `id` |
| `payment_new` | админ | `amount`, `client`, `plan` |
| `payment_blocked_client` | админ | `amount`, `client` |
| `refund` | админ | `amount`, `client` |
| `internal_stuck` | админ | `count` |
| `bot_start` | бот | `name` |
| `bot_hint` | бот | — |
| `bot_whoami` | бот | `chat_id` |
| `bot_open_app` | бот | — (подпись кнопки) |

- [ ] **Шаг 1: Пустой пакет**

```bash
cd backend
mkdir -p src/ocmanager/notifications/templates
touch src/ocmanager/notifications/__init__.py
```

- [ ] **Шаг 2: Тест `notifications/test_render.py`**

```python
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
```

- [ ] **Шаг 3: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/notifications/test_render.py -v
```
Ожидается: ошибка сбора — `ImportError: cannot import name 'render'`.

- [ ] **Шаг 4: Шаблоны `notifications/templates/ru.json`**

```json
{
  "payment_accepted": "Оплата {amount} получена. Подписка «{plan}» действует до {expires}.",
  "device_issued": "Ключ для устройства «{device}» выпущен. Скачать его повторно нельзя — если потеряете, выпустите устройство заново.",
  "expiring_soon": "Подписка заканчивается через {days} дн. ({expires}). Продлите её в приложении, чтобы VPN не отключился.",
  "expired": "Подписка закончилась, доступ закрыт. Откройте приложение, чтобы продлить.",
  "device_revoked": "Устройство «{device}» отозвано: доступ с него закрыт.",
  "trial_started": "Пробный период начался: {days} дн., до {expires}. Откройте приложение и добавьте устройство.",
  "node_down": "⚠️ Нода «{node}» недоступна ({state}).",
  "node_up": "✅ Нода «{node}» снова в сети.",
  "webhook_dead": "⚠️ Вебхук {provider} #{id} не обработан: {reason}. Разберите его в разделе «Платежи».",
  "webhook_bad_signature": "⚠️ Вебхук {provider} #{id} пришёл с неверной подписью. Если вы не проверяли интеграцию сами — проверьте ключ API.",
  "payment_new": "💰 Новая оплата {amount}: {client}, тариф «{plan}».",
  "payment_blocked_client": "⚠️ Оплата {amount} от заблокированного клиента {client} записана, доступ не выдан. Разблокируйте клиента и переобработайте вебхук или верните деньги.",
  "refund": "↩️ Возврат {amount}: {client}. Доступ не отключён — решите вручную.",
  "internal_stuck": "⚠️ Внутренних событий, застрявших после 10 попыток: {count}. Смотрите логи воркера.",
  "bot_start": "Привет, {name}! Здесь можно оформить подписку на VPN, выпускать ключи для устройств и следить за трафиком — всё в приложении.",
  "bot_hint": "Всё управление — в приложении. Нажмите кнопку ниже.",
  "bot_whoami": "Ваш chat_id: {chat_id}. Чтобы получать алерты, добавьте это число в admin_chat_ids в настройках панели.",
  "bot_open_app": "Открыть приложение"
}
```

- [ ] **Шаг 5: Шаблоны `notifications/templates/en.json`**

```json
{
  "payment_accepted": "Payment of {amount} received. Your “{plan}” subscription is valid until {expires}.",
  "device_issued": "The key for “{device}” has been issued. It cannot be downloaded again — if you lose it, issue the device anew.",
  "expiring_soon": "Your subscription ends in {days} d ({expires}). Renew it in the app so the VPN stays on.",
  "expired": "Your subscription has ended and access is closed. Open the app to renew.",
  "device_revoked": "Device “{device}” was revoked: its access is closed.",
  "trial_started": "Your trial has started: {days} d, until {expires}. Open the app and add a device.",
  "node_down": "⚠️ Node “{node}” is unavailable ({state}).",
  "node_up": "✅ Node “{node}” is back online.",
  "webhook_dead": "⚠️ Webhook {provider} #{id} was not processed: {reason}. Review it in the Payments section.",
  "webhook_bad_signature": "⚠️ Webhook {provider} #{id} arrived with a bad signature. If you were not testing the integration yourself, check the API key.",
  "payment_new": "💰 New payment {amount}: {client}, plan “{plan}”.",
  "payment_blocked_client": "⚠️ Payment {amount} from blocked client {client} was recorded, access was not granted. Unblock the client and reprocess the webhook, or refund.",
  "refund": "↩️ Refund {amount}: {client}. Access was not revoked — decide manually.",
  "internal_stuck": "⚠️ Internal events stuck after 10 attempts: {count}. Check the worker logs.",
  "bot_start": "Hi, {name}! Here you can buy a VPN subscription, issue keys for your devices and watch your traffic — all in the app.",
  "bot_hint": "Everything is managed in the app. Tap the button below.",
  "bot_whoami": "Your chat_id: {chat_id}. To receive alerts, add this number to admin_chat_ids in the panel settings.",
  "bot_open_app": "Open the app"
}
```

- [ ] **Шаг 6: Реализация `notifications/render.py`**

```python
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
```

- [ ] **Шаг 7: Запустить — PASS**

```bash
uv run pytest src/ocmanager/notifications/test_render.py -v
```
Ожидается: все тесты зелёные (параметризованных — по 18 × 2 + мелкие).

- [ ] **Шаг 8: Проверка и коммит**

```bash
make fmt && make check
git add src/ocmanager/notifications
git commit -m "feat(backend): ru/en notification templates and a strict renderer"
```

---

### Задача 6.2: Таблица `outbox_messages` и `enqueue`

**Files:**
- Create: `backend/src/ocmanager/notifications/models.py`, `service.py`, `test_service.py`
- Modify: `backend/src/ocmanager/models.py` (реестр)
- Create: `backend/alembic/versions/0013_outbox_messages.py` (автогенерация)

**Interfaces:**
- Consumes: `render.render`, `render.TemplateError` (6.1).
- Produces:

```python
class OutboxMessage(Base):  # таблица outbox_messages
    id: int; recipient_type: str          # client | admin
    chat_id: int; template_key: str; lang: str; payload: dict[str, Any]
    dedupe_key: str | None
    status: str                           # pending | sent | failed | undeliverable
    attempts: int                         # только неудачные попытки
    created_at: datetime; send_after: datetime
    sent_at: datetime | None; last_error: str | None

async def enqueue(
    session: AsyncSession, *,
    recipient_type: Literal["client", "admin"], chat_id: int,
    template_key: str, lang: str, payload: Mapping[str, Any],
    dedupe_key: str | None = None, send_after: datetime | None = None,
) -> bool: ...   # False — дубль (тот же chat_id и dedupe_key)
```

- [ ] **Шаг 1: Модель `notifications/models.py`**

```python
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ocmanager.core.db import Base

RECIPIENT_TYPES = ("client", "admin")
MESSAGE_STATUSES = ("pending", "sent", "failed", "undeliverable")


class OutboxMessage(Base):
    """Исходящее сообщение в Telegram. Кладётся обработчиками событий в транзакции доставки
    события, отправляется задачей воркера (tasks.py): сбой Telegram не откатывает доменные события."""

    __tablename__ = "outbox_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_type: Mapped[str]
    chat_id: Mapped[int] = mapped_column(BigInteger)
    template_key: Mapped[str]
    lang: Mapped[str]
    payload: Mapped[dict[str, Any]]
    # Защита от дублей: событие, дошедшее до обработчика дважды, не шлёт второе сообщение.
    # Уникален в паре с chat_id (П6-2): один алерт — по сообщению на каждого админа.
    dedupe_key: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default=text("0"), default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    send_after: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    last_error: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint("chat_id", "dedupe_key", name="uq_outbox_messages_chat_id_dedupe_key"),
        CheckConstraint(
            "recipient_type IN ('" + "', '".join(RECIPIENT_TYPES) + "')", name="recipient_type"
        ),
        CheckConstraint("status IN ('" + "', '".join(MESSAGE_STATUSES) + "')", name="status"),
        CheckConstraint("lang IN ('ru', 'en')", name="lang"),
        # Доставка ищет только ждущие сообщения — индекс остаётся маленьким.
        Index(
            "ix_outbox_messages_pending",
            "send_after",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
    )
```

- [ ] **Шаг 2: Реестр моделей.** В `src/ocmanager/models.py` добавьте строку между `_nodes` и `_provisioning`
  (порядок алфавитный, ruff `I` проверит):

```python
from ocmanager.notifications import models as _notifications  # noqa: F401
```

- [ ] **Шаг 3: Миграция.** Dev-база должна быть на `0012`:

```bash
make dev-up && make migrate
make revision id=0013 m=outbox_messages
```

Откройте `alembic/versions/0013_outbox_messages.py` и убедитесь: `down_revision = "0012"`, в `upgrade()` —
`create_table("outbox_messages", …)` с тремя `CheckConstraint`, `UniqueConstraint` с именем
`uq_outbox_messages_chat_id_dedupe_key`, `postgresql.JSONB` для `payload`, и `create_index` с
`postgresql_where=sa.text("status = 'pending'")`; в `downgrade()` — `drop_index` и `drop_table`. Затем:

```bash
make migrate
uv run pytest src/ocmanager/test_migrations.py src/ocmanager/test_models.py -v
```
Ожидается: PASS (миграции совпадают с моделями, реестр полный).

- [ ] **Шаг 4: Тест `notifications/test_service.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import TemplateError
from ocmanager.notifications.service import enqueue

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


async def queue(session: AsyncSession, **over: Any) -> bool:
    fields: dict[str, Any] = {
        "recipient_type": "client",
        "chat_id": 42,
        "template_key": "expired",
        "lang": "ru",
        "payload": {},
    } | over
    return await enqueue(session, **fields)


async def count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(OutboxMessage)) or 0


async def test_enqueue_stores_a_pending_message(session: AsyncSession) -> None:
    with time_machine.travel(NOW, tick=False):
        assert await queue(session, template_key="device_issued", payload={"device": "iPhone"})
    [row] = (await session.scalars(select(OutboxMessage))).all()
    assert (row.recipient_type, row.chat_id, row.template_key, row.lang) == (
        "client",
        42,
        "device_issued",
        "ru",
    )
    assert row.payload == {"device": "iPhone"}
    assert (row.status, row.attempts, row.sent_at, row.last_error) == ("pending", 0, None, None)
    assert row.send_after == NOW


async def test_send_after_can_be_postponed(session: AsyncSession) -> None:
    later = NOW + timedelta(hours=2)
    await queue(session, send_after=later)
    [row] = (await session.scalars(select(OutboxMessage))).all()
    assert row.send_after == later


async def test_enqueue_with_the_same_dedupe_key_for_the_same_chat_is_a_duplicate(
    session: AsyncSession,
) -> None:
    assert await queue(session, dedupe_key="expired:client:1") is True
    assert await queue(session, dedupe_key="expired:client:1") is False
    assert await count(session) == 1


async def test_the_same_dedupe_key_for_another_chat_is_not_a_duplicate(
    session: AsyncSession,
) -> None:
    assert await queue(session, chat_id=1, dedupe_key="node_down:1") is True
    assert await queue(session, chat_id=2, dedupe_key="node_down:1") is True
    assert await count(session) == 2


async def test_messages_without_a_dedupe_key_never_collide(session: AsyncSession) -> None:
    assert await queue(session) is True
    assert await queue(session) is True
    assert await count(session) == 2


async def test_enqueue_refuses_a_payload_the_template_cannot_render(
    session: AsyncSession,
) -> None:
    with pytest.raises(TemplateError, match="device"):
        await queue(session, template_key="device_issued", payload={})
    assert await count(session) == 0


async def test_enqueue_refuses_an_unknown_template_or_language(session: AsyncSession) -> None:
    with pytest.raises(TemplateError):
        await queue(session, template_key="nope")
    with pytest.raises(TemplateError):
        await queue(session, lang="de")
    assert await count(session) == 0
```

- [ ] **Шаг 5: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/notifications/test_service.py -v
```
Ожидается: `ModuleNotFoundError: ... notifications.service`.

- [ ] **Шаг 6: Реализация `notifications/service.py`**

```python
"""Очередь исходящих уведомлений. enqueue() кладёт сообщение в outbox_messages в транзакции
вызывающего (commit — у него); отправляет сообщения воркер (tasks.py)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core.clock import utcnow
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import render


async def enqueue(
    session: AsyncSession,
    *,
    recipient_type: Literal["client", "admin"],
    chat_id: int,
    template_key: str,
    lang: str,
    payload: Mapping[str, Any],
    dedupe_key: str | None = None,
    send_after: datetime | None = None,
) -> bool:
    """False — такое сообщение уже в очереди (тот же chat_id и dedupe_key).

    Шаблон рендерится вхолостую: ошибка в шаблоне или payload падает здесь, в обработчике
    события (оно уйдёт на повтор и будет видно в event_outbox), а не при отправке."""
    render(template_key, lang, payload)
    stmt = (
        insert(OutboxMessage)
        .values(
            recipient_type=recipient_type,
            chat_id=chat_id,
            template_key=template_key,
            lang=lang,
            payload=dict(payload),
            dedupe_key=dedupe_key,
            send_after=send_after or utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_outbox_messages_chat_id_dedupe_key")
        .returning(OutboxMessage.id)
    )
    return await session.scalar(stmt) is not None
```

- [ ] **Шаг 7: Запустить — PASS**

```bash
uv run pytest src/ocmanager/notifications/test_service.py -v
```

- [ ] **Шаг 8: Проверка и коммит**

```bash
make fmt && make check
git add src/ocmanager/notifications src/ocmanager/models.py alembic/versions/0013_outbox_messages.py
git commit -m "feat(backend): notification outbox table with dedupe-aware enqueue"
```

---

### Задача 6.3: События → сообщения (`flows/notify.py`)

**Files:**
- Create: `backend/src/ocmanager/flows/notify.py`, `backend/src/ocmanager/flows/test_notify.py`
- Modify: `backend/src/ocmanager/apps/worker.py` (регистрация в `startup`), `backend/src/ocmanager/apps/test_worker.py`

**Interfaces:**
- Consumes: `notifications.service.enqueue` (6.2); `settings_store.load(session) -> RuntimeSettings`
  (`admin_chat_ids`, `default_lang`); `bus.on`; события из `events/types.py`;
  `subscriptions.service.get_subscription(session, client_id) -> Subscription | None`.
- Produces:

```python
def register() -> None                                   # вызывается один раз в startup воркера
def money(amount: int, currency: str) -> str             # 19900, "RUB" → "199.00 RUB"
def day(moment: datetime) -> str                         # → "01.11.2026" (UTC)
def who(client: Client) -> str                           # → "@anna (5001)" или "Anna (5001)"
async def to_client(session, client_id, template_key, payload, *, dedupe_key) -> bool
async def to_admins(session, template_key, payload, *, dedupe_key=None) -> int
```

Кто что получает (из спеки §10 и П6-8…П6-13):

| Событие | Клиент | Админ | `dedupe_key` |
|---|---|---|---|
| `SubscriptionActivated` (статус `trial`) | `trial_started` | — | `trial_started:client:{id}` |
| `PaymentReceived` | `payment_accepted` | `payment_new` | `…:payment:{id}` |
| `PaymentRefunded` | — | `refund` | `refund:payment:{id}` |
| `PaymentNeedsReview` | — | `payment_blocked_client` | `needs_review:payment:{id}` |
| `WebhookDeadLettered` | — | `webhook_dead` | `webhook_dead:{id}` |
| `WebhookRejected` | — | `webhook_bad_signature` | `bad_signature:{provider}:{ГГГГММДДЧЧ}` |
| `NodeStatusChanged` | — | `node_down` / `node_up` | нет (по переходам, П6-10) |
| `DeviceIssued` | `device_issued` | — | `device_issued:device:{id}` |
| `DeviceRevoked` | `device_revoked` | — | `device_revoked:device:{id}` |
| `SubscriptionExpired` (подписка не живая) | `expired` | — | `expired:client:{id}:{expires_at}` |

- [ ] **Шаг 1: Тест `flows/test_notify.py`**

```python
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from conftest import MakeClient, MakeDevice, MakePayment, MakePlan, MakeSubscription, MakeWebhook
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core import settings_store
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.events.types import (
    DeviceIssued,
    DeviceRevoked,
    DomainEvent,
    NodeStatusChanged,
    PaymentNeedsReview,
    PaymentReceived,
    PaymentRefunded,
    SubscriptionActivated,
    SubscriptionExpired,
    WebhookDeadLettered,
    WebhookRejected,
)
from ocmanager.flows import notify
from ocmanager.nodes.models import Node
from ocmanager.notifications.models import OutboxMessage

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture(autouse=True)
def _notify_handlers(_isolated_event_handlers: None) -> None:
    """Зависимость от фикстуры conftest гарантирует порядок: сначала снимок реестра шины,
    потом наша регистрация — и она не утечёт в соседние тесты."""
    notify.register()


async def deliver(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], event: DomainEvent
) -> None:
    # События, порождённые подготовкой данных (activate и т. п.), не предмет теста.
    await session.execute(delete(EventOutbox))
    await bus.record(session, event)
    await session.commit()
    assert await bus.dispatch_pending(sessionmaker) == 1  # 0 — обработчик упал


async def queued(session: AsyncSession) -> list[tuple[str, int, str, str]]:
    rows = await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))
    return [(m.recipient_type, m.chat_id, m.template_key, m.lang) for m in rows]


async def messages(session: AsyncSession) -> list[OutboxMessage]:
    return list(await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


async def set_admins(session: AsyncSession, *chat_ids: int) -> None:
    await settings_store.update(session, {"admin_chat_ids": list(chat_ids)})


def test_money_is_formatted_without_floats() -> None:
    assert notify.money(19900, "RUB") == "199.00 RUB"
    assert notify.money(5, "USD") == "0.05 USD"
    assert notify.money(0, "EUR") == "0.00 EUR"


def test_day_is_utc_date() -> None:
    assert notify.day(datetime(2026, 11, 1, 23, 30, tzinfo=UTC)) == "01.11.2026"


# --- платежи -----------------------------------------------------------------


async def test_a_payment_notifies_the_client_and_every_admin(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client(username="anna", language_code="ru")
    plan = await make_plan(name_i18n={"ru": "Месяц", "en": "Month"})
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client, plan_id=plan.id, amount=19900)
    await set_admins(session, 111, 222)

    await deliver(session, sessionmaker, PaymentReceived(payment_id=payment.id, client_id=client.id))

    assert await queued(session) == [
        ("client", client.telegram_id, "payment_accepted", "ru"),
        ("admin", 111, "payment_new", "ru"),
        ("admin", 222, "payment_new", "ru"),
    ]
    first, second, _ = await messages(session)
    assert first.payload == {"amount": "199.00 RUB", "plan": "Месяц", "expires": "01.11.2026"}
    assert second.payload == {
        "amount": "199.00 RUB",
        "client": f"@anna ({client.telegram_id})",
        "plan": "Месяц",
    }


async def test_the_same_payment_event_twice_queues_one_message(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)
    await set_admins(session, 111)
    event = PaymentReceived(payment_id=payment.id, client_id=client.id)

    await deliver(session, sessionmaker, event)
    await deliver(session, sessionmaker, event)

    assert len(await queued(session)) == 2  # клиенту одно и админу одно, а не по два


async def test_an_english_client_gets_english_and_the_english_plan_name(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_plan: MakePlan,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client(language_code="en")
    plan = await make_plan(name_i18n={"ru": "Месяц", "en": "Month"})
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client, plan_id=plan.id)

    await deliver(session, sessionmaker, PaymentReceived(payment_id=payment.id, client_id=client.id))

    [message] = await messages(session)  # админов не настроено — только клиент
    assert (message.template_key, message.lang) == ("payment_accepted", "en")
    assert message.payload["plan"] == "Month"


async def test_a_payment_without_a_plan_shows_a_dash(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)  # plan_id=None

    await deliver(session, sessionmaker, PaymentReceived(payment_id=payment.id, client_id=client.id))

    [message] = await messages(session)
    assert message.payload["plan"] == "—"


async def test_a_blocked_client_gets_no_client_messages_but_admins_still_hear(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)
    payment = await make_payment(client)
    client.is_blocked = True
    await session.flush()
    await set_admins(session, 111)

    await deliver(session, sessionmaker, PaymentReceived(payment_id=payment.id, client_id=client.id))

    assert await queued(session) == [("admin", 111, "payment_new", "ru")]


async def test_a_refund_and_a_blocked_payment_alert_the_admins_only(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_payment: MakePayment,
) -> None:
    client = await make_client()
    payment = await make_payment(client, amount=500, currency="USD")
    await set_admins(session, 111)

    await deliver(session, sessionmaker, PaymentRefunded(payment_id=payment.id, client_id=client.id))
    await deliver(
        session, sessionmaker, PaymentNeedsReview(payment_id=payment.id, client_id=client.id)
    )

    assert await queued(session) == [
        ("admin", 111, "refund", "ru"),
        ("admin", 111, "payment_blocked_client", "ru"),
    ]
    refund, _ = await messages(session)
    assert refund.payload["amount"] == "5.00 USD"


# --- вебхуки -----------------------------------------------------------------


async def test_a_dead_webhook_alerts_the_admins_with_the_reason(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_webhook: MakeWebhook,
) -> None:
    webhook = await make_webhook(status="dead", last_error="no plan for product 7")
    await set_admins(session, 111)

    await deliver(session, sessionmaker, WebhookDeadLettered(webhook_event_id=webhook.id))

    [message] = await messages(session)
    assert message.template_key == "webhook_dead"
    assert message.payload == {
        "provider": "tribute",
        "id": webhook.id,
        "reason": "no plan for product 7",
    }


async def test_bad_signature_alerts_are_throttled_to_one_per_hour(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_webhook: MakeWebhook,
) -> None:
    first = await make_webhook(status="rejected", signature_ok=False)
    second = await make_webhook(status="rejected", signature_ok=False)
    await set_admins(session, 111, 222)

    await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=first.id))
    await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=second.id))
    assert len(await queued(session)) == 2  # по одному на админа, не по два

    with time_machine.travel(NOW + timedelta(hours=1), tick=False):
        await deliver(session, sessionmaker, WebhookRejected(webhook_event_id=second.id))
    assert len(await queued(session)) == 4


# --- нода --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("online", "offline", "node_down"),
        ("online", "degraded", "node_down"),
        ("unknown", "offline", "node_down"),
        ("offline", "online", "node_up"),
        ("degraded", "online", "node_up"),
        ("degraded", "offline", None),
        ("offline", "degraded", None),
        ("unknown", "online", None),
    ],
)
async def test_node_transitions(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    old: str,
    new: str,
    expected: str | None,
) -> None:
    node = Node(name="local", driver="local_docker", public_host="vpn.example.com")
    session.add(node)
    await session.flush()
    await set_admins(session, 111)

    await deliver(session, sessionmaker, NodeStatusChanged(node_id=node.id, old=old, new=new))

    sent = await messages(session)
    if expected is None:
        assert sent == []
    else:
        [message] = sent
        assert message.template_key == expected
        assert message.payload["node"] == "local"


# --- устройства и подписка ---------------------------------------------------


async def test_device_events_notify_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_device: MakeDevice,
) -> None:
    client = await make_client()
    device = await make_device(client, seq=1)

    await deliver(session, sessionmaker, DeviceIssued(client_id=client.id, device_id=device.id))
    await deliver(
        session,
        sessionmaker,
        DeviceRevoked(client_id=client.id, device_id=device.id, username=device.ocserv_username),
    )

    assert await queued(session) == [
        ("client", client.telegram_id, "device_issued", "ru"),
        ("client", client.telegram_id, "device_revoked", "ru"),
    ]
    issued, _ = await messages(session)
    assert issued.payload == {"device": "dev1"}


async def test_a_trial_activation_greets_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, days=3, now=NOW)
    sub.status = "trial"
    await session.flush()

    await deliver(session, sessionmaker, SubscriptionActivated(client_id=client.id))

    [message] = await messages(session)
    assert message.template_key == "trial_started"
    assert message.payload == {"days": 3, "expires": "05.10.2026"}


async def test_a_paid_activation_is_silent(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)  # статус active

    await deliver(session, sessionmaker, SubscriptionActivated(client_id=client.id))

    assert await queued(session) == []  # об оплате расскажет PaymentReceived


async def test_expiry_tells_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    sub = await make_subscription(client, days=30, now=NOW)
    sub.status = "expired"
    await session.flush()

    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))
    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))

    assert await queued(session) == [("client", client.telegram_id, "expired", "ru")]


async def test_expired_is_silent_if_the_subscription_was_renewed_meanwhile(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    client = await make_client()
    await make_subscription(client, days=30, now=NOW)  # живая: событие устарело

    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))

    assert await queued(session) == []


async def test_expired_is_silent_for_a_client_without_a_subscription(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
) -> None:
    client = await make_client()
    await deliver(session, sessionmaker, SubscriptionExpired(client_id=client.id))
    assert await queued(session) == []
```

- [ ] **Шаг 2: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/flows/test_notify.py -v
```
Ожидается: `ImportError: cannot import name 'notify'`.

- [ ] **Шаг 3: Реализация `flows/notify.py`**

```python
"""Склейка notifications + доменные события: что и кому отправить.

Обработчики только кладут сообщения в outbox_messages — в транзакции доставки события,
без сети и без commit. Отправляет их cron воркера (notifications/tasks.py): так упавший
Telegram не откатывает и не ретраит доменное событие.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.billing.models import Payment, Plan, WebhookEvent
from ocmanager.core import settings_store
from ocmanager.core.clock import utcnow
from ocmanager.core.i18n import pick
from ocmanager.events import bus
from ocmanager.events.types import (
    DeviceIssued,
    DeviceRevoked,
    NodeStatusChanged,
    PaymentNeedsReview,
    PaymentReceived,
    PaymentRefunded,
    SubscriptionActivated,
    SubscriptionExpired,
    WebhookDeadLettered,
    WebhookRejected,
)
from ocmanager.nodes.models import Node
from ocmanager.notifications import service as notifications
from ocmanager.provisioning.models import Device
from ocmanager.subscriptions import service as subscriptions
from ocmanager.subscriptions.models import Client
from ocmanager.subscriptions.state import LIVE, Status

DOWN = ("offline", "degraded")
REASON_LIMIT = 300


def money(amount: int, currency: str) -> str:
    """Минорные единицы → «199.00 RUB». Целочисленно: float для денег не используется."""
    return f"{amount // 100}.{amount % 100:02d} {currency}"


def day(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%d.%m.%Y")


def who(client: Client) -> str:
    name = f"@{client.username}" if client.username else client.first_name
    return f"{name} ({client.telegram_id})"


async def to_client(
    session: AsyncSession,
    client_id: int,
    template_key: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str,
) -> bool:
    """Заблокированному клиенту и несуществующему не пишем."""
    client = await session.get(Client, client_id)
    if client is None or client.is_blocked:
        return False
    return await notifications.enqueue(
        session,
        recipient_type="client",
        chat_id=client.telegram_id,
        template_key=template_key,
        lang=client.lang,
        payload=payload,
        dedupe_key=dedupe_key,
    )


async def to_admins(
    session: AsyncSession,
    template_key: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
) -> int:
    """Сообщение каждому из admin_chat_ids на языке по умолчанию. Список пуст — тишина."""
    runtime = await settings_store.load(session)
    queued = 0
    for chat_id in runtime.admin_chat_ids:
        queued += await notifications.enqueue(
            session,
            recipient_type="admin",
            chat_id=chat_id,
            template_key=template_key,
            lang=runtime.default_lang,
            payload=payload,
            dedupe_key=dedupe_key,
        )
    return queued


def register() -> None:
    """Вызывается один раз на процесс воркера, рядом с handlers.register. Явно, а не при
    импорте: иначе любой тест, импортировавший модуль, получил бы боевые обработчики."""

    @bus.on(SubscriptionActivated)
    async def trial_started(event: SubscriptionActivated, session: AsyncSession) -> None:
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is None or sub.status != Status.TRIAL:
            return  # оплаченную активацию объявит PaymentReceived
        await to_client(
            session,
            event.client_id,
            "trial_started",
            {"days": (sub.expires_at - sub.started_at).days, "expires": day(sub.expires_at)},
            dedupe_key=f"trial_started:client:{event.client_id}",
        )

    @bus.on(PaymentReceived)
    async def payment_received(event: PaymentReceived, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        plan = None if payment.plan_id is None else await session.get(Plan, payment.plan_id)
        plan_name = (pick(plan.name_i18n, client.lang) or plan.code) if plan else "—"
        amount = money(payment.amount, payment.currency)
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is not None:
            await to_client(
                session,
                event.client_id,
                "payment_accepted",
                {"amount": amount, "plan": plan_name, "expires": day(sub.expires_at)},
                dedupe_key=f"payment_accepted:payment:{payment.id}",
            )
        await to_admins(
            session,
            "payment_new",
            {"amount": amount, "client": who(client), "plan": plan_name},
            dedupe_key=f"payment_new:payment:{payment.id}",
        )

    @bus.on(PaymentRefunded)
    async def payment_refunded(event: PaymentRefunded, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        await to_admins(
            session,
            "refund",
            {"amount": money(payment.amount, payment.currency), "client": who(client)},
            dedupe_key=f"refund:payment:{payment.id}",
        )

    @bus.on(PaymentNeedsReview)
    async def payment_needs_review(event: PaymentNeedsReview, session: AsyncSession) -> None:
        payment = await session.get(Payment, event.payment_id)
        client = await session.get(Client, event.client_id)
        if payment is None or client is None:
            return
        await to_admins(
            session,
            "payment_blocked_client",
            {"amount": money(payment.amount, payment.currency), "client": who(client)},
            dedupe_key=f"needs_review:payment:{payment.id}",
        )

    @bus.on(WebhookDeadLettered)
    async def webhook_dead(event: WebhookDeadLettered, session: AsyncSession) -> None:
        row = await session.get(WebhookEvent, event.webhook_event_id)
        if row is None:
            return
        await to_admins(
            session,
            "webhook_dead",
            {
                "provider": row.provider,
                "id": row.id,
                "reason": (row.last_error or "—")[:REASON_LIMIT],
            },
            dedupe_key=f"webhook_dead:{row.id}",
        )

    @bus.on(WebhookRejected)
    async def webhook_rejected(event: WebhookRejected, session: AsyncSession) -> None:
        row = await session.get(WebhookEvent, event.webhook_event_id)
        if row is None:
            return
        # Флуд подделанных вебхуков не должен стать флудом админу: один алерт в час на провайдера.
        bucket = utcnow().strftime("%Y%m%d%H")
        await to_admins(
            session,
            "webhook_bad_signature",
            {"provider": row.provider, "id": row.id},
            dedupe_key=f"bad_signature:{row.provider}:{bucket}",
        )

    @bus.on(NodeStatusChanged)
    async def node_status_changed(event: NodeStatusChanged, session: AsyncSession) -> None:
        node = await session.get(Node, event.node_id)
        if node is None:
            return
        if event.new in DOWN and event.old not in DOWN:
            await to_admins(session, "node_down", {"node": node.name, "state": event.new})
        elif event.new == "online" and event.old in DOWN:
            await to_admins(session, "node_up", {"node": node.name})

    @bus.on(DeviceIssued)
    async def device_issued(event: DeviceIssued, session: AsyncSession) -> None:
        device = await session.get(Device, event.device_id)
        if device is None:
            return
        await to_client(
            session,
            event.client_id,
            "device_issued",
            {"device": device.name},
            dedupe_key=f"device_issued:device:{device.id}",
        )

    @bus.on(DeviceRevoked)
    async def device_revoked(event: DeviceRevoked, session: AsyncSession) -> None:
        device = await session.get(Device, event.device_id)
        if device is None:
            return
        await to_client(
            session,
            event.client_id,
            "device_revoked",
            {"device": device.name},
            dedupe_key=f"device_revoked:device:{device.id}",
        )

    @bus.on(SubscriptionExpired)
    async def subscription_expired(event: SubscriptionExpired, session: AsyncSession) -> None:
        sub = await subscriptions.get_subscription(session, event.client_id)
        if sub is None or Status(sub.status) in LIVE:
            return  # продлили, пока событие ждало очереди
        await to_client(
            session,
            event.client_id,
            "expired",
            {},
            dedupe_key=f"expired:client:{event.client_id}:{sub.expires_at.isoformat()}",
        )
```

- [ ] **Шаг 4: Запустить — PASS**

```bash
uv run pytest src/ocmanager/flows/test_notify.py -v
```
Если красный на `test_the_same_payment_event_twice_queues_one_message` — проверьте, что в `enqueue`
используется `on_conflict_do_nothing(constraint=...)` из 6.2.

- [ ] **Шаг 5: Регистрация в воркере.** В `apps/worker.py` добавьте импорт (по алфавиту, после
  `from ocmanager.flows import handlers`):

```python
from ocmanager.flows import notify as notify_flows
```

и в `startup` сразу после `handlers.register(settings)`:

```python
    handlers.register(settings)
    notify_flows.register()
```

- [ ] **Шаг 6: Тест регистрации.** В `apps/test_worker.py` добавьте после `test_startup_and_shutdown`
  (импорт `from ocmanager.events import bus` там уже есть):

```python
async def test_startup_registers_the_notification_handlers(
    settings: Settings, db_engine: object
) -> None:
    ctx: dict[str, Any] = {"settings": settings}
    await startup(ctx)
    for name in ("payment.received", "node.status_changed", "device.issued"):
        assert bus._handlers.get(name), name  # noqa: SLF001 — реестр шины приватный
    await shutdown(ctx)
```

```bash
uv run pytest src/ocmanager/apps/test_worker.py -v
```

- [ ] **Шаг 7: Проверка и коммит**

```bash
make fmt && make check
git add src/ocmanager/flows/notify.py src/ocmanager/flows/test_notify.py src/ocmanager/apps
git commit -m "feat(backend): turn domain events into client and admin notifications"
```

---

### Задача 6.4: Доставка в Telegram с учётом лимитов

**Files:**
- Create: `backend/src/ocmanager/notifications/telegram.py`, `test_telegram.py`, `tasks.py`, `test_tasks.py`
- Modify: `backend/src/ocmanager/apps/worker.py`, `backend/src/ocmanager/apps/test_worker.py`

**Interfaces:**
- Consumes: `OutboxMessage` (6.2), `render.render` (6.1).
- Produces:

```python
class SendOutcome(Enum): SENT; RETRY; UNDELIVERABLE
@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    retry_after: int | None = None     # секунды, только при 429
    error: str | None = None

async def send_message(http: httpx.AsyncClient, bot_token: str, chat_id: int, text: str) -> SendResult
async def send_pending(
    sessionmaker: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, bot_token: str,
    *, batch: int = 50, pause: float = SEND_PAUSE_S,
) -> int          # сколько отправлено
```

Правила ответа Bot API: `200` → `SENT`; `429` + `parameters.retry_after` → `RETRY` с `retry_after`;
`403` и `400 … chat not found` → `UNDELIVERABLE`; всё остальное (5xx, сеть, `401`, прочие `4xx`) → `RETRY` с
нарастающей паузой `min(2^attempts, 600)` с; на десятой неудаче — `failed`.

- [ ] **Шаг 1: Тест `notifications/test_telegram.py`** (без БД)

```python
import json
import logging

import httpx
import pytest

from ocmanager.notifications.telegram import SendOutcome, send_message

TOKEN = "123456:secret-bot-token"


def client(handler: httpx.MockTransport | None = None, **response: object) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(**response)  # type: ignore[arg-type]

    return httpx.AsyncClient(transport=handler or httpx.MockTransport(respond))


async def test_ok_is_sent_and_the_request_has_chat_and_text() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with client(httpx.MockTransport(respond)) as http:
        result = await send_message(http, TOKEN, 42, "Привет")

    assert result.outcome is SendOutcome.SENT
    [request] = seen
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert json.loads(request.content) == {"chat_id": 42, "text": "Привет"}


async def test_429_is_a_retry_with_the_pause_telegram_asked_for() -> None:
    body = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 7",
        "parameters": {"retry_after": 7},
    }
    async with client(status_code=429, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert (result.outcome, result.retry_after) == (SendOutcome.RETRY, 7)


async def test_429_without_a_pause_is_an_ordinary_retry() -> None:
    async with client(status_code=429, json={"ok": False}) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert (result.outcome, result.retry_after) == (SendOutcome.RETRY, None)


async def test_a_blocked_bot_is_undeliverable() -> None:
    body = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
    async with client(status_code=403, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.UNDELIVERABLE
    assert result.error is not None
    assert "blocked" in result.error


async def test_chat_not_found_is_undeliverable() -> None:
    body = {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    async with client(status_code=400, json=body) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.UNDELIVERABLE


@pytest.mark.parametrize("status", [400, 401, 500, 502])
async def test_other_failures_are_retried(status: int) -> None:
    async with client(status_code=status, json={"ok": False, "description": "boom"}) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY
    assert result.retry_after is None


async def test_a_non_json_error_body_is_a_retry() -> None:
    async with client(status_code=502, text="<html>Bad Gateway</html>") as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY


async def test_a_network_error_is_a_retry_and_does_not_leak_the_token() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with client(httpx.MockTransport(boom)) as http:
        result = await send_message(http, TOKEN, 42, "x")
    assert result.outcome is SendOutcome.RETRY
    assert result.error == "ConnectError"
    assert TOKEN not in (result.error or "")


async def test_the_token_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        async with client(status_code=200, json={"ok": True}) as http:
            await send_message(http, TOKEN, 42, "x")
    assert TOKEN not in caplog.text
```

- [ ] **Шаг 2: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/notifications/test_telegram.py -v
```
Ожидается: `ModuleNotFoundError: ... notifications.telegram`.

- [ ] **Шаг 3: Реализация `notifications/telegram.py`**

```python
"""Клиент Telegram Bot API: одна функция — sendMessage."""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

import httpx

# httpx пишет каждый запрос в лог целиком (INFO), а токен бота лежит в URL запроса:
# /bot<token>/sendMessage. Уровень выставляется при импорте — любой процесс, который шлёт
# сообщения, получает его вместе с функцией.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = "https://api.telegram.org"
ERROR_LIMIT = 200


class SendOutcome(Enum):
    SENT = auto()
    RETRY = auto()
    UNDELIVERABLE = auto()  # получатель недоступен насовсем: повтор не поможет


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    retry_after: int | None = None
    error: str | None = None


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def send_message(
    http: httpx.AsyncClient, bot_token: str, chat_id: int, text: str
) -> SendResult:
    try:
        response = await http.post(
            f"{API_URL}/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": text}
        )
    except httpx.HTTPError as exc:
        # Текст исключения может содержать URL, а в нём — токен: сохраняем только тип.
        return SendResult(SendOutcome.RETRY, error=type(exc).__name__)
    if response.status_code == 200:
        return SendResult(SendOutcome.SENT)

    body = _body(response)
    description = str(body.get("description", ""))[:ERROR_LIMIT]
    error = f"{response.status_code}: {description}"
    if response.status_code == 429:
        parameters = body.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if isinstance(retry_after, int) and retry_after > 0:
            return SendResult(SendOutcome.RETRY, retry_after=retry_after, error=error)
    if response.status_code == 403 or (
        response.status_code == 400 and "chat not found" in description.lower()
    ):
        return SendResult(SendOutcome.UNDELIVERABLE, error=error)
    return SendResult(SendOutcome.RETRY, error=error)
```

- [ ] **Шаг 4: Запустить — PASS**

```bash
uv run pytest src/ocmanager/notifications/test_telegram.py -v
```

- [ ] **Шаг 5: Тест `notifications/test_tasks.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.notifications import tasks
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import render

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
TOKEN = "123456:secret-bot-token"
OK = (200, {"ok": True, "result": {}})


class FakeTelegram:
    """Подменяет Bot API: отвечает заданными (статус, тело) по очереди, последний — навсегда."""

    def __init__(self, *responses: tuple[int, dict[str, Any]]) -> None:
        self.responses = list(responses) or [OK]
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.AsyncClient:
        def respond(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status, body = self.responses[min(len(self.requests), len(self.responses)) - 1]
            return httpx.Response(status, json=body)

        return httpx.AsyncClient(transport=httpx.MockTransport(respond))


async def add(session: AsyncSession, **over: Any) -> OutboxMessage:
    fields: dict[str, Any] = {
        "recipient_type": "client",
        "chat_id": 42,
        "template_key": "expired",
        "lang": "ru",
        "payload": {},
        "send_after": NOW,
    } | over
    row = OutboxMessage(**fields)
    session.add(row)
    await session.flush()
    await session.commit()
    return row


async def run(
    sessionmaker: async_sessionmaker[AsyncSession], telegram: FakeTelegram, **kwargs: Any
) -> int:
    async with telegram.client() as http:
        return await tasks.send_pending(sessionmaker, http, TOKEN, pause=0, **kwargs)


async def test_a_pending_message_is_rendered_sent_and_marked(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session, template_key="device_issued", payload={"device": "iPhone"})
    telegram = FakeTelegram()

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1

    await session.refresh(row)
    assert (row.status, row.sent_at, row.attempts, row.last_error) == ("sent", NOW, 0, None)
    [request] = telegram.requests
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert request.content == httpx.Request(
        "POST",
        "http://x",
        json={"chat_id": 42, "text": render("device_issued", "ru", {"device": "iPhone"})},
    ).content


async def test_a_sent_message_is_not_sent_again(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1
        assert await run(sessionmaker, telegram) == 0
    assert len(telegram.requests) == 1


async def test_a_message_scheduled_for_later_waits(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session, send_after=NOW + timedelta(minutes=5))
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
    assert telegram.requests == []


async def test_messages_go_out_oldest_first(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await add(session, chat_id=1)
    await add(session, chat_id=2)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 2
    assert [r.content for r in telegram.requests] == [
        httpx.Request("POST", "http://x", json={"chat_id": chat, "text": render("expired", "ru", {})}).content
        for chat in (1, 2)
    ]


async def test_403_is_undeliverable_and_never_retried(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)
    telegram = FakeTelegram((403, {"ok": False, "description": "Forbidden: bot was blocked"}))

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
        assert await run(sessionmaker, telegram) == 0

    await session.refresh(row)
    assert (row.status, row.attempts) == ("undeliverable", 0)
    assert row.last_error is not None
    assert "blocked" in row.last_error
    assert len(telegram.requests) == 1


async def test_a_server_error_backs_off_and_the_tenth_failure_is_final(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)
    telegram = FakeTelegram((500, {"ok": False}), OK)

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0
        await session.refresh(row)
        assert (row.status, row.attempts) == ("pending", 1)
        assert row.send_after == NOW + timedelta(seconds=2)
        assert await run(sessionmaker, telegram) == 0  # пауза ещё не прошла
        assert len(telegram.requests) == 1

    with time_machine.travel(NOW + timedelta(seconds=3), tick=False):
        assert await run(sessionmaker, telegram) == 1  # второй ответ — OK
    await session.refresh(row)
    assert row.status == "sent"

    last = await add(session, attempts=tasks.MAX_ATTEMPTS - 1)
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, FakeTelegram((500, {"ok": False}))) == 0
    await session.refresh(last)
    assert (last.status, last.attempts) == ("failed", tasks.MAX_ATTEMPTS)


async def test_backoff_is_capped() -> None:
    assert tasks.backoff(1) == timedelta(seconds=2)
    assert tasks.backoff(5) == timedelta(seconds=32)
    assert tasks.backoff(30) == timedelta(seconds=tasks.MAX_BACKOFF_S)


async def test_429_reschedules_by_retry_after_and_stops_the_batch(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await add(session, chat_id=1)
    second = await add(session, chat_id=2)
    telegram = FakeTelegram(
        (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}})
    )

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 0

    await session.refresh(first)
    await session.refresh(second)
    assert len(telegram.requests) == 1  # вторую даже не пробовали
    assert (first.status, first.attempts, first.send_after) == (
        "pending",
        0,
        NOW + timedelta(seconds=7),
    )
    assert (second.status, second.attempts, second.send_after) == ("pending", 0, NOW)


async def test_an_unrenderable_message_fails_without_blocking_the_queue(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    broken = await add(session, template_key="no_such_template")
    fine = await add(session, chat_id=7)
    telegram = FakeTelegram()

    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram) == 1

    await session.refresh(broken)
    await session.refresh(fine)
    assert broken.status == "failed"
    assert broken.last_error is not None
    assert "no_such_template" in broken.last_error
    assert fine.status == "sent"
    assert len(telegram.requests) == 1


async def test_a_failed_send_does_not_leak_the_token_into_last_error(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    row = await add(session)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        with time_machine.travel(NOW, tick=False):
            await tasks.send_pending(sessionmaker, http, TOKEN, pause=0)

    await session.refresh(row)
    assert row.last_error == "ConnectError"


async def test_the_batch_size_limits_one_run(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    for chat in (1, 2, 3):
        await add(session, chat_id=chat)
    telegram = FakeTelegram()
    with time_machine.travel(NOW, tick=False):
        assert await run(sessionmaker, telegram, batch=2) == 2
        assert await run(sessionmaker, telegram, batch=2) == 1
```

- [ ] **Шаг 6: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/notifications/test_tasks.py -v
```
Ожидается: `ImportError: cannot import name 'tasks'`.

- [ ] **Шаг 7: Реализация `notifications/tasks.py`**

```python
"""Доставка очереди outbox_messages в Telegram.

Каждое сообщение — своя транзакция: строка берётся FOR UPDATE SKIP LOCKED (параллельные запуски
не шлют одно и то же), после ответа Telegram статус коммитится сразу. Падение процесса между
отправкой и коммитом дублирует максимум одно сообщение, а не пачку.
"""

import asyncio
from datetime import datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.core.clock import utcnow
from ocmanager.notifications import telegram
from ocmanager.notifications.models import OutboxMessage
from ocmanager.notifications.render import TemplateError, render
from ocmanager.notifications.telegram import SendOutcome, SendResult

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 10
MAX_BACKOFF_S = 600
ERROR_LIMIT = 500
# Глобальный лимит Telegram — 30 сообщений в секунду; идём с запасом.
SEND_PAUSE_S = 0.04


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts, MAX_BACKOFF_S))


async def _send_one(
    session: AsyncSession, http: httpx.AsyncClient, bot_token: str, now: datetime
) -> SendResult | None:
    """None — очередь пуста. Иначе результат попытки (для подсчёта и для 429)."""
    row = await session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.status == "pending", OutboxMessage.send_after <= now)
        .order_by(OutboxMessage.send_after, OutboxMessage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    try:
        text = render(row.template_key, row.lang, row.payload)
    except TemplateError as exc:
        # Шаблон удалён или payload не подходит: отправить это сообщение нельзя никогда.
        row.status = "failed"
        row.last_error = str(exc)[:ERROR_LIMIT]
        log.error("notification_unrenderable", message_id=row.id, error=str(exc))
        return SendResult(SendOutcome.UNDELIVERABLE, error=row.last_error)

    result = await telegram.send_message(http, bot_token, row.chat_id, text)
    if result.outcome is SendOutcome.SENT:
        row.status = "sent"
        row.sent_at = now
        row.last_error = None
    elif result.outcome is SendOutcome.UNDELIVERABLE:
        row.status = "undeliverable"
        row.last_error = result.error
        log.info("notification_undeliverable", message_id=row.id, error=result.error)
    elif result.retry_after is not None:
        # Просьба Telegram притормозить — не сбой сообщения: попытка не считается.
        row.send_after = now + timedelta(seconds=result.retry_after)
    else:
        row.attempts += 1
        row.last_error = result.error
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            log.warning("notification_failed", message_id=row.id, error=result.error)
        else:
            row.send_after = now + backoff(row.attempts)
    return result


async def send_pending(
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    bot_token: str,
    *,
    batch: int = 50,
    pause: float = SEND_PAUSE_S,
) -> int:
    """Отправляет до `batch` готовых сообщений. Возвращает число отправленных."""
    sent = 0
    for _ in range(batch):
        async with sessionmaker() as session, session.begin():
            result = await _send_one(session, http, bot_token, utcnow())
        if result is None:
            break
        if result.outcome is SendOutcome.SENT:
            sent += 1
        if result.retry_after is not None:
            break  # Telegram просит паузу для всей очереди, а не для одного сообщения
        await asyncio.sleep(pause)
    return sent
```

- [ ] **Шаг 8: Запустить — PASS**

```bash
uv run pytest src/ocmanager/notifications -v
```

- [ ] **Шаг 9: Воркер.** В `apps/worker.py`:

1. Импорты: `import httpx` (рядом со `structlog`) и
   `from ocmanager.notifications import tasks as notification_tasks`.
2. В `startup` — клиент HTTP, в `ctx.update(...)` добавьте `http=...`:

```python
    engine = make_engine(settings.database_url)
    ctx.update(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        http=httpx.AsyncClient(timeout=httpx.Timeout(10.0)),
    )
```

3. В `shutdown` перед `engine.dispose()`:

```python
    await ctx["http"].aclose()
    await ctx["engine"].dispose()
```

4. Новая задача (рядом с `purge_event_outbox`):

```python
async def send_outbox(ctx: dict[str, Any]) -> int:
    """Уведомления из очереди — в Telegram. Раз в 5 секунд, не больше 50 за запуск."""
    sent = await notification_tasks.send_pending(
        ctx["sessionmaker"], ctx["http"], ctx["settings"].bot_token.get_secret_value()
    )
    if sent:
        log.info("notifications_sent", count=sent)
    return sent
```

5. В `WorkerSettings.cron_jobs`:

```python
        cron(send_outbox, second=EVERY_5_SECONDS, keep_result=0),
```

- [ ] **Шаг 10: Тесты воркера.** В `apps/test_worker.py`:

1. В `test_cron_registry` добавьте строку `"cron:send_outbox",` в ожидаемое множество.
2. Добавьте тест (импорты `send_outbox` из `ocmanager.apps.worker`, `httpx`, `OutboxMessage` из
   `ocmanager.notifications.models`):

```python
async def test_send_outbox_delivers_through_the_bot_api(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    session.add(
        OutboxMessage(
            recipient_type="client",
            chat_id=42,
            template_key="expired",
            lang="ru",
            payload={},
            send_after=utcnow(),
        )
    )
    await session.commit()
    token = settings.bot_token.get_secret_value()
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker, "http": http}
        assert await send_outbox(ctx) == 1
    assert paths == [f"/bot{token}/sendMessage"]


async def test_startup_opens_and_shutdown_closes_the_http_client(
    settings: Settings, db_engine: object
) -> None:
    ctx: dict[str, Any] = {"settings": settings}
    await startup(ctx)
    http = ctx["http"]
    assert not http.is_closed
    await shutdown(ctx)
    assert http.is_closed
```

- [ ] **Шаг 11: Проверка и коммит**

```bash
uv run pytest src/ocmanager/apps/test_worker.py -v
make fmt && make check
git add src/ocmanager/notifications src/ocmanager/apps
git commit -m "feat(backend): telegram delivery with rate-limit aware retries"
```

---

### Задача 6.5: Напоминания об истечении и алерт «события застряли»

**Files:**
- Modify: `backend/src/ocmanager/flows/notify.py`, `backend/src/ocmanager/apps/worker.py`,
  `backend/src/ocmanager/apps/test_worker.py`
- Create: `backend/src/ocmanager/flows/test_notify_schedule.py`

**Interfaces:**
- Consumes: `notify.to_client`, `notify.to_admins`, `notify.day` (6.3); `bus.MAX_ATTEMPTS`;
  `RuntimeSettings.expiry_reminder_days` (по умолчанию `[3, 1]`).
- Produces:

```python
REMINDER_WINDOW = timedelta(hours=1)
async def enqueue_expiry_reminders(session: AsyncSession, now: datetime) -> int   # сколько поставлено
async def alert_stuck_events(session: AsyncSession, now: datetime) -> int         # сколько поставлено
```

Правила напоминаний: для каждого `d` из `expiry_reminder_days` — живые подписки с `auto_renew = false`,
`expires_at ∈ [now + d дн − 1 ч, now + d дн)`, незаблокированные клиенты, и **длина периода больше `d` дней**
(иначе триал на 3 дня получил бы «осталось 3 дня» через час после старта). `dedupe_key =
"expiring:{client_id}:{expires_at.date()}:{d}"` — повторный запуск и соседние окна ничего не удваивают.

- [ ] **Шаг 1: Тест `flows/test_notify_schedule.py`**

```python
from datetime import UTC, datetime, timedelta

from conftest import MakeClient, MakeSubscription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ocmanager.core import settings_store
from ocmanager.events import bus
from ocmanager.events.models import EventOutbox
from ocmanager.flows import notify
from ocmanager.notifications.models import OutboxMessage
from ocmanager.subscriptions.models import Client, Subscription

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
DAY = timedelta(days=1)


async def expiring(
    make_client: MakeClient,
    make_subscription: MakeSubscription,
    *,
    expires_in: timedelta,
    period: timedelta = 30 * DAY,
    auto_renew: bool = False,
    **client: object,
) -> tuple[Client, Subscription]:
    """Живая подписка, которая закончится через `expires_in`, при периоде `period`."""
    who = await make_client(**client)
    sub = await make_subscription(who, days=30, now=NOW, auto_renew=auto_renew)
    sub.expires_at = NOW + expires_in
    sub.started_at = sub.expires_at - period
    sub.auto_renew = auto_renew
    return who, sub


async def messages(session: AsyncSession) -> list[OutboxMessage]:
    return list(await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


async def test_a_reminder_goes_out_inside_the_window(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    client, _ = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )

    assert await notify.enqueue_expiry_reminders(session, NOW) == 1

    [message] = await messages(session)
    assert (message.recipient_type, message.chat_id, message.template_key, message.lang) == (
        "client",
        client.telegram_id,
        "expiring_soon",
        "ru",
    )
    assert message.payload == {"days": 3, "expires": "05.10.2026"}


async def test_hourly_runs_remind_once_per_threshold(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30))

    total = 0
    for hour in range(0, 80):  # больше трёх суток почасовых запусков
        total += await notify.enqueue_expiry_reminders(session, NOW + timedelta(hours=hour))

    assert total == 2  # «за 3 дня» и «за 1 день», ни одного повтора


async def test_running_the_same_window_twice_is_harmless(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30))
    assert await notify.enqueue_expiry_reminders(session, NOW) == 1
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_outside_the_window_nothing_is_sent(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(make_client, make_subscription, expires_in=3 * DAY + timedelta(minutes=1))
    await expiring(make_client, make_subscription, expires_in=3 * DAY - timedelta(hours=1, minutes=1))
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_auto_renewing_subscriptions_get_no_reminder(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        auto_renew=True,
    )
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_a_blocked_client_gets_no_reminder(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    client, _ = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )
    client.is_blocked = True
    await session.flush()
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_a_short_trial_skips_the_reminder_longer_than_itself(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    # Триал на 3 дня, только что начался: «осталось 3 дня» — нелепость. «Остался 1 день» — к месту.
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        period=3 * DAY,
    )
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0

    assert await notify.enqueue_expiry_reminders(session, NOW + 2 * DAY) == 1
    [message] = await messages(session)
    assert message.payload["days"] == 1


async def test_expired_subscriptions_are_not_reminded(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    _, sub = await expiring(
        make_client, make_subscription, expires_in=3 * DAY - timedelta(minutes=30)
    )
    sub.status = "expired"
    await session.flush()
    assert await notify.enqueue_expiry_reminders(session, NOW) == 0


async def test_an_english_client_is_reminded_in_english(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await expiring(
        make_client,
        make_subscription,
        expires_in=3 * DAY - timedelta(minutes=30),
        language_code="en",
    )
    await notify.enqueue_expiry_reminders(session, NOW)
    [message] = await messages(session)
    assert message.lang == "en"


async def test_the_thresholds_come_from_the_runtime_settings(
    session: AsyncSession, make_client: MakeClient, make_subscription: MakeSubscription
) -> None:
    await settings_store.update(session, {"expiry_reminder_days": [7]})
    await expiring(make_client, make_subscription, expires_in=7 * DAY - timedelta(minutes=30))
    assert await notify.enqueue_expiry_reminders(session, NOW) == 1
    [message] = await messages(session)
    assert message.payload["days"] == 7


async def test_stuck_events_alert_the_admins_once_a_day(session: AsyncSession) -> None:
    await settings_store.update(session, {"admin_chat_ids": [111]})
    session.add(
        EventOutbox(
            name="client.blocked",
            payload={"client_id": 1},
            available_at=NOW,
            attempts=bus.MAX_ATTEMPTS,
            last_error="boom",
        )
    )
    await session.flush()

    assert await notify.alert_stuck_events(session, NOW) == 1
    assert await notify.alert_stuck_events(session, NOW + timedelta(hours=5)) == 0
    assert await notify.alert_stuck_events(session, NOW + DAY) == 1

    first, _ = await messages(session)
    assert (first.template_key, first.payload) == ("internal_stuck", {"count": 1})


async def test_no_stuck_events_no_alert(session: AsyncSession) -> None:
    await settings_store.update(session, {"admin_chat_ids": [111]})
    session.add(
        EventOutbox(name="client.blocked", payload={"client_id": 1}, available_at=NOW, attempts=3)
    )
    await session.flush()
    assert await notify.alert_stuck_events(session, NOW) == 0
```

- [ ] **Шаг 2: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/flows/test_notify_schedule.py -v
```
Ожидается: `AttributeError: module 'ocmanager.flows.notify' has no attribute 'enqueue_expiry_reminders'`.

- [ ] **Шаг 3: Реализация.** В `flows/notify.py` добавьте импорты:

```python
from datetime import UTC, datetime, timedelta   # было: UTC, datetime

from sqlalchemy import func, select
...
from ocmanager.events.models import EventOutbox
from ocmanager.subscriptions.models import Client, Subscription   # было: Client
```

константу рядом с `DOWN`:

```python
REMINDER_WINDOW = timedelta(hours=1)
```

и две функции в конец файла:

```python
async def enqueue_expiry_reminders(session: AsyncSession, now: datetime) -> int:
    """Напоминания «подписка скоро закончится». Запускается раз в час: окно длиной в час
    для каждого порога, так что одна подписка попадает в него один раз; dedupe_key страхует
    от повторного запуска и от сдвига расписания. Автопродление — без напоминания: продлится само."""
    runtime = await settings_store.load(session)
    live = [s.value for s in LIVE]
    queued = 0
    for days in runtime.expiry_reminder_days:
        threshold = now + timedelta(days=days)
        rows = await session.execute(
            select(Subscription, Client)
            .join(Client, Client.id == Subscription.client_id)
            .where(
                Subscription.status.in_(live),
                Subscription.auto_renew.is_(False),
                Subscription.expires_at >= threshold - REMINDER_WINDOW,
                Subscription.expires_at < threshold,
                Client.is_blocked.is_(False),
            )
        )
        for sub, client in rows:
            if sub.expires_at - sub.started_at <= timedelta(days=days):
                continue  # период короче порога: «осталось 3 дня» в первый же час — нелепость
            queued += await to_client(
                session,
                client.id,
                "expiring_soon",
                {"days": days, "expires": day(sub.expires_at)},
                dedupe_key=f"expiring:{client.id}:{sub.expires_at.date()}:{days}",
            )
    return queued


async def alert_stuck_events(session: AsyncSession, now: datetime) -> int:
    """События outbox, исчерпавшие попытки, сами не доставятся: нужен человек. Алерт — раз в сутки,
    пока они лежат."""
    stuck = await session.scalar(
        select(func.count())
        .select_from(EventOutbox)
        .where(EventOutbox.dispatched_at.is_(None), EventOutbox.attempts >= bus.MAX_ATTEMPTS)
    )
    if not stuck:
        return 0
    return await to_admins(
        session, "internal_stuck", {"count": stuck}, dedupe_key=f"internal_stuck:{now.date()}"
    )
```

Если `ruff` ругнётся на `Client, Subscription` — импорт `Client` уже был, дублировать не нужно: итоговая строка
`from ocmanager.subscriptions.models import Client, Subscription`.

- [ ] **Шаг 4: Запустить — PASS**

```bash
uv run pytest src/ocmanager/flows/test_notify_schedule.py -v
```

- [ ] **Шаг 5: Воркер.** В `apps/worker.py` добавьте задачи рядом с `send_outbox`:

```python
async def expiry_reminders(ctx: dict[str, Any]) -> int:
    """Напоминания об истечении — раз в час."""
    async with ctx["sessionmaker"]() as session:
        queued = await notify_flows.enqueue_expiry_reminders(session, utcnow())
        await session.commit()
    if queued:
        log.info("expiry_reminders_queued", count=queued)
    return queued


async def alert_stuck_events(ctx: dict[str, Any]) -> int:
    """Недоставленные события доменной шины — алерт админу раз в сутки."""
    async with ctx["sessionmaker"]() as session:
        queued = await notify_flows.alert_stuck_events(session, utcnow())
        await session.commit()
    return queued
```

и в `cron_jobs`:

```python
        cron(expiry_reminders, minute={0}, second={5}, keep_result=0),
        cron(alert_stuck_events, hour={9}, minute={0}, second={10}, keep_result=0),
```

- [ ] **Шаг 6: Тесты воркера.** В `apps/test_worker.py`:

1. В `test_cron_registry` добавьте `"cron:expiry_reminders",` и `"cron:alert_stuck_events",`.
2. Тест:

```python
async def test_expiry_reminders_job_queues_and_commits(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_client: MakeClient,
    make_subscription: MakeSubscription,
) -> None:
    now = utcnow()
    client = await make_client()
    sub = await make_subscription(client, days=30, now=now, auto_renew=False)
    sub.auto_renew = False
    sub.expires_at = now + timedelta(days=1) - timedelta(minutes=10)
    sub.started_at = now - timedelta(days=29)
    await session.commit()

    assert await expiry_reminders({"sessionmaker": sessionmaker}) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1


def test_the_hourly_reminder_job_runs_on_the_hour() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:expiry_reminders"]
    assert job.minute == {0}
```

Нужные импорты в `test_worker.py`: `MakeSubscription` из `conftest`, `func` из `sqlalchemy`,
`expiry_reminders` из `ocmanager.apps.worker`.

- [ ] **Шаг 7: Проверка и коммит**

```bash
make fmt && make check
git add src/ocmanager/flows src/ocmanager/apps
git commit -m "feat(backend): expiry reminders and a stuck-events alert"
```

---

### Задача 6.6: Процесс бота

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (aiogram), `backend/Makefile`,
  `backend/src/ocmanager/apps/test_entrypoints.py`
- Create: `backend/src/ocmanager/apps/bot.py`, `backend/src/ocmanager/apps/test_bot.py`

**Interfaces:**
- Consumes: `register_client(session, TelegramIdentity) -> UpsertResult` (`flows/clients.py`);
  `lang_from_telegram(code) -> "ru" | "en"` (`subscriptions/service.py`); `render` (6.1);
  `Settings.public_base_url`, `Settings.bot_token`.
- Produces:

```python
async def start(message: Message, *, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]) -> None
async def whoami(message: Message) -> None
async def fallback(message: Message, *, settings: Settings) -> None
router: Router
def main() -> None            # python -m ocmanager.apps.bot
```

Команды: `/start` — регистрирует клиента, отвечает на его языке с кнопкой Mini App; `/whoami` — показывает
`chat_id` (так админ узнаёт значение для `admin_chat_ids` без доступа к БД); любой другой текст — подсказка с
той же кнопкой. Бот **ничего не рассылает**: уведомления шлёт воркер из очереди.

- [ ] **Шаг 1: Зависимость**

```bash
uv add aiogram
uv run python -c "import aiogram; print(aiogram.__version__)"
```
Ожидается: версия `3.x`. Если `uv` сообщает о конфликте с `pydantic` — пришлите вывод.

- [ ] **Шаг 2: Тест `apps/test_bot.py`**

```python
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocmanager.apps import bot
from ocmanager.core.config import Settings
from ocmanager.notifications.render import render
from ocmanager.subscriptions.models import Client

PANEL = "https://panel.example.com"


class FakeMessage:
    """Ровно то, что читают обработчики: from_user, chat и answer()."""

    def __init__(
        self,
        *,
        user_id: int = 7001,
        first_name: str = "Anna",
        language_code: str | None = "ru",
        chat_id: int | None = None,
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, first_name=first_name, username=None, language_code=language_code
        )
        self.chat = SimpleNamespace(id=user_id if chat_id is None else chat_id)
        self.answers: list[tuple[str, Any]] = []

    async def answer(self, text: str, reply_markup: Any = None) -> None:
        self.answers.append((text, reply_markup))


def msg(fake: FakeMessage) -> Message:
    return cast("Message", fake)


@pytest.fixture
def https_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"public_base_url": PANEL})


async def clients(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Client)) or 0


async def test_start_registers_the_client_and_opens_the_mini_app(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    fake = FakeMessage(user_id=7001, first_name="Anna")

    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)

    assert await clients(session) == 1
    client = await session.scalar(select(Client).where(Client.telegram_id == 7001))
    assert client is not None
    assert (client.first_name, client.lang) == ("Anna", "ru")
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "ru", {"name": "Anna"})
    button = markup.inline_keyboard[0][0]
    assert button.text == render("bot_open_app", "ru", {})
    assert button.web_app.url == PANEL


async def test_start_twice_does_not_duplicate_the_client(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    for _ in range(2):
        await bot.start(msg(FakeMessage()), settings=https_settings, sessionmaker=sessionmaker)
    assert await clients(session) == 1


async def test_start_answers_in_the_clients_language(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    https_settings: Settings,
) -> None:
    fake = FakeMessage(language_code="en")
    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "en", {"name": "Anna"})
    assert markup.inline_keyboard[0][0].text == render("bot_open_app", "en", {})


async def test_start_without_https_sends_no_button(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    # Telegram отвергает web_app с http-адресом и всё сообщение пропало бы.
    assert settings.public_base_url.startswith("http://")
    fake = FakeMessage()
    await bot.start(msg(fake), settings=settings, sessionmaker=sessionmaker)
    [(text, markup)] = fake.answers
    assert text == render("bot_start", "ru", {"name": "Anna"})
    assert markup is None


async def test_whoami_shows_the_chat_id_and_touches_no_database(session: AsyncSession) -> None:
    fake = FakeMessage(user_id=7001, chat_id=555)
    await bot.whoami(msg(fake))
    [(text, _)] = fake.answers
    assert text == render("bot_whoami", "ru", {"chat_id": 555})
    assert await clients(session) == 0


async def test_any_other_text_gets_the_hint_with_the_button(https_settings: Settings) -> None:
    fake = FakeMessage(language_code="en")
    await bot.fallback(msg(fake), settings=https_settings)
    [(text, markup)] = fake.answers
    assert text == render("bot_hint", "en", {})
    assert markup.inline_keyboard[0][0].web_app.url == PANEL


async def test_a_message_without_a_sender_is_ignored(
    sessionmaker: async_sessionmaker[AsyncSession], https_settings: Settings
) -> None:
    fake = FakeMessage()
    fake.from_user = None  # type: ignore[assignment]
    await bot.start(msg(fake), settings=https_settings, sessionmaker=sessionmaker)
    await bot.whoami(msg(fake))
    await bot.fallback(msg(fake), settings=https_settings)
    assert fake.answers == []
```

- [ ] **Шаг 3: Запустить — FAIL**

```bash
uv run pytest src/ocmanager/apps/test_bot.py -v
```
Ожидается: `ImportError: cannot import name 'bot' from 'ocmanager.apps'`.

- [ ] **Шаг 4: Реализация `apps/bot.py`**

```python
"""Процесс бота: aiogram 3, long polling (публичный вебхук для бота не нужен).

Запуск: `uv run python -m ocmanager.apps.bot`.
Бот ничего не рассылает: уведомления кладут в очередь обработчики событий, отправляет воркер
(notifications/tasks.py) — рестарт бота не теряет сообщения.
"""

import asyncio
from typing import Literal

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import ocmanager.models  # noqa: F401 — регистрирует все таблицы: без этого FK между доменами не разрешаются
from ocmanager.core.config import Settings, get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.core.logging import configure_logging
from ocmanager.flows.clients import register_client
from ocmanager.notifications.render import render
from ocmanager.subscriptions.schemas import TelegramIdentity
from ocmanager.subscriptions.service import lang_from_telegram

log = structlog.get_logger(__name__)

router = Router(name="main")
router.message.filter(F.chat.type == "private")


def open_app_markup(settings: Settings, lang: Literal["ru", "en"]) -> InlineKeyboardMarkup | None:
    """Кнопка Mini App. Telegram принимает web_app только с https: без него (dev без туннеля)
    отвечаем без кнопки, а не теряем сообщение целиком."""
    if not settings.public_base_url.startswith("https://"):
        return None
    button = InlineKeyboardButton(
        text=render("bot_open_app", lang, {}), web_app=WebAppInfo(url=settings.public_base_url)
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


@router.message(CommandStart())
async def start(
    message: Message, *, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    user = message.from_user
    if user is None:
        return
    identity = TelegramIdentity(
        telegram_id=user.id,
        first_name=user.first_name,
        username=user.username,
        language_code=user.language_code,
    )
    async with sessionmaker() as session:
        result = await register_client(session, identity)
        await session.commit()
    lang = lang_from_telegram(result.client.lang)
    await message.answer(
        render("bot_start", lang, {"name": user.first_name}),
        reply_markup=open_app_markup(settings, lang),
    )


@router.message(Command("whoami"))
async def whoami(message: Message) -> None:
    """chat_id для admin_chat_ids: так админ узнаёт его, не заходя в БД."""
    user = message.from_user
    if user is None:
        return
    lang = lang_from_telegram(user.language_code)
    await message.answer(render("bot_whoami", lang, {"chat_id": message.chat.id}))


@router.message()
async def fallback(message: Message, *, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = lang_from_telegram(user.language_code)
    await message.answer(
        render("bot_hint", lang, {}), reply_markup=open_app_markup(settings, lang)
    )


async def run(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = Dispatcher(settings=settings, sessionmaker=make_sessionmaker(engine))
    dispatcher.include_router(router)
    try:
        # Бот мог раньше работать на вебхуке: пока он стоит, getUpdates отвечает ошибкой.
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("bot_started")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
        log.info("bot_stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, fmt=settings.log_format)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
```

Про DI aiogram: именованные параметры `settings` и `sessionmaker` подставляются из данных диспетчера
(`Dispatcher(settings=…, sessionmaker=…)`), обработчик получает только те, что есть в его сигнатуре. Если в вашей
версии aiogram `*` перед `settings` мешает регистрации — уберите `*` (тесты вызывают с именованными аргументами и
останутся зелёными).

- [ ] **Шаг 5: Запустить — PASS**

```bash
uv run pytest src/ocmanager/apps/test_bot.py -v
```

- [ ] **Шаг 6: Процесс знает все таблицы.** В `apps/test_entrypoints.py` добавьте в `parametrize` модуль:

```python
        "ocmanager.apps.worker",
        "ocmanager.apps.bot",
        "ocmanager.cli",
```

```bash
uv run pytest src/ocmanager/apps/test_entrypoints.py -v
```

- [ ] **Шаг 7: Цель в Makefile.** Добавьте `bot` в `.PHONY` и новую цель рядом с `api-admin`:

```make
bot:        ## бот: long polling, нужен OCM_BOT_TOKEN
	uv run python -m ocmanager.apps.bot
```

- [ ] **Шаг 8: Проверка и коммит**

```bash
make fmt && make check
git add pyproject.toml uv.lock Makefile src/ocmanager/apps
git commit -m "feat(backend): telegram bot with mini app entry and admin chat discovery"
```

---

### Задача 6.7: Сквозная проверка на dev-стенде

Автотесты проверяют каждое звено по отдельности; здесь — живой Telegram и настоящий воркер. Код не пишется.
**Критерий готовности фазы** (из дорожной карты): оплата, выпуск и отзыв устройства дают сообщения клиенту,
остановка `ocm-ocserv` за ≤ 2 минуты даёт алерт админу, возврат — второй алерт.

**Нужно:** бот из @BotFather (можно тестовый); в `backend/.env` — `OCM_BOT_TOKEN=<токен>`; Docker запущен.
Кнопка Mini App появится только при `OCM_PUBLIC_BASE_URL=https://…` (туннель из проверки Фазы 5); остальное
работает и без неё.

- [ ] **Шаг 1: Поднять стенд**

```bash
cd backend
make dev-up && make migrate
make ocserv-up
```

В трёх терминалах: `uv run python -m ocmanager.apps.worker`, `make bot`, `make api-public`.

- [ ] **Шаг 2: Узнать свой `chat_id`.** Напишите боту `/whoami` — он ответит числом. Затем:

```bash
docker compose -f ../deploy/docker-compose.dev.yml exec -T postgres psql -U ocm -d ocmanager -c \
  "INSERT INTO settings (key, value) VALUES ('admin_chat_ids', '[<ваш chat_id>]') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
```

Ожидается: `INSERT 0 1`. (То же самое делает `PATCH /admin/settings` — это быстрее для проверки.)

- [ ] **Шаг 3: Приветствие.** Напишите боту `/start`. Ожидается: ответ на вашем языке, клиент появился в
  `clients`; с https-адресом — кнопка «Открыть приложение».

- [ ] **Шаг 4: Нода.** Подождите минуту (первый `unknown → online` молчит — так и задумано), затем:

```bash
docker stop ocm-ocserv
```

Ожидается: в течение двух минут админское «⚠️ Нода «local» недоступна (offline)». Затем:

```bash
docker start ocm-ocserv
```

Ожидается: «✅ Нода «local» снова в сети». Повторный `stop`/`start` даёт новую пару алертов.

- [ ] **Шаг 5: Оплата, устройство, отзыв.** Пройдите сценарий проверки Фазы 5 (`scripts/tribute_tool.py send …`
  с вашим `telegram_user_id` в теле) и выпустите и отзовите устройство через TMA (сценарий Фазы 4).
  Ожидается: клиенту — «Оплата … получена», «Ключ для устройства … выпущен», «Устройство … отозвано»; админу —
  «💰 Новая оплата …». Отправьте то же тело вебхука второй раз — **новых сообщений быть не должно**.

- [ ] **Шаг 6: Напоминание.** Подведите подписку к окну и запустите расчёт напрямую, не дожидаясь часа:

```bash
docker compose -f ../deploy/docker-compose.dev.yml exec -T postgres psql -U ocm -d ocmanager -c \
  "UPDATE subscriptions SET auto_renew = false, started_at = now() - interval '29 days', expires_at = now() + interval '1 day' - interval '10 minutes'"

uv run python - <<'EOF'
import asyncio

import ocmanager.models  # noqa: F401
from ocmanager.core.clock import utcnow
from ocmanager.core.config import get_settings
from ocmanager.core.db import make_engine, make_sessionmaker
from ocmanager.flows import notify


async def main() -> None:
    sessionmaker = make_sessionmaker(make_engine(get_settings().database_url))
    async with sessionmaker() as session:
        print(await notify.enqueue_expiry_reminders(session, utcnow()))
        await session.commit()


asyncio.run(main())
EOF
```

Ожидается: `1` и через ≤ 5 секунд «Подписка заканчивается через 1 дн.». Повторный запуск печатает `0`.

- [ ] **Шаг 7: Бот заблокирован.** В Telegram заблокируйте бота и повторите шаг 6 (после сброса:
  `DELETE FROM outbox_messages`). Ожидается: строка в `outbox_messages` со `status = 'undeliverable'`, воркер
  не зацикливается и не ругается в логи.

- [ ] **Шаг 8: Токен не в логах**

```bash
grep -c "$OCM_BOT_TOKEN" <логи воркера и бота>
```
Ожидается: `0` (если логи идут в терминал — просмотрите вывод воркера и бота глазами: токена в нём нет).

- [ ] **Шаг 9: Остановить стенд и закрыть фазу**

```bash
make ocserv-down
git status
```

Ожидается: рабочее дерево чистое (все задачи закоммичены). Отметьте Фазу 6 выполненной.

---

## Что Фаза 6 передаёт дальше

| Что | Кому | Контракт |
|---|---|---|
| Процесс бота `python -m ocmanager.apps.bot` | Фаза 7 (compose, образ) | Третий процесс одного образа; нужны `OCM_BOT_TOKEN`, `OCM_DATABASE_URL`, `OCM_PUBLIC_BASE_URL` (https — для кнопки). Порты не слушает |
| Исходящий HTTPS воркера на `api.telegram.org` | Фаза 7 (сеть) | Воркер должен выходить в интернет; `api-public` — нет, он ничего не шлёт |
| `outbox_messages` | Админка (этап 2) | Журнал уведомлений со `status`/`attempts`/`last_error`; очистки старых `sent` пока нет |
| `flows/notify.register()` | Любой новый процесс с шиной | Вызывается рядом с `handlers.register(settings)` |

## Определение готовности фазы

- [ ] Задачи 6.1–6.6 закоммичены, `make check` зелёный.
- [ ] Шаги 6.7 пройдены на живом боте: сообщения клиенту, алерты админу, дедупликация, недоставляемый получатель.
- [ ] Токен бота не найден ни в логах, ни в `last_error`.
- [ ] Для каждого пункта Review Focus есть тест, и он зелёный.

## Покрытие требований дорожной карты

| Требование Фазы 6 | Задача |
|---|---|
| Outbox уведомлений, дедупликация | 6.2 |
| Шаблоны ru/en, равенство множеств ключей | 6.1 |
| Клиентские уведомления (оплата, ключ, истечение, отзыв, trial) | 6.3, 6.5 |
| Алерты админу (нода, вебхуки, оплата, возврат) | 6.3 |
| Доставка с лимитами Telegram (429, 403, 5xx, 10 попыток) | 6.4 |
| Напоминания по `expiry_reminder_days`, без `auto_renew` | 6.5 |
| Алерт про застрявшие события outbox | 6.5 |
| Бот: `/start`, `/whoami`, кнопка Mini App | 6.6 |
| Критерий готовности на dev-стенде | 6.7 |
