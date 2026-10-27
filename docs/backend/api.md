# API

Три поверхности. Схему админ-API всегда можно открыть на `http://localhost:8080/admin/docs` (через SSH-туннель); у публичного
API документация включена только в dev (`/api/docs`). Ошибки у всех одинаковы:

```json
{"error": {"code": "device_limit_reached", "message": "…"}}
```

## Публичный API (`api-public`, порт 8000)

Снаружи доступны только `/api/*` и `/webhooks/*` (через Caddy). `/internal/*` на периметре отвечает 404.

### Mini App: `/api/tma/*`

Авторизация: заголовок `Authorization: tma <initData>` — строка, подписанная Telegram (HMAC от токена бота; срок жизни
`OCM_TMA_INITDATA_TTL_S`, по умолчанию сутки; от клиента не принимается дата из будущего больше чем на 5 минут).
Клиент создаётся при первом обращении. Заблокированный клиент всё равно получает `GET /me` (с `is_blocked: true`, чтобы приложение показало причину), а подключение и выпуск ключей ему недоступны.

| Метод и путь | Назначение |
|---|---|
| `GET /me` | клиент: язык, статус, блокировка |
| `GET /plans` | активные тарифы по `sort_order` |
| `GET /subscription` | текущая подписка или `null` |
| `POST /subscription/trial` | запуск пробного периода (один раз на клиента) |
| `POST /checkout` | `{plan_code}` → ссылка на оплату в Tribute |
| `GET /connection` | адрес шлюза с камуфляжным секретом |
| `GET /devices` | неотозванные устройства |
| `POST /devices` | выпуск ключа: ответ с паролем и одноразовой ссылкой (нигде не кэшируется) |
| `DELETE /devices/{id}` | отзыв (чужое и несуществующее неотличимы: `not_found`) |
| `GET /download/{token}` | скачать `.p12` (без initData, ссылка одноразовая, 15 минут) |
| `GET /referral` | код, ссылка, друзья, уровни, история наград |
| `POST /promo/redeem` | погасить промокод |

Rate limit по клиенту на пробный период, оплату, выпуск устройства и промокоды (Redis, фиксированное окно); превышение — `429`.

### Вебхуки: `/webhooks/{provider}`

`POST /webhooks/tribute`: принимает сырое тело, проверяет подпись, пишет в `webhook_events`, отвечает сразу, дальше работает воркер.

### Внутренний: `/internal/*`

`POST /internal/session-end` — финальные счётчики сессии от `disconnect.sh`. Заголовок `X-Internal-Token`; доступен ноде только
по внутренней сети `hooks`.

### Служебное

`GET /api/health`: проверка живости (используется healthcheck и `doctor`).

## Админ-API (`api-admin`, `/admin/*`, 127.0.0.1:8080)

### Авторизация

- Вход `POST /admin/auth/login` (логин, пароль, код TOTP, если включён). Ответ: админ и `csrf_token`; cookie `ocm_admin`
  (HttpOnly) хранит токен серверной сессии (в БД только его хеш).
- Все изменяющие запросы требуют заголовок `X-CSRF-Token`.
- Сессия: простой 12 часов, максимум 7 дней. Сессии видны и отзываются (`/auth/sessions`).
- Вход ограничен 5 попытками за 15 минут на пару логин + адрес. Роль одна (`owner`).
- TOTP подключается в профиле: `/auth/totp/setup`, `/auth/totp/confirm`, `/auth/totp/disable`.

### Разделы

| Раздел | Пути |
|---|---|
| Авторизация | `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password`, `/auth/totp/*`, `/auth/sessions` |
| Обзор | `GET /overview` |
| Клиенты | `GET /clients`, `GET /clients/{id}`, `POST /clients/{id}/{block,unblock,grant,extend,reset-traffic,devices}`, `GET /downloads/{token}` |
| Подписки | `GET /subscriptions`, `POST /subscriptions/{client_id}/{cancel-auto-renew,expire}` |
| Тарифы | `GET/POST /plans`, `PATCH /plans/{code}` |
| Устройства | `GET /devices`, `POST /devices/{id}/revoke`, `GET /devices/{id}/sessions` |
| Платежи | `GET /payments`, `GET /webhooks`, `GET /webhooks/{id}`, `POST /webhooks/{id}/reprocess` |
| Статистика | `/stats/{traffic,revenue,clients,economics}` |
| Промокоды | `/promo-codes` (список, создание, изменение, удаление, `/{id}/redemptions`) |
| Рефералы | `/referrals/stats`, `/referrals/rewards` |
| Нода | `GET /node`, `POST /node/{probe,actions,reconcile}`, `GET /node/sessions`, `GET /node/logs` (SSE) |
| Журнал | `GET /audit` |
| Настройки | `GET/PATCH /settings` (runtime-настройки, в том числе `bypass_routes`) |
| Экспорт | `/export/{clients,subscriptions,payments,audit,traffic}.csv` |

Списки поддерживают пагинацию (`limit`/`offset`) и фильтры; все изменения пишутся в `audit_log` с именем админа и IP.
`GET /node/logs` — поток Server-Sent Events (хвост логов ocserv).

### Типы для фронтенда

- **Админка:** `frontend/admin/src/api/generated.d.ts` генерируется из OpenAPI бэкенда без запуска сервера (`make admin-types`);
  `make admin-types-check` в CI падает, если типы устарели.
- **Mini App:** `frontend/tma/src/api/generated.d.ts` берётся с запущенного `api-public` в dev-режиме (`npm run api:types`);
  собственные типы приложения (`types.ts`) сверяются с ним проверкой типов (`npm run api:check`).

## CLI (`ocmanager …`)

Для оператора, в Docker: `docker compose run --rm -T cli <команда>`; на разработке: `uv run ocmanager <команда>`.

| Группа | Что делает |
|---|---|
| `pki` | `init` (CA), `dev-server-cert` |
| `admin` | `create`, `passwd`, `reset-totp`, `list` (пароль из stdin: `--password-stdin`) |
| `client`, `subscription`, `plan`, `device` | заведение клиентов, выдача тарифа, тарифы, ключи |
| `node` | сессии, allowlist |
| `reconcile` | ручная сверка ноды |
| `notify` | `backup-failed --reason …` ставит алерт админам в очередь |
| `settings` | `admin-chat <id>` добавляет чат для алертов |
