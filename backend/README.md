# ocmanager · backend

Один Python-пакет, из которого запускаются четыре процесса: публичный API, админ-API, воркер и бот. Плюс CLI для
оператора. Всё общается через общую PostgreSQL и Redis.

> Общая картина: [docs/architecture.md](../docs/architecture.md). Детали бэкенда: [docs/backend/](../docs/backend/).

## Стек

| Область | Что используется |
|---|---|
| Язык, веб | Python 3.12, FastAPI, uvicorn |
| БД | PostgreSQL 16, SQLAlchemy 2 (async, asyncpg), Alembic |
| Очередь и кеш | Redis 7, arq (очередь и cron), собственный rate limit |
| Бот | aiogram 3 (long polling) |
| Криптография | `cryptography` (CA, сертификаты, `.p12`, CRL), bcrypt, pyotp (TOTP) |
| Качество | pytest + pytest-asyncio, ruff, mypy `--strict`, проверка границ модулей |
| Прочее | pydantic-settings, structlog, typer (CLI), httpx |

## Процессы

| Команда запуска | Что делает | Порт |
|---|---|---|
| `api-public` | Mini App API (`/api/*`), вебхуки платёжных систем, внутренний хук ноды | 8000 |
| `api-admin` | админ-API (`/admin/*`) и статика веб-админки | 127.0.0.1:8080 |
| `worker` | очередь arq и cron: события, уведомления, сверка ноды, трафик, истечение подписок | нет |
| `bot` | Telegram-бот, long polling | нет |
| `migrate` | `alembic upgrade head` и выход | нет |
| `ocmanager …` | CLI: `pki`, `admin`, `client`, `device`, `plan`, `node`, `notify`, `settings` | нет |

## Запуск для разработки

```bash
cd backend
make dev-up          # Postgres и Redis в Docker
make migrate         # схема БД
uv run ocmanager pki init            # корневой CA (один раз)
uv run ocmanager admin create owner  # первый администратор
make api-admin       # http://127.0.0.1:8080
```

Остальные процессы: `make api-public`, `make bot` (нужен `OCM_BOT_TOKEN`), `uv run python -m ocmanager.apps.worker`.
Настройки читаются из `backend/.env` (шаблон: `.env.example`, префикс `OCM_`).

## Проверки

```bash
make check           # ruff + mypy --strict + границы модулей + pytest
make test-unit       # только тесты без Postgres и Redis
make ocserv-up && make test-ocserv   # интеграционные тесты с живым ocserv и VPN-клиентами
make test-load       # нагрузочные проверки
```

## Структура

```
src/ocmanager/
  core/            настройки, БД, ошибки, часы, crypto, rate limit, runtime-настройки
  events/          доменные события и транзакционный outbox
  billing/ subscriptions/ provisioning/ nodes/ notifications/ audit/   доменные модули
  flows/           склейка доменов: покупка, доступ, трафик, сверка ноды, рефералы
  admin/ tma/      HTTP-слой админки и Mini App
  apps/            точки входа процессов (public_api, admin_api, worker, bot)
  cli/             команды оператора
alembic/           миграции (0001–0014)
scripts/           проверка границ, выгрузка OpenAPI, утилита для Tribute
tests/             интеграционные и нагрузочные тесты
```

Главное правило: доменные модули **не импортируют друг друга**, только `core` и `events`; склейка живёт в `flows/`.
Проверяется `make boundaries`. Подробности: [docs/backend/architecture.md](../docs/backend/architecture.md).
