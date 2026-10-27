# Развёртывание и эксплуатация

Инструкция владельца: [deploy/INSTALL.ru.md](../deploy/INSTALL.ru.md) ([English](../deploy/INSTALL.md)). Здесь устройство.

## Состав Docker Compose (`deploy/docker-compose.yml`)

Проект называется `ocmanager`. Один файл описывает весь боевой стек.

| Сервис | Образ | Что делает | Сети |
|---|---|---|---|
| `postgres` | postgres:16 | база, том `pgdata` | app |
| `redis` | redis:7 | очередь, rate limit, одноразовые ссылки, том `redisdata` | app |
| `volume-init` | alpine | разово выставляет владельца томов (10001) | |
| `migrate` | backend | `alembic upgrade head`, затем выход | app |
| `api-public` | backend | публичный API | web, hooks, app |
| `api-admin` | backend | админ-API; порт 127.0.0.1:8080 | app, docker |
| `worker` | backend | очередь и cron | app, docker |
| `bot` | backend | Telegram-бот | app |
| `docker-proxy` | haproxy | белый список запросов к Docker API | docker |
| `ocserv` | ocserv | VPN-нода, `container_name: ocm-ocserv`, 443/udp | edge, hooks |
| `caddy` | web (Caddy + статика Mini App) | сертификаты, прокси, 80/tcp | edge, web |
| `nginx` | nginx | 443/tcp, SNI-маршрутизация | edge |
| `cli` | backend | разовые команды (`docker compose run --rm -T cli …`), профиль `tools` | app |

Образ backend один на `migrate`, `api-*`, `worker`, `bot` и `cli`: роль выбирается командой. Он собирается в три стадии:
сборка админки → окружение Python (uv) → рантайм.

### Сети

| Сеть | Зачем |
|---|---|
| `edge` (172.29.10.0/24) | nginx ↔ Caddy ↔ ocserv; Caddy принимает PROXY-заголовок только из этой подсети |
| `web` | Caddy → api-public |
| `hooks` (internal) | ocserv → api-public: только `POST /internal/session-end`, наружу выхода нет |
| `app` | сервисы ↔ Postgres и Redis |
| `docker` (internal) | docker-proxy ↔ worker и api-admin |

### Тома

`pgdata`, `redisdata`, `pki` (CA и ключи), `ocserv-state` (общий каталог состояния ноды), `caddy-data` (сертификаты),
`caddy-config`.

### Порты

Наружу: 80/tcp (ACME и редирект), 443/tcp (nginx), 443/udp (DTLS, прямо в ocserv). Админка: только `127.0.0.1:8080` и SSH-туннель.

## Нода ocserv

Каталог [`ocserv/`](../ocserv): образ ноды.

- **Общий каталог состояния** `/var/lib/ocmanager` (том `ocserv-state`): панель пишет, нода читает (в ocserv смонтирован
  только на чтение). Файлы: `allowed.list` (допущенные логины), `crl.pem`, `ca.crt`, `default-user.conf` (строки `no-route`).
- **`entrypoint.sh`**: ждёт сертификат сервера (его выпускает Caddy) и CRL, готовит секрет для хуков, собирает конфиг, включает NAT,
  запускает ocserv под `tini`.
- **`render-conf.sh`** (`ocm-render-conf`): шаблон `ocserv.conf.tmpl` + строки `no-route` → `ocserv.conf`, проверка
  `ocserv --test-config` перед заменой. Панель вызывает его через `docker exec` после смены маршрутов, затем `occtl reload`.
- **Хуки**: `connect.sh` пускает только логины из `allowed.list` (без сети); `disconnect.sh` шлёт итоговые счётчики сессии.
- **Управление ноды**: через `LocalDockerDriver` (`docker exec ocm-ocserv occtl …`) и файлы состояния. Интерфейс
  `NodeDriver` задуман так, что другие драйверы (удалённые ноды) подключаются без изменений остального кода.

## Доступ воркера к Docker

Воркеру и api-admin нужно управлять только одной нодой, но сокет Docker даёт root на хосте. Поэтому они ходят в Docker
не напрямую, а через `docker-proxy` (haproxy). Он разрешает только запросы к контейнеру `ocm-ocserv`:
`inspect`, `logs`, `exec`, `start`, `stop`, `restart`. Всё остальное — 403 (проверка: `deploy/docker-proxy/check.sh`).

## TLS и маршрутизация 443

nginx принимает 443/tcp, читает SNI (`ssl_preread`) и без расшифровки направляет:
домен VPN → `ocserv:443`, всё остальное (включая соединения без SNI) → `caddy:8443`. Оба получают реальный адрес клиента
через PROXY-протокол. Caddy выпускает сертификаты Let's Encrypt для **обоих** доменов (HTTP-01 на порту 80); ocserv читает свой
сертификат из тома `caddy-data`.

## Установщик и `ocm`

| Файл | Роль |
|---|---|
| `install.sh` | проверяет root и python3, запускает `deploy/installer` |
| `deploy/installer/` | мастер на Python (stdlib): проверки системы, вопросы, шаги, состояние, бэкапы, `ocm` |
| `deploy/ocm` | bash-обёртка → `installer.ocm`; ставится ссылкой в `/usr/local/bin/ocm` |
| `deploy/.install-state` | выполненные шаги и несекретные ответы (повторный запуск продолжает) |
| `deploy/.env` | настройки стека (0600; шаблон `.env.example`) |

Язык интерфейса: английский по умолчанию, русский через `--lang ru` или `OCM_LANG=ru`; выбор сохраняется в `.install-state`, и `ocm` с `doctor.sh` говорят на нём же. Тексты в коде русские, английские лежат в `deploy/installer/messages_en.py` (тест следит, чтобы переведено было всё).

Шаги установки: `.env` → swap → Docker → сборка образов → базы и миграции → CA → администратор → все сервисы →
сертификаты → `ocm` → бэкапы (по желанию) → `doctor`. Логика за интерфейсами `Runner`, `Net`, `Prompter`, поэтому она
тестируется без сервера (`deploy/installer/tests`, запуск `pytest -c deploy/installer/pytest.ini`).

`ocm` (от root): `status` (= `scripts/doctor.sh`), `logs`, `update`, `rollback`, `backup-enable`, `backup`, `restore`,
`admin-chat`, `admin-password`. `update` отказывается работать при локальных правках и после слияния не fast-forward;
`ocm` не запускается, если код доступен на запись другим пользователям.

## Резервные копии (по желанию)

Один файл `ocmanager-<дата>.tar.gz.enc` в `/var/backups/ocmanager`: `pg_dump`, том `pki` (CA), `.env`. Шифрование
`openssl enc -aes-256-cbc -pbkdf2` ключом из `/root/.ocmanager-backup-key` (0600). Хранятся 14 последних; запуск systemd-таймером
ежедневно в 03:30; при сбое админу приходит алерт, а `doctor` краснеет, если успешной копии нет больше 36 часов.
Восстановление сначала проверяет файл и ключ, потом снимает аварийную копию и только затем останавливает сервисы.

## Диагностика

`scripts/doctor.sh` (или `ocm status`): контейнеры, порты, сертификаты обоих доменов, публичный API, `/internal` снаружи
закрыт, ocserv healthy, CRL, свежесть сверки ноды, ограничения docker-proxy, свежесть бэкапа.
`scripts/check-deploy-configs.sh` проверяет конфиги Caddy, nginx, haproxy и compose без запуска стека (его же гоняет CI).

## CI

| Воркфлоу | Что проверяет |
|---|---|
| `backend.yml` | ruff, mypy, границы модулей, pytest, интеграционные тесты с живым ocserv, конфиги деплоя |
| `admin.yml`, `tma.yml` | typecheck, lint, тесты, сборка |
| `installer.yml` | тесты установщика на Python 3.12 и 3.10, ruff, shellcheck, `bash -n`, конфиги деплоя |
