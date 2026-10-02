# Бэкенд ocmanager — Фаза 7 «Продакшн-сборка и доставка»: пошаговый план

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ САБ-СКИЛЛ — используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения плана задача за задачей.
> Шаги размечены чекбоксами (`- [ ]`) для отслеживания прогресса.
>
> **Этот план исполняется вручную:** код из каждого шага набирается руками,
> Claude проверяет результат по команде («проверь задачу 7.N»).

**Дата:** 2026-10-02
**Основание:** [дорожная карта бэкенда](2026-09-22-backend-implementation.md) (Фаза 7,
Global Constraints) · [план Фазы 6](2026-10-02-backend-phase-6.md) (бот — третий процесс) ·
[план TMA](2026-09-03-tma-mock-first-implementation.md) (Задача 21: production-сборка) ·
[SaaS-дизайн](../specs/2026-09-02-ocmanager-saas-design.md) §4.4, §9, §11 ·
[стек и структура](../specs/2026-09-02-ocmanager-stack-and-structure.md) §1.7, §2.5

**Goal:** Чистый сервер с двумя доменами поднимается по `deploy/.env.example` командами из
`deploy/README.md`, без правки исходников: один образ бэкенда в четырёх ролях (`api-public`, `api-admin`,
`worker`, `bot`), образ ocserv, статика Mini App, nginx-мультиплексор по SNI, Caddy с настоящими
сертификатами Let's Encrypt для обоих доменов. Снаружи открыты только 80 и 443 (TCP и UDP); админка — только
через SSH-туннель; ни один прикладной контейнер не получает права на Docker шире «управлять одной нодой».
CI на каждый PR гоняет юнит-тесты, образы и интеграционный набор с настоящим ocserv.

**Architecture:** Пять сетей изолируют роли: `edge` (nginx, caddy, ocserv), `web` (caddy ↔ api-public),
`hooks` (ocserv ↔ api-public, без выхода наружу), `app` (процессы бэкенда, Postgres, Redis), `docker`
(HAProxy-прокси к сокету ↔ worker и api-admin). TCP на 443 принимает nginx (`ssl_preread`) и по SNI отдаёт
соединение ocserv или Caddy, добавляя PROXY-заголовок с настоящим адресом клиента; UDP 443 (DTLS) идёт прямо
в ocserv. Caddy выпускает сертификаты обоих доменов (HTTP-01 на :80) и кладёт их в общий том; ocserv читает
свой сертификат оттуда, а воркер следит за отпечатком файла и просит ocserv перечитать его при продлении.

**Tech Stack:** Docker 24+ / Compose v2 · nginx 1.27 (stream) · Caddy 2.8 · HAProxy 3.0 · Debian trixie
(ocserv) · python:3.12-slim · uv 0.11 · GitHub Actions · bash.

---

## Статус реализации

**Реализовано и проверено локально 2026-10-02** (коммиты `96164f5` … `30da1b8`): задачи 7.1–7.9 и README из
7.10. Проверено на dev-стенде: образы собираются и все роли стартуют; интеграционный набор с живым ocserv
(28 тестов) зелёный; PROXY-протокол ocserv (без заголовка — отказ, с заголовком — ответ, healthcheck
`healthy`); белый список HAProxy (`check.sh`); Caddy с внутренним CA (маршруты, SPA-фоллбэк, `/internal` → 404,
нет `X-Frame-Options`, редирект с :80 без порта, отказ без PROXY-заголовка); цепочка nginx → Caddy и
nginx → ocserv на подсети `172.29.10.0/24`; запуск части боевого compose (`postgres`, `redis`, `migrate`,
`api-public`, `api-admin`, `worker`, `docker-proxy`) с `pki init` и `admin create` в контейнерах; `make check`
и тесты TMA. **Не проверено** (нужны внешние ресурсы): шаги 4–5 Задачи 7.9 (PR в GitHub, красный/зелёный
прогон), вся Задача 7.10 кроме README (чистый VPS, два домена, настоящий Let's Encrypt, iPhone), прогон
`doctor.sh` на Linux-сервере.

**Что вскрыла реализация и чем план отличается от первоначального текста ниже:**

1. **`httpx` был только в dev-зависимостях**, а воркер (Фаза 6) импортирует его при старте: образ без dev-пакетов
   падал с `ModuleNotFoundError`. Перенесён в основные зависимости (`96164f5`) — шаг 5 Задачи 7.1 это и ловит.
2. **Мок-клиент попадал в production-бандл** отдельным чанком: `env.apiMode` вычисляется в рантайме, и сборщик
   не мог убрать динамический `import("./mock/…")`. Импорт привязан к константе
   `import.meta.env.VITE_API_MODE !== "http"` (`frontend/tma/src/api/index.ts`) — только после этого
   `build.test.ts` стал зелёным (Задача 7.3).
3. **`docker logs` ходит за логами по полному ID контейнера**, а не по имени, поэтому ACL `logs` в HAProxy
   разрешает `ocm-ocserv` **или** 64 hex-символа; чужой ID через прокси не узнать (`inspect` разрешён только для
   ocserv). В `check.sh` добавлена проверка «logs чужого контейнера по имени запрещён» (Задача 7.4).
4. **Сервис `cli` в compose получил `entrypoint: ["ocmanager"]`**: `docker compose run --rm cli pki init`
   подменяет `command` целиком, и роль образа `cli` не находилась (Задача 7.7).

---

## Статус проверки — прочтите перед началом

Как и планы Фаз 5 и 6, **этот план не прогонялся по задачам на чистой копии**: код и конфиги написаны по
фактическим файлам репозитория на коммите `c32a998` (прочитаны `ocserv/*`, `deploy/docker-compose.dev.yml`,
`backend/Makefile`, `apps/*`, `core/config.py`, `nodes/driver/local_docker.py`, `tests/integration/*`,
`.github/workflows/backend.yml`, `frontend/tma/src/env.ts`). Проверено руками только одно: **ocserv 1.3.0 в
вашем образе знает опцию `listen-proxy-proto`** (`ocserv -t` не выдаёт «unknown option»). Остальное — по
документации и опыту, поэтому рядом с каждым конфигом стоит команда, которая его проверяет. Заведомо
рискованные места, где синтаксис мог не совпасть с вашей версией:

- блок `servers :8443 { listener_wrappers { proxy_protocol … tls } }` в Caddyfile (Задача 7.5);
- `proxy_pass $variable` со значением `host:port` и `resolver` в `stream` nginx (Задача 7.5);
- ACL-регулярки HAProxy и «туннельный» режим для `docker exec` / `docker logs -f` (Задача 7.4);
- наличие `/dev/net/tun` на раннере GitHub (Задача 7.9).

Правила те же: перед `make check` — `make fmt`; если что-то краснеет не так, как написано в «Ожидается», —
**пришлите вывод**, исправим план и конфиг вместе, не подгоняйте молча.

---

## Global Constraints

Действуют **все** пункты Global Constraints [дорожной карты](2026-09-22-backend-implementation.md#global-constraints).
Для Фазы 7 ключевые из них:

- **Процесс `api-public` не имеет доступа к Docker** — ни сокета, ни прокси. `bot` — тоже. Docker нужен только
  `worker` и `api-admin`, и только через прокси с белым списком (Задача 7.4). Сырой `docker.sock` не монтируется
  ни в один прикладной контейнер.
- **Снаружи открыты только `80/tcp`, `443/tcp`, `443/udp`.** Postgres и Redis порты не публикуют. `api-admin`
  публикуется как `127.0.0.1:8080:8080`.
- **`/internal/*` наружу не проксируется** и отвечает `404` (а не страницей Mini App из SPA-фоллбэка).
- **Приватный ключ CA (`ca.key`) — файл `0600`** в томе `pki`; в контейнер ocserv и в Caddy том не монтируется.
- **Секреты — только в `deploy/.env`** (в `.gitignore`), в образы не попадают (`.dockerignore`), в логи не
  попадают (уже обеспечено `core/logging.py`).
- **Production-сборка Mini App не содержит моков:** режим API — `http`, dev-панель выключена, поддельной
  `initData` в бандле нет. Проверяется тестом на собранном `dist` (Задача 7.3).
- **`OCM_ENV=production`** в боевом compose: `config.py` тогда запрещает `tma_allow_dev_initdata` и требует
  `https://` в `public_base_url`.
- **Время — только `core/clock.utcnow()`**; новая логика воркера (Задача 7.6) тестируется с подменой часов.
- **Граница модулей** (`make boundaries`): правки Фазы 7 в Python — только `flows/`, `apps/`, `core/config.py`.
- Коммиты: `chore(deploy): …`, `chore(backend): …`, `chore(ocserv): …`, `chore(ci): …`, `feat(backend): …`,
  `feat(tma): …`. Файлы в `docs/` — через `git add -f`.

---

## Review Focus

Входы и условия, которые спека подразумевает, но которые не очевидны из описания задач и больше всего
угрожают владельцу сервера и его клиентам. Ожидаемое поведение и проверка, которая его закрепляет:

1. **Все клиенты приходят с адреса nginx.** Без PROXY-протокола ocserv начисляет штрафные очки за неудачные
   подключения адресу nginx, и один сканер банит весь сервис (`max-ban-score`); аудит и лимиты TMA видят
   адрес Caddy вместо клиентского. Ожидается: ocserv и api-public видят настоящий адрес. *Проверки:*
   Задача 7.2, шаг «прямой запрос без PROXY отклоняется»; Задача 7.10, шаг «в `occtl show users` — адрес
   клиента, а не `172.29.10.x`»; строка `doctor.sh` про приём PROXY.
2. **Сертификат продлён, а ocserv держит старый.** Через 60–90 дней клиенты внезапно не подключаются, панель
   зелёная. Ожидается: воркер замечает смену файла и делает `occtl reload`; неудавшийся reload повторяется;
   исчезнувший файл — предупреждение, а не падение. *Тесты:* `test_a_renewed_certificate_reloads_the_node`,
   `test_a_failed_reload_is_retried_next_time`, `test_a_missing_certificate_file_is_reported_not_raised`.
3. **Взломанный `worker` или `api-admin` получает root на хосте через Docker API.** Ожидается: через прокси
   доступны только `inspect`, `logs`, `exec`, `start|stop|restart` **одного** контейнера; `docker run`,
   `docker ps`, `docker exec` в Postgres — `403`. *Проверка:* `deploy/docker-proxy/check.sh` (локально и в CI).
4. **Mini App уходит в бой на моках или с dev-панелью.** По умолчанию `VITE_API_MODE=mock` (`src/env.ts`):
   сборка без `.env.production` молча отдаёт поддельный API. Ожидается: сборка образа падает, если в бандле
   есть моки. *Тесты:* `src/build.test.ts` (4 проверки), он же — шаг сборки Dockerfile.
5. **Холодный старт на чистом сервере.** Нет CA, нет CRL, нет сертификата (Caddy выпускает его минуты спустя
   после старта), миграции не накатаны. Ожидается: ocserv ждёт сертификат и CRL и не уходит в вечный рестарт;
   прикладные процессы ждут миграцию; порядок команд в README исполняется без правок. *Проверка:* Задача
   7.10 на чистом VPS.
6. **`/internal/session-end` через SPA-фоллбэк.** `try_files {path} /index.html` отдаст на любой путь `200` со
   страницей Mini App. Ожидается: явный `404` и для GET, и для POST. *Проверка:* строка `doctor.sh`.
7. **Админка слушает внешний интерфейс.** Ожидается: `ss` показывает `127.0.0.1:8080`, и больше ничего на
   `:8080`. *Проверка:* строка `doctor.sh`.

---

## Решения, принятые при детализации

| # | Решение | Почему | Где живёт |
|---|---|---|---|
| П7-1 | **Прокси к Docker — HAProxy с белым списком путей, а не `tecnativa/docker-socket-proxy`** (дорожная карта) | У tecnativa доступ задаётся разделами API, а не контейнерами: `CONTAINERS=1` + `POST=1` разрешают в том числе `POST /containers/create`, то есть запуск привилегированного контейнера с корнем хоста — прокси ничего не защищает. HAProxy разрешает ровно перечисленные запросы к одному имени контейнера | `deploy/docker-proxy/` |
| П7-2 | **PROXY-протокол v1 на TCP:** nginx отправляет заголовок и в ocserv (`listen-proxy-proto`), и в Caddy (`listener_wrappers`). UDP 443 идёт мимо nginx | Без него адрес клиента теряется (Review Focus №1). `listen-proxy-proto` проверен в образе. Для healthcheck ocserv: `curl --haproxy-protocol` | `ocserv/`, `deploy/nginx`, `deploy/caddy` |
| П7-3 | **Сеть `edge` с фиксированной подсетью `172.29.10.0/24`** | Caddy принимает PROXY-заголовок только от адресов из `allow`; динамическая подсеть Docker не позволила бы их перечислить. Конфликт с вашей сетью — единственная цена, правится в двух местах (compose и Caddyfile) | `deploy/docker-compose.yml`, `Caddyfile` |
| П7-4 | **Caddy слушает `https_port 8443`, автоматические редиректы выключены, редирект на https — явный блок `http://`** | Автоматический редирект Caddy подставил бы в `Location` порт 8443, снаружи недоступный. HTTP-01 для обоих доменов работает на :80 | `deploy/caddy/Caddyfile` |
| П7-5 | **Конфиг nginx собирается из шаблона `envsubst` в `command`; имена контейнеров резолвятся при каждом соединении (`resolver 127.0.0.11`)** | nginx не читает переменные окружения; пересоздание ocserv или caddy меняет IP, а статический `upstream` держал бы старый до перезапуска | `deploy/nginx/nginx.conf.template` |
| П7-6 | **Неизвестный SNI и соединения без SNI уходят в Caddy, а не в ocserv** | Сканеры по IP не должны попадать на шлюз с камуфляжем | `deploy/nginx` |
| П7-7 | **ocserv читает сертификат из тома Caddy** (`/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<домен>/<домен>.crt`), **воркер следит за отпечатком** файла (`OCM_SERVER_CERT_PATH`), cron `check_server_cert` раз в 6 часов; reload — при любом отличии отпечатка от запомненного в Redis, включая первый просмотр | Один ACME-клиент (спека §1.7). Reload дешёвый и не обрывает сессии, поэтому лишний reload при пустом Redis безопаснее пропущенного | `flows/nodes.py`, `apps/worker.py` |
| П7-8 | **Образ бэкенда: непривилегированный пользователь `app` (uid 10001), `docker` CLI копируется из `docker:27-cli`**, а не ставится из apt-репозитория Docker | Статический бинарь без ключей и репозиториев; образ один для всех ролей (спека §2.1) | `backend/Dockerfile` |
| П7-9 | **Права на тома выставляет одноразовый сервис `volume-init`** (`chown 10001`) | Именованный том наследует владельца от образа того контейнера, который смонтировал его первым; ocserv и бэкенд делят `ocserv-state`, и результат зависел бы от порядка запуска | compose |
| П7-10 | **`api-public` запускается с `--proxy-headers --forwarded-allow-ips '*'`; `api-admin` — без** | За Caddy `request.client.host` иначе всегда адрес Caddy — аудит и лимиты по IP теряют смысл. `*` безопасно: порт не публикуется, достучаться могут только Caddy (он перезаписывает `X-Forwarded-For`) и ocserv по сети `hooks`; `/internal` проверяет адрес **и** секрет. У `api-admin` адрес клиента — шлюз Docker (SSH-туннель на loopback); принято | `docker-entrypoint.sh` |
| П7-11 | **Redis с паролем, Postgres и Redis без публикации портов** | `api-public` смотрит в интернет; пароль — дешёвая вторая линия | compose |
| П7-12 | **`ocserv-state` смонтирован в ocserv только на чтение, `pki` — только на чтение везде, кроме одноразового сервиса `cli`** | Нода не должна менять allowlist и CRL; ключ CA не должен быть доступен записи из процессов, смотрящих наружу | compose |
| П7-13 | **Mini App собирается в образ `web` (Caddy + `dist`), Caddyfile монтируется файлом**; сборка запускает `build.test.ts` и падает при моках | Правка конфига не требует пересборки; мок в бандле не доживает до сервера | `deploy/web/Dockerfile` |
| П7-14 | **`frontend/tma/.env.production` коммитится** (не секрет); адрес поддержки — build-arg | Режим по умолчанию `mock` (Review Focus №4) | `frontend/tma/.env.production` |
| П7-15 | **Бэкапов нет** (дорожная карта: вне плана); в README — ручные команды и предупреждение: потеря тома `pki` = потеря всех выданных ключей | Автоматические бэкапы с шифрованием — отдельная задача этапа 1.5 | `deploy/README.md` |
| П7-16 | **CI-прогон интеграционных тестов не накатывает миграции в dev-базу** | `conftest.py` строит тестовую БД через Alembic сам; лишний шаг только удлиняет прогон | `.github/workflows/backend.yml` |

### Отклонения от дорожной карты

- Задач десять вместо трёх: образ ocserv (7.2), образ Mini App (7.3), прокси Docker (7.4), прокси и TLS (7.5),
  слежение за сертификатом (7.6), `doctor.sh` (7.8) и README (7.10) вынесены из «7.2» в отдельные.
- Задача 21 плана TMA (production-сборка, Caddyfile) **не была выполнена** — она поглощена задачами 7.3 и 7.5.
- Файл `deploy/docker-compose.tma.yml` из плана TMA не создаётся: Mini App входит в общий compose.
- Фильтр «только контейнер `ocserv`» реализован ACL по имени контейнера (П7-1), а не флагами tecnativa.

### Отложено (не входит в фазу)

- Автоматические бэкапы Postgres и PKI (П7-15), установщик `install.sh` и веб-визард (этап 3).
- Мониторинг и сбор логов за пределами `json-file` с ротацией.
- Второй сервер и `RemoteAgentDriver` (этап 4).

---

## Карта файлов

```
.github/workflows/backend.yml                 (7.9, переписывается)
.github/workflows/tma.yml                     (7.9)
.dockerignore                                 (7.3, для контекста — корень репозитория)
scripts/doctor.sh                             (7.8)
scripts/check-deploy-configs.sh               (7.5, дополняется в 7.4, 7.7)
backend/
├── Dockerfile  .dockerignore  docker-entrypoint.sh      (7.1)
└── src/ocmanager/
    ├── core/config.py                                   (7.6: server_cert_path)
    ├── flows/nodes.py  flows/test_nodes.py              (7.6)
    └── apps/worker.py  apps/test_worker.py              (7.6)
ocserv/
├── Dockerfile  entrypoint.sh  ocserv.conf.tmpl          (7.2)
└── healthcheck.sh                                       (7.2)
frontend/tma/
├── .env.production                                      (7.3)
└── src/build.test.ts                                    (7.3)
deploy/
├── docker-compose.yml  .env.example  README.md          (7.7, 7.10)
├── web/Dockerfile                                       (7.3)
├── caddy/Caddyfile                                      (7.5)
├── nginx/nginx.conf.template                            (7.5)
└── docker-proxy/haproxy.cfg  check.sh                   (7.4)
```

---

### Задача 7.1: Образ бэкенда

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `backend/docker-entrypoint.sh`

**Interfaces:**
- Produces: образ `ocmanager/backend`; вызов `docker run <image> <роль> [аргументы]`, роли:
  `api-public` (:8000), `api-admin` (:8080), `worker`, `bot`, `migrate` (`alembic upgrade head`),
  `cli …` (то же, что `ocmanager …`). Рабочий каталог `/app`, пользователь `app` (uid 10001), каталоги
  `/var/lib/ocmanager` и `/var/lib/ocmanager-pki` принадлежат `app`.

- [ ] **Шаг 1: `backend/.dockerignore`.** Контекст сборки — `backend/`; `.env` с секретами в него попадать не
  должен.

```
.venv
.env
.env.*
!.env.example
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
tests
scripts
```

- [ ] **Шаг 2: `backend/docker-entrypoint.sh`**

```sh
#!/bin/sh
# Роли одного образа: docker run <image> <роль> [аргументы]. exec — чтобы сигналы
# (SIGTERM от docker stop) доходили до процесса, а не до оболочки.
set -eu

role="${1:-}"
[ "$#" -gt 0 ] && shift

case "$role" in
    api-public)
        # За Caddy адрес клиента приходит в X-Forwarded-For (решение П7-10).
        exec uvicorn ocmanager.apps.public_api:create_app --factory \
            --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' "$@"
        ;;
    api-admin)
        # Все интерфейсы контейнера; наружу порт публикуется только на 127.0.0.1 хоста.
        exec uvicorn ocmanager.apps.admin_api:create_app --factory \
            --host 0.0.0.0 --port 8080 "$@"
        ;;
    worker) exec python -m ocmanager.apps.worker "$@" ;;
    bot) exec python -m ocmanager.apps.bot "$@" ;;
    migrate) exec alembic upgrade head "$@" ;;
    cli) exec ocmanager "$@" ;;
    *)
        echo "роль: api-public | api-admin | worker | bot | migrate | cli <команда>" >&2
        exit 64
        ;;
esac
```

```bash
chmod +x backend/docker-entrypoint.sh
```

- [ ] **Шаг 3: `backend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Один образ для всех процессов бэкенда (спека §2.1); роль выбирает docker-entrypoint.sh.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Сначала зависимости: слой переиспользуется, пока не менялись pyproject.toml и uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
# Клиент Docker нужен только worker и api-admin (управление нодой через прокси, Задача 7.4),
# но образ один. Статический бинарь, без apt-репозитория Docker.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /var/lib/ocmanager /var/lib/ocmanager-pki
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api-public"]
```

- [ ] **Шаг 4: Собрать и посмотреть, что получилось**

```bash
cd backend
docker build -t ocmanager/backend:dev .
docker run --rm ocmanager/backend:dev cli --help | head -5
docker run --rm ocmanager/backend:dev nonsense; echo "exit=$?"
docker run --rm --entrypoint docker ocmanager/backend:dev --version
docker run --rm --entrypoint sh ocmanager/backend:dev -c 'id; ls /app; ls -ld /var/lib/ocmanager'
docker run --rm --entrypoint sh ocmanager/backend:dev -c 'test ! -e /app/.env && echo "нет .env"'
```
Ожидается: справка `ocmanager` на русском; для `nonsense` — строка про роли и `exit=64`; версия Docker
`27.x`; `uid=10001(app)`, в `/app` лежат `.venv`, `alembic`, `alembic.ini`, каталог принадлежит `app`; «нет
.env».

- [ ] **Шаг 5: Каждая роль стартует.** Dev-инфраструктура запущена (`make dev-up`); `backend/.env` — dev-файл.

```bash
cd backend
ENVS="--env-file .env -e OCM_DATABASE_URL=postgresql+asyncpg://ocm:ocm@host.docker.internal:54320/ocmanager -e OCM_REDIS_URL=redis://host.docker.internal:63790/0"

docker run --rm $ENVS ocmanager/backend:dev migrate 2>&1 | tail -3

docker run -d --name t-public $ENVS -p 127.0.0.1:18000:8000 ocmanager/backend:dev api-public
docker run -d --name t-admin  $ENVS -p 127.0.0.1:18080:8080 ocmanager/backend:dev api-admin
docker run -d --name t-worker $ENVS ocmanager/backend:dev worker
sleep 6
curl -fsS http://127.0.0.1:18000/api/health; echo
curl -fsS http://127.0.0.1:18080/admin/health; echo
docker logs t-worker 2>&1 | grep worker_started
docker rm -f t-public t-admin t-worker
```
Ожидается: `migrate` — «Running upgrade …» либо тишина (БД уже на `head`); оба health-ответа
`{"status":"ok"}`; в логах воркера `worker_started`. Если контейнер не стартует с «No such file or
directory» про `ocmanager.*` — `uv sync --no-editable` не положил пакет: пришлите вывод
`docker run --rm --entrypoint pip ocmanager/backend:dev list | grep ocmanager`.

- [ ] **Шаг 6: Коммит**

```bash
git add backend/Dockerfile backend/.dockerignore backend/docker-entrypoint.sh
git commit -m "chore(backend): production image with role-based entrypoint"
```

---

### Задача 7.2: Образ ocserv для продакшена

**Files:**
- Modify: `ocserv/ocserv.conf.tmpl`, `ocserv/entrypoint.sh`, `ocserv/Dockerfile`
- Create: `ocserv/healthcheck.sh`

**Interfaces:**
- Produces (новые переменные окружения контейнера ocserv, все необязательные, умолчания сохраняют dev):
  `OCSERV_PROXY_PROTOCOL` = `true|false` (по умолчанию `false`) — ждать PROXY-заголовок на TCP;
  `OCSERV_CERT_WAIT_S` — сколько секунд ждать появления серверного сертификата и ключа (по умолчанию `0`).

- [ ] **Шаг 1: Шаблон конфига.** В `ocserv/ocserv.conf.tmpl` после строки `udp-port = 443` добавьте:

```
# ocm: за nginx (прод) на TCP первым приходит PROXY-заголовок с настоящим адресом клиента.
# Без него max-ban-score начислялся бы адресу nginx — то есть всем клиентам сразу.
# UDP (DTLS) идёт мимо nginx и в PROXY не нуждается.
listen-proxy-proto = ${OCSERV_PROXY_PROTOCOL}
```

- [ ] **Шаг 2: `ocserv/entrypoint.sh`.** Три правки.

1) После строки `export OCSERV_MAX_BAN_SCORE=…`:

```sh
export OCSERV_PROXY_PROTOCOL="${OCSERV_PROXY_PROTOCOL:-false}"
case "$OCSERV_PROXY_PROTOCOL" in true | false) ;; *) die "OCSERV_PROXY_PROTOCOL: true или false" ;; esac
```

2) Перед циклом `for f in "$STATE_DIR/ca.crt" …`:

```sh
# В проде серверный сертификат выпускает Caddy и он появляется спустя минуты после старта.
waited=0
until [ -r "$OCSERV_SERVER_CERT" ] && [ -r "$OCSERV_SERVER_KEY" ]; do
    [ "$waited" -ge "${OCSERV_CERT_WAIT_S:-0}" ] && break
    [ "$waited" -eq 0 ] && echo "entrypoint: жду сертификат $OCSERV_SERVER_CERT…" >&2
    sleep 1
    waited=$((waited + 1))
done
```

3) Список `envsubst` дополните переменной:

```sh
envsubst '${OCSERV_SERVER_CERT} ${OCSERV_SERVER_KEY} ${OCSERV_IPV4_NETWORK} ${OCSERV_CAMOUFLAGE_SECRET} ${OCSERV_MAX_BAN_SCORE} ${OCSERV_PROXY_PROTOCOL}' \
```

- [ ] **Шаг 3: `ocserv/healthcheck.sh`.** При включённом PROXY-протоколе обычный запрос на 443 отклоняется,
  поэтому проверка сама отправляет заголовок.

```sh
#!/bin/sh
# Любой HTTP-ответ (даже страница камуфляжа) = TLS-слушатель жив.
proxy=""
[ "${OCSERV_PROXY_PROTOCOL:-false}" = "true" ] && proxy="--haproxy-protocol"
# shellcheck disable=SC2086 — $proxy пуст или один флаг
exec curl -ks $proxy -o /dev/null https://localhost:443/
```

- [ ] **Шаг 4: `ocserv/Dockerfile`.** Скопируйте скрипт и замените `HEALTHCHECK`:

```dockerfile
COPY --chmod=0755 entrypoint.sh /entrypoint.sh
COPY --chmod=0755 healthcheck.sh /healthcheck.sh
```
```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD ["/healthcheck.sh"]
```

- [ ] **Шаг 5: Dev-стенд не сломан** (умолчание `false`):

```bash
cd backend
make ocserv-up
docker inspect -f '{{.State.Health.Status}}' ocm-ocserv
make test-ocserv
```
Ожидается: `healthy`; интеграционный набор зелёный (как до правок).

- [ ] **Шаг 6: PROXY-протокол принимается и обязателен.** Включите его в уже запущенном контейнере и
  проверьте обе стороны (конфиг пересобирается на старте контейнера):

```bash
docker rm -f ocm-ocserv
cd backend && OCSERV_PROXY_PROTOCOL=true docker compose -f ../deploy/docker-compose.dev.yml --profile ocserv run -d --name ocm-ocserv-proxy -e OCSERV_PROXY_PROTOCOL=true ocserv
sleep 5
docker exec ocm-ocserv-proxy curl -ks -o /dev/null -w 'без PROXY: %{http_code}\n' --max-time 3 https://localhost:443/ || echo "без PROXY: отклонено"
docker exec ocm-ocserv-proxy curl -ks --haproxy-protocol -o /dev/null -w 'с PROXY: %{http_code}\n' --max-time 3 https://localhost:443/
docker inspect -f '{{.State.Health.Status}}' ocm-ocserv-proxy
docker rm -f ocm-ocserv-proxy
make ocserv-up   # вернуть обычный dev-контейнер
```
Ожидается: «без PROXY: отклонено» (или нулевой код ответа/ошибка соединения), «с PROXY: 401» или другой
HTTP-код, статус `healthy` (healthcheck использует `--haproxy-protocol`). Если без PROXY ответ всё же
приходит — опция не применилась: пришлите `docker exec ocm-ocserv-proxy grep proxy /etc/ocserv/ocserv.conf`.

- [ ] **Шаг 7: Коммит**

```bash
git add ocserv
git commit -m "chore(ocserv): proxy protocol, certificate wait and proxy-aware healthcheck"
```

---

### Задача 7.3: Образ Mini App и защита сборки от моков

**Files:**
- Create: `frontend/tma/.env.production`, `frontend/tma/src/build.test.ts`, `deploy/web/Dockerfile`, `.dockerignore`

**Interfaces:**
- Produces: образ `ocmanager/web` — Caddy 2.8 с собранной статикой в `/srv/tma`; конфиг Caddy монтируется
  снаружи (`/etc/caddy/Caddyfile`, Задача 7.5). Build-arg `VITE_SUPPORT_HANDLE`.

- [ ] **Шаг 1: Тест `frontend/tma/src/build.test.ts`.** Единственный тест проекта, которому нужна
  предварительная сборка; без `dist` пропускается.

```ts
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIST = join(import.meta.dirname, "..", "dist");

function bundleText(): string {
  const assets = join(DIST, "assets");
  return readdirSync(assets)
    .filter((file) => file.endsWith(".js"))
    .map((file) => readFileSync(join(assets, file), "utf8"))
    .join("\n");
}

describe.skipIf(!existsSync(DIST))("production-сборка", () => {
  it("не содержит поддельную initData", () => {
    expect(bundleText()).not.toContain("dev-mock-hash");
  });

  it("не содержит мок-клиента и его сценариев", () => {
    const text = bundleText();
    expect(text).not.toContain("окружение Telegram замокано");
    expect(text).not.toContain("Активный пробный период");
  });

  it("не содержит dev-панели", () => {
    expect(bundleText()).not.toContain("Мок-окружение");
  });

  it("index.html не выставляет X-Frame-Options через meta", () => {
    const html = readFileSync(join(DIST, "index.html"), "utf8");
    expect(html.toLowerCase()).not.toContain("x-frame-options");
  });
});
```

- [ ] **Шаг 2: `frontend/tma/.env.production`.** Режим по умолчанию — `mock` (`src/env.ts`), поэтому без
  файла production-сборка молча отдавала бы поддельный API.

```
VITE_API_MODE=http
VITE_API_BASE_URL=/api
VITE_DEV_PANEL=false
VITE_SUPPORT_HANDLE=@ocmanager_help
```

- [ ] **Шаг 3: Сначала доказать, что тест ловит моки.** Соберите **без** `.env.production` и убедитесь, что тест
  краснеет, затем с ним — зеленеет:

```bash
cd frontend/tma
mv .env.production /tmp/env.production.bak
npm run build && npm test -- src/build.test.ts; echo "exit=$?"
mv /tmp/env.production.bak .env.production
npm run build && npm test -- src/build.test.ts; echo "exit=$?"
```
Ожидается: в первом прогоне хотя бы одна проверка падает (`exit=1`) — мок попал в бандл; во втором
`4 passed`, `exit=0`. Если первый прогон тоже зелёный — мок отсекается уже на уровне `import.meta.env.DEV`, и
тест всё равно полезен как страховка от будущей регрессии; пришлите вывод, если сомневаетесь.

- [ ] **Шаг 4: Размер бандла**

```bash
du -sh dist/assets/*.js | sort -h
```
Ориентир из плана TMA: главный чанк до 250 КБ без сжатия. Превышение почти всегда означает, что ленивый
импорт экрана стал статическим.

- [ ] **Шаг 5: `.dockerignore` в корне репозитория.** Контекст сборки образа `web` — корень репозитория (в
  нём лежит `frontend/`); без этого файла в контекст уедут `node_modules`, `.dev` с ключами и вся история.

```
.git
.dev
docs
backend
ocserv
**/node_modules
**/dist
**/.env
**/.venv
```

- [ ] **Шаг 6: `deploy/web/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Mini App: сборка статики и раздача её Caddy. Контекст — корень репозитория:
#   docker build -f deploy/web/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /tma
COPY frontend/tma/package.json frontend/tma/package-lock.json ./
RUN npm ci
COPY frontend/tma ./
# Адрес поддержки — на установку (переопределяет .env.production).
ARG VITE_SUPPORT_HANDLE=@ocmanager_help
ENV VITE_SUPPORT_HANDLE=$VITE_SUPPORT_HANDLE
# Сборка падает, если в бандл попал мок (Review Focus №4).
RUN npm run build && npm test -- src/build.test.ts

FROM caddy:2.8-alpine
COPY --from=build /tma/dist /srv/tma
# Caddyfile монтируется из deploy/caddy/ (Задача 7.5): правка конфига не требует пересборки.
```

- [ ] **Шаг 7: Собрать образ**

```bash
cd ../..    # корень репозитория
docker build -f deploy/web/Dockerfile -t ocmanager/web:dev .
docker run --rm --entrypoint sh ocmanager/web:dev -c 'ls /srv/tma && grep -c "dev-mock-hash" /srv/tma/assets/*.js | grep -v ":0" || echo "моков нет"'
```
Ожидается: `index.html`, `assets`, `fonts` …; «моков нет».

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/.env.production frontend/tma/src/build.test.ts deploy/web/Dockerfile .dockerignore
git commit -m "feat(tma): production env, mock-free build guard and web image"
```

---

### Задача 7.4: Прокси к Docker с белым списком

**Files:**
- Create: `deploy/docker-proxy/haproxy.cfg`, `deploy/docker-proxy/check.sh`

**Interfaces:**
- Produces: HAProxy на `:2375` внутри сети `docker`; `DOCKER_HOST=tcp://docker-proxy:2375` для `worker` и
  `api-admin`. Разрешено (имя контейнера фиксировано — `ocm-ocserv`, как `OCM_OCSERV_CONTAINER` по умолчанию):

| Запрос | Что делает `docker` CLI |
|---|---|
| `GET\|HEAD /_ping` | согласование версии API |
| `GET /containers/ocm-ocserv/json` | `docker inspect`, проверка перед `logs`/`exec` |
| `GET /containers/{ocm-ocserv или 64 hex}/logs` | `docker logs -f` (live-логи админки; CLI просит логи по ID) |
| `POST /containers/ocm-ocserv/{exec,start,stop,restart}` | `occtl` через `docker exec`; действия над нодой |
| `POST /exec/<64 hex>/start`, `GET /exec/<64 hex>/json` | запуск созданного exec и код возврата |

Всё остальное — `403`: `docker ps`, `docker run`, `docker exec` в любой другой контейнер, `create`, `images`,
`volumes`, `networks`, `info`.

- [ ] **Шаг 1: `deploy/docker-proxy/haproxy.cfg`**

```
# Прокси к Docker API с белым списком запросов (решение П7-1). Монтируется в haproxy:3.0-alpine.
# Имя контейнера ocserv зашито: оно же — container_name в docker-compose.yml.
global
    log stdout format raw local0
    maxconn 64

defaults
    mode http
    log global
    option httplog
    timeout connect 5s
    timeout client 1h
    timeout server 1h
    timeout tunnel 1h

frontend docker
    bind :2375

    # Префикс версии API (/v1.47/…) необязателен.
    acl ping       path_reg ^(/v[0-9.]+)?/_ping$
    acl inspect    path_reg ^(/v[0-9.]+)?/containers/ocm-ocserv/json$
    # docker logs: CLI сначала делает inspect по имени, а логи просит уже по полному ID контейнера.
    # Чужой ID через прокси не узнать (inspect разрешён только для ocm-ocserv), а подобрать
    # 64 hex-символа нельзя: логи читаются только у контейнера, чей ID уже выдал разрешённый inspect.
    acl logs       path_reg ^(/v[0-9.]+)?/containers/(ocm-ocserv|[0-9a-f]{64})/logs$
    acl actions    path_reg ^(/v[0-9.]+)?/containers/ocm-ocserv/(exec|start|stop|restart)$
    acl exec_start path_reg ^(/v[0-9.]+)?/exec/[0-9a-f]{64}/start$
    acl exec_json  path_reg ^(/v[0-9.]+)?/exec/[0-9a-f]{64}/json$

    http-request allow if ping { method GET HEAD }
    http-request allow if inspect { method GET }
    http-request allow if logs { method GET }
    http-request allow if actions { method POST }
    http-request allow if exec_start { method POST }
    http-request allow if exec_json { method GET }
    http-request deny deny_status 403

    default_backend engine

backend engine
    server docker /var/run/docker.sock
```

- [ ] **Шаг 2: `deploy/docker-proxy/check.sh`.** Поднимает прокси на локальном порту против настоящего
  сокета и проверяет разрешённое и запрещённое. Нужен запущенный контейнер `ocm-ocserv` (`make ocserv-up`) и
  любой второй контейнер, например dev-Postgres.

```bash
#!/usr/bin/env bash
# Проверка белого списка прокси к Docker. Из корня репозитория:
#   make -C backend ocserv-up && deploy/docker-proxy/check.sh
set -uo pipefail
cd "$(dirname "$0")"

PORT=23750
NAME=ocm-proxy-check
OTHER=$(docker ps --format '{{.Names}}' | grep -v -e '^ocm-ocserv$' -e "^$NAME$" | head -n1)
fails=0

docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --user 0:0 -p "127.0.0.1:$PORT:2375" \
    -v "$PWD/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    haproxy:3.0-alpine >/dev/null || exit 1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
sleep 2
export DOCKER_HOST="tcp://127.0.0.1:$PORT"

allow() { if "${@:2}" >/dev/null 2>&1; then echo "  OK   разрешено: $1"; else echo "  FAIL разрешено, но отказано: $1"; fails=$((fails + 1)); fi; }
deny()  { if "${@:2}" >/dev/null 2>&1; then echo "  FAIL запрещено, но прошло: $1"; fails=$((fails + 1)); else echo "  OK   запрещено: $1"; fi; }

allow "inspect ocserv"      docker inspect -f '{{.State.Status}}' ocm-ocserv
allow "exec occtl"          docker exec ocm-ocserv occtl -j show status
allow "logs ocserv"         docker logs --tail 3 ocm-ocserv
allow "restart ocserv"      docker restart ocm-ocserv
deny  "docker ps"           docker ps
deny  "docker images"       docker images
deny  "docker run"          docker run --rm alpine true
deny  "docker info"         docker info
if [ -n "$OTHER" ]; then
    deny "exec в чужой контейнер ($OTHER)" docker exec "$OTHER" id
    deny "inspect чужого контейнера"       docker inspect "$OTHER"
    deny "stop чужого контейнера"          docker stop "$OTHER"
    deny "logs чужого контейнера по имени" docker logs --tail 1 "$OTHER"
fi

[ "$fails" -eq 0 ] && echo "прокси: всё как задумано" || { echo "прокси: ошибок $fails"; exit 1; }
```

```bash
chmod +x deploy/docker-proxy/check.sh
```

- [ ] **Шаг 3: Запустить**

```bash
cd backend && make ocserv-up && cd ..
deploy/docker-proxy/check.sh
```
Ожидается: четыре `OK разрешено`, остальные (включая logs чужого контейнера) `OK запрещено`, итог «прокси: всё как задумано». Если
`exec occtl` не проходит — пришлите вывод `docker logs ocm-proxy-check` (первая причина обычно в regexp ACL или
в версии API); если `logs` обрывается — таймаут `timeout tunnel`.

- [ ] **Шаг 4: Живой стрим логов через прокси** (то, что делает админка по SSE):

```bash
# check.sh удаляет прокси при выходе — поднимаем заново вручную:
docker run -d --name ocm-proxy-check --user 0:0 -p 127.0.0.1:23750:2375 \
  -v "$PWD/deploy/docker-proxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock haproxy:3.0-alpine
(sleep 3; docker restart ocm-ocserv >/dev/null) &
DOCKER_HOST=tcp://127.0.0.1:23750 timeout 10 docker logs -f --tail 2 ocm-ocserv; echo "exit=$?"
docker rm -f ocm-proxy-check
```
Ожидается: старые строки, затем новые строки старта ocserv (после `restart`), `exit=124` от `timeout`.

- [ ] **Шаг 5: Коммит**

```bash
git add deploy/docker-proxy
git commit -m "chore(deploy): allow-list proxy to the docker api limited to the ocserv container"
```

---

### Задача 7.5: SNI-мультиплексор, Caddy и TLS

**Files:**
- Create: `deploy/nginx/nginx.conf.template`, `deploy/caddy/Caddyfile`, `scripts/check-deploy-configs.sh`

**Interfaces:**
- Consumes: сервисы compose `ocserv` (:443 TCP, PROXY v1), `caddy` (:8443, PROXY v1), `api-public` (:8000);
  переменные `DOMAIN_APP`, `DOMAIN_VPN`, `ACME_EMAIL`; сеть `edge` с подсетью `172.29.10.0/24` (П7-3).
- Produces: TCP 443 → по SNI в ocserv (домен VPN) или в Caddy (всё остальное); Caddy выпускает сертификаты
  обоих доменов и кладёт их в `/data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<домен>/`.

- [ ] **Шаг 1: `deploy/nginx/nginx.conf.template`.** Только `${DOMAIN_VPN}` подставляется `envsubst`; остальные `$`
  — переменные nginx.

```nginx
# L4-мультиплексор по SNI (спека §1.7, §4.4). Трафик не расшифровывается.
worker_processes auto;
error_log /dev/stderr warn;
pid /tmp/nginx.pid;

events { worker_connections 4096; }

stream {
    # Docker-DNS: имена резолвятся при каждом соединении, поэтому пересоздание ocserv или caddy
    # (новый IP) не требует перезапуска nginx (решение П7-5).
    resolver 127.0.0.11 valid=10s ipv6=off;

    map $ssl_preread_server_name $backend {
        "${DOMAIN_VPN}"  ocserv:443;
        default          caddy:8443;   # включая соединения без SNI (решение П7-6)
    }

    server {
        listen 443;
        ssl_preread on;
        proxy_pass $backend;
        # Настоящий адрес клиента для ocserv и Caddy (решение П7-2).
        proxy_protocol on;
        proxy_connect_timeout 5s;
    }
}
```

- [ ] **Шаг 2: `deploy/caddy/Caddyfile`.** Подсеть в `allow` — та же, что у `edge` в compose.

```caddy
# Caddy: сертификаты обоих доменов (HTTP-01 на :80), прокси панели и статика Mini App.
# TLS на 443 для APP терминирует Caddy на :8443 (за nginx), для VPN — сам ocserv.
{
	email {$ACME_EMAIL}

	# Снаружи 443 принимает nginx; Caddy слушает 8443.
	https_port 8443
	# Автоматический редирект подставил бы :8443 в Location (решение П7-4) — делаем свой.
	auto_https disable_redirects

	servers :8443 {
		listener_wrappers {
			# Настоящий адрес клиента от nginx; принимаем заголовок только из сети edge (П7-3).
			proxy_protocol {
				timeout 5s
				allow 172.29.10.0/24
			}
			tls
		}
	}
}

http:// {
	redir https://{host}{uri} permanent
}

# Сертификат этого домена нужен ocserv. Для него nginx направляет соединения мимо Caddy,
# так что блок существует ради выпуска и продления сертификата.
{$DOMAIN_VPN} {
	respond 404
}

{$DOMAIN_APP} {
	encode gzip

	header {
		Referrer-Policy strict-origin-when-cross-origin
		X-Content-Type-Options nosniff
		# Mini App открывается в iframe веб-клиента Telegram: заголовок даёт белый экран без ошибок.
		-X-Frame-Options
	}

	handle /api/* {
		reverse_proxy api-public:8000
	}

	handle /webhooks/* {
		reverse_proxy api-public:8000
	}

	# Явный 404: иначе SPA-фоллбэк ниже ответил бы 200 страницей Mini App (Review Focus №6).
	handle /internal/* {
		respond 404
	}

	handle {
		root * /srv/tma
		try_files {path} /index.html
		file_server
	}
}
```

- [ ] **Шаг 3: `scripts/check-deploy-configs.sh`.** Проверяет конфиги без запуска стека; потом им же пользуется CI.

```bash
#!/usr/bin/env bash
# Проверка конфигов деплоя без запуска стека. Из корня репозитория: scripts/check-deploy-configs.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export DOMAIN_APP=app.example.com DOMAIN_VPN=vpn.example.com ACME_EMAIL=admin@example.com

echo "== caddy"
docker run --rm -e DOMAIN_APP -e DOMAIN_VPN -e ACME_EMAIL \
    -v "$PWD/deploy/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

echo "== nginx"
docker run --rm -e DOMAIN_VPN \
    -v "$PWD/deploy/nginx/nginx.conf.template:/t:ro" \
    nginx:1.27-alpine sh -c "envsubst '\${DOMAIN_VPN}' </t >/etc/nginx/nginx.conf && nginx -t"

echo "== haproxy"
docker run --rm \
    -v "$PWD/deploy/docker-proxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
    haproxy:3.0-alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg

if [ -f deploy/docker-compose.yml ]; then
    echo "== compose"
    docker compose -f deploy/docker-compose.yml --env-file deploy/.env.example config -q
fi
echo "конфиги валидны"
```

```bash
chmod +x scripts/check-deploy-configs.sh
```

- [ ] **Шаг 4: Запустить**

```bash
scripts/check-deploy-configs.sh
```
Ожидается: `Valid configuration` от Caddy, `syntax is ok` и `test is successful` от nginx, `Configuration file
is valid` от HAProxy, итог «конфиги валидны». Раздел «compose» появится после Задачи 7.7. **Если Caddy не
принял `listener_wrappers` или `proxy_protocol`** — пришлите вывод `caddy validate`: синтаксис этих блоков
зависит от версии, поправим по `caddy adapt`.

- [ ] **Шаг 5: Коммит**

```bash
git add deploy/nginx deploy/caddy scripts/check-deploy-configs.sh
git commit -m "chore(deploy): sni multiplexer, caddy tls for both domains and config checks"
```

---

### Задача 7.6: Слежение за серверным сертификатом

**Files:**
- Modify: `backend/src/ocmanager/core/config.py`, `flows/nodes.py`, `flows/test_nodes.py`, `apps/worker.py`, `apps/test_worker.py`

**Interfaces:**
- Consumes: `NodeDriver.reload()`, `registry.get_active_nodes(session)`, `registry.driver_for(node, settings)`,
  `FakeNodeDriver` (записывает вызовы в `.calls`).
- Produces:

```python
# core/config.py
server_cert_path: Path | None = None        # OCM_SERVER_CERT_PATH; None — слежения нет (dev)

# flows/nodes.py
SERVER_CERT_FINGERPRINT_KEY = "ocm:server_cert:{node_id}"
async def sync_server_cert(
    redis: Redis, node_id: int, path: Path, driver: NodeDriver
) -> Literal["unchanged", "reloaded", "missing"]

# apps/worker.py
async def check_server_cert(ctx) -> str      # cron раз в 6 часов
```

- [ ] **Шаг 1: Тесты функции.** В `flows/test_nodes.py` добавьте импорты (`hashlib` не нужен) и тесты. Нужны
  `redis` (фикстура `conftest.py`), `tmp_path`, `FakeNodeDriver`, `NodeUnreachable`:

```python
from pathlib import Path

from arq import ArqRedis

from ocmanager.flows.nodes import sync_server_cert
from ocmanager.nodes.driver.base import NodeUnreachable
from ocmanager.nodes.driver.fake import FakeNodeDriver


async def test_the_first_look_at_the_certificate_reloads_once(
    redis: ArqRedis, tmp_path: Path
) -> None:
    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    driver = FakeNodeDriver()

    assert await sync_server_cert(redis, 1, cert, driver) == "reloaded"
    assert driver.calls == [("reload", ())]


async def test_an_unchanged_certificate_is_left_alone(redis: ArqRedis, tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    driver = FakeNodeDriver()
    await sync_server_cert(redis, 1, cert, driver)

    assert await sync_server_cert(redis, 1, cert, driver) == "unchanged"
    assert driver.calls == [("reload", ())]  # второго reload нет


async def test_a_renewed_certificate_reloads_the_node(redis: ArqRedis, tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    driver = FakeNodeDriver()
    await sync_server_cert(redis, 1, cert, driver)

    cert.write_bytes(b"certificate-2")  # Caddy продлил сертификат

    assert await sync_server_cert(redis, 1, cert, driver) == "reloaded"
    assert driver.calls == [("reload", ()), ("reload", ())]


async def test_a_failed_reload_is_retried_next_time(redis: ArqRedis, tmp_path: Path) -> None:
    class FlakyDriver(FakeNodeDriver):
        failures = 1

        async def reload(self) -> None:
            if self.failures:
                self.failures -= 1
                raise NodeUnreachable("occtl is down")
            await super().reload()

    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    driver = FlakyDriver()

    with pytest.raises(NodeUnreachable):
        await sync_server_cert(redis, 1, cert, driver)
    # отпечаток не запомнен: следующий запуск повторит reload
    assert await sync_server_cert(redis, 1, cert, driver) == "reloaded"
    assert driver.calls == [("reload", ())]


async def test_a_missing_certificate_file_is_reported_not_raised(
    redis: ArqRedis, tmp_path: Path
) -> None:
    driver = FakeNodeDriver()
    assert await sync_server_cert(redis, 1, tmp_path / "nope.crt", driver) == "missing"
    assert driver.calls == []


async def test_each_node_remembers_its_own_fingerprint(redis: ArqRedis, tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    first, second = FakeNodeDriver(), FakeNodeDriver()

    await sync_server_cert(redis, 1, cert, first)
    await sync_server_cert(redis, 2, cert, second)

    assert first.calls == second.calls == [("reload", ())]
```

Если в файле уже импортируются `pytest` и другие имена — не дублируйте. Проверьте, что `FakeNodeDriver.calls`
действительно список кортежей `(имя, аргументы)`: так записывает `reload` (`self.calls.append(("reload", ()))`).

- [ ] **Шаг 2: Запустить — FAIL**

```bash
cd backend
uv run pytest src/ocmanager/flows/test_nodes.py -q 2>&1 | tail -5
```
Ожидается: ошибка импорта `sync_server_cert`.

- [ ] **Шаг 3: Реализация.** В `flows/nodes.py` добавьте импорты и функцию:

```python
import asyncio
import hashlib
from pathlib import Path
from typing import Literal

SERVER_CERT_FINGERPRINT_KEY = "ocm:server_cert:{node_id}"


async def sync_server_cert(
    redis: Redis, node_id: int, path: Path, driver: NodeDriver
) -> Literal["unchanged", "reloaded", "missing"]:
    """Серверный сертификат ocserv выпускает и продлевает Caddy; ocserv держит прочитанный при
    старте. Смена файла без reload тихо ломает подключения через 60–90 дней, поэтому воркер
    сверяет отпечаток с запомненным и при отличии просит ocserv перечитать сертификат.

    Отпечаток запоминается только после успешного reload: сбой повторится при следующем запуске.
    Пустой Redis даёт один лишний reload — он не обрывает сессии и дешевле пропущенного."""
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        return "missing"
    fingerprint = hashlib.sha256(data).hexdigest()
    key = SERVER_CERT_FINGERPRINT_KEY.format(node_id=node_id)
    known = await redis.get(key)
    if isinstance(known, bytes):
        known = known.decode()
    if known == fingerprint:
        return "unchanged"
    await driver.reload()
    await redis.set(key, fingerprint)
    return "reloaded"
```

`redis.get` у `ArqRedis` возвращает байты — поэтому `decode()`. Если в файле уже есть `from pathlib import Path`
или `import asyncio` — не дублируйте.

- [ ] **Шаг 4: Запустить — PASS**

```bash
uv run pytest src/ocmanager/flows/test_nodes.py -q 2>&1 | tail -5
```

- [ ] **Шаг 5: Настройка.** В `core/config.py` после `ocserv_container`:

```python
    # Серверный сертификат ocserv, который выпускает и продлевает Caddy (общий том). Воркер следит
    # за файлом и просит ноду перечитать его при смене. Не задан — слежения нет (dev).
    server_cert_path: Path | None = None
```

- [ ] **Шаг 6: Задача воркера.** В `apps/worker.py` импортируйте `from ocmanager.flows import nodes as node_flows`
  (рядом с остальными `flows`; `check_node_health` уже импортируется отдельной строкой — это нормально) и
  добавьте рядом с `check_nodes`:

```python
async def check_server_cert(ctx: dict[str, Any]) -> str:
    """Продлённый Caddy сертификат — в ocserv: reload при смене отпечатка файла. Раз в 6 часов."""
    settings: Settings = ctx["settings"]
    if settings.server_cert_path is None:
        return "disabled"
    outcome = "no_nodes"
    async with ctx["sessionmaker"]() as session:
        nodes = await registry.get_active_nodes(session)
    for node in nodes:
        try:
            outcome = await node_flows.sync_server_cert(
                ctx["redis"],
                node.id,
                settings.server_cert_path,
                registry.driver_for(node, settings),
            )
        except NodeUnreachable as exc:
            # Нода недоступна — не ошибка задачи: отпечаток не запомнен, повторим через 6 часов.
            log.warning("server_cert_reload_failed", node_id=node.id, error=str(exc))
            return "unreachable"
        if outcome == "missing":
            log.warning("server_cert_missing", path=str(settings.server_cert_path))
        elif outcome == "reloaded":
            log.info("server_cert_reloaded", node_id=node.id)
    return outcome
```

и в `cron_jobs`:

```python
        cron(check_server_cert, hour={0, 6, 12, 18}, minute={25}, second={0}, keep_result=0),
```

- [ ] **Шаг 7: Тесты воркера.** В `apps/test_worker.py`: в `test_cron_registry` добавьте
  `"cron:check_server_cert",`; импортируйте `check_server_cert` из `ocmanager.apps.worker`; тесты:

```python
async def test_check_server_cert_is_off_without_a_path(
    sessionmaker: async_sessionmaker[AsyncSession], redis: ArqRedis, settings: Settings
) -> None:
    ctx: dict[str, Any] = {"settings": settings, "sessionmaker": sessionmaker, "redis": redis}
    assert settings.server_cert_path is None
    assert await check_server_cert(ctx) == "disabled"


async def test_check_server_cert_reloads_the_node_when_the_file_changes(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: ArqRedis,
    settings: Settings,
    tmp_path: Path,
) -> None:
    cert = tmp_path / "server.crt"
    cert.write_bytes(b"certificate-1")
    configured = settings.model_copy(update={"server_cert_path": cert})
    async with sessionmaker() as s:
        await registry.ensure_local_node(s, configured)
        await s.commit()
    ctx: dict[str, Any] = {"settings": configured, "sessionmaker": sessionmaker, "redis": redis}
    fake = FakeNodeDriver()

    with registry.override_driver(fake):
        assert await check_server_cert(ctx) == "reloaded"
        assert await check_server_cert(ctx) == "unchanged"
        cert.write_bytes(b"certificate-2")
        assert await check_server_cert(ctx) == "reloaded"

    assert fake.calls.count(("reload", ())) == 2


def test_the_certificate_is_checked_every_six_hours() -> None:
    [job] = [j for j in WorkerSettings.cron_jobs if j.name == "cron:check_server_cert"]
    assert job.hour == {0, 6, 12, 18}
```

`Path` и `registry` в `test_worker.py` уже импортированы. Если `ensure_local_node` требует иных аргументов —
подсмотрите в `test_check_nodes_updates_status_and_cache`.

- [ ] **Шаг 8: Проверка и коммит**

```bash
make fmt && make check
git add src/ocmanager
git commit -m "feat(backend): reload ocserv when caddy renews the server certificate"
```

---

### Задача 7.7: Боевой compose и `.env.example`

**Files:**
- Create: `deploy/docker-compose.yml`, `deploy/.env.example`
- Modify: `.gitignore` (добавить `deploy/.env`)

**Interfaces:**
- Consumes: образы и конфиги Задач 7.1–7.5; `OCM_SERVER_CERT_PATH` (7.6).
- Produces: `docker compose up -d` из каталога `deploy/`. Сервисы: `volume-init`, `postgres`, `redis`,
  `docker-proxy`, `migrate`, `api-public`, `api-admin`, `worker`, `bot`, `ocserv`, `caddy`, `nginx`, а также
  служебный `cli` (профиль `tools`). Тома: `pgdata`, `redisdata`, `pki`, `ocserv-state`, `caddy-data`,
  `caddy-config`.

- [ ] **Шаг 1: `.gitignore`.** Добавьте строку (рядом с `.env`; шаблон `.env` ловит только файл ровно с таким
  именем в любом каталоге, но явная запись понятнее):

```
deploy/.env
```

- [ ] **Шаг 2: `deploy/.env.example`**

```bash
# Боевые настройки. cp .env.example .env, заполнить, chmod 600 .env.
# Секреты генерируйте так:  openssl rand -hex 24   (Postgres и Redis — только hex: пароль идёт в URL).

# --- Домены (A-записи обоих — на IP сервера; 80 и 443 открыты) ---------------------------------
# Адрес Mini App и вебхуков Tribute.
DOMAIN_APP=app.example.com
# Адрес VPN (SNI). Для него Caddy выпускает настоящий сертификат Let's Encrypt.
DOMAIN_VPN=vpn.example.com
# Почта для уведомлений Let's Encrypt.
ACME_EMAIL=admin@example.com

# --- Пароли инфраструктуры -----------------------------------------------------------------------
POSTGRES_PASSWORD=change-me-hex-24
REDIS_PASSWORD=change-me-hex-24

# --- Секреты приложения (≥ 32 символов) ------------------------------------------------------------
# python -c "import secrets; print(secrets.token_urlsafe(48))"
OCM_SECRET_KEY=change-me-change-me-change-me-change-me
# Общий секрет ноды и панели: им disconnect.sh подписывает отчёт о сессии.
OCM_INTERNAL_TOKEN=change-me-change-me-change-me-change-me
# Секрет камуфляжа ocserv: https://<DOMAIN_VPN>/?<секрет> открывает шлюз, остальное — «сайт».
OCM_CAMOUFLAGE_SECRET=change-me-camouflage

# --- Telegram и платежи ---------------------------------------------------------------------------------
# Токен бота (@BotFather). Им подписана initData Mini App.
OCM_BOT_TOKEN=000000:change-me
# Ключ API Tribute (кабинет автора → API). Пусто — вебхуки Tribute не принимаются (404).
OCM_TRIBUTE_API_KEY=

# --- Необязательное ----------------------------------------------------------------------------------------
# Подсеть клиентов VPN (NAT делает ocserv).
OCSERV_IPV4_NETWORK=10.77.0.0/24
# Адрес поддержки в Mini App (применяется при сборке образа web).
VITE_SUPPORT_HANDLE=@ocmanager_help
```

- [ ] **Шаг 3: `deploy/docker-compose.yml`**

```yaml
# Боевой стек (спека §2.5). Запуск из этого каталога: docker compose up -d
# Порядок первого запуска и обслуживание — в README.md.
name: ocmanager

x-logging: &logging
  driver: json-file
  options: { max-size: "10m", max-file: "5" }

x-backend-env: &backend-env
  OCM_ENV: production
  OCM_LOG_FORMAT: json
  OCM_DATABASE_URL: postgresql+asyncpg://ocm:${POSTGRES_PASSWORD:?задайте POSTGRES_PASSWORD}@postgres:5432/ocmanager
  OCM_REDIS_URL: redis://:${REDIS_PASSWORD:?задайте REDIS_PASSWORD}@redis:6379/0
  OCM_SECRET_KEY: ${OCM_SECRET_KEY:?задайте OCM_SECRET_KEY}
  OCM_INTERNAL_TOKEN: ${OCM_INTERNAL_TOKEN:?задайте OCM_INTERNAL_TOKEN}
  OCM_CAMOUFLAGE_SECRET: ${OCM_CAMOUFLAGE_SECRET:?задайте OCM_CAMOUFLAGE_SECRET}
  OCM_BOT_TOKEN: ${OCM_BOT_TOKEN:?задайте OCM_BOT_TOKEN}
  OCM_TRIBUTE_API_KEY: ${OCM_TRIBUTE_API_KEY:-}
  OCM_PUBLIC_BASE_URL: https://${DOMAIN_APP:?задайте DOMAIN_APP}
  OCM_VPN_HOST: ${DOMAIN_VPN:?задайте DOMAIN_VPN}
  OCM_PKI_DIR: /var/lib/ocmanager-pki
  OCM_OCSERV_STATE_DIR: /var/lib/ocmanager
  OCM_OCSERV_CONTAINER: ocm-ocserv

x-backend: &backend
  image: ocmanager/backend:${OCM_VERSION:-latest}
  restart: unless-stopped
  logging: *logging

x-after-migrate: &after-migrate
  postgres: { condition: service_healthy }
  redis: { condition: service_healthy }
  volume-init: { condition: service_completed_successfully }
  migrate: { condition: service_completed_successfully }

services:
  # Права на тома. Именованный том наследует владельца от первого смонтировавшего контейнера,
  # а ocserv и бэкенд делят ocserv-state — без этого результат зависел бы от порядка запуска.
  volume-init:
    image: alpine:3.20
    command: ["chown", "-R", "10001:10001", "/state", "/pki"]
    volumes:
      - ocserv-state:/state
      - pki:/pki
    restart: "no"

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    logging: *logging
    environment:
      POSTGRES_USER: ocm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ocmanager
    volumes: [pgdata:/var/lib/postgresql/data]
    networks: [app]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ocm -d ocmanager"]
      interval: 5s
      timeout: 3s
      retries: 15

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    logging: *logging
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", "--appendonly", "yes"]
    environment: { REDIS_PASSWORD: "${REDIS_PASSWORD}" }
    volumes: [redisdata:/data]
    networks: [app]
    healthcheck:
      test: ["CMD-SHELL", 'redis-cli -a "$$REDIS_PASSWORD" --no-auth-warning ping | grep -q PONG']
      interval: 5s
      timeout: 3s
      retries: 15

  # Единственный путь к Docker API для worker и api-admin (решение П7-1).
  docker-proxy:
    image: haproxy:3.0-alpine
    restart: unless-stopped
    logging: *logging
    user: "0:0" # читает /var/run/docker.sock (root:docker, 0660)
    volumes:
      - ./docker-proxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
      - /var/run/docker.sock:/var/run/docker.sock
    networks: [docker]

  migrate:
    <<: *backend
    build: ../backend
    restart: "no"
    command: ["migrate"]
    environment: *backend-env
    depends_on:
      postgres: { condition: service_healthy }
    networks: [app]

  api-public:
    <<: *backend
    command: ["api-public"]
    environment: *backend-env
    # ca.key только на чтение: выпуск .p12 идёт в запросе (открытый вопрос №5 дорожной карты).
    volumes:
      - pki:/var/lib/ocmanager-pki:ro
      - ocserv-state:/var/lib/ocmanager:ro
    depends_on: *after-migrate
    networks: [web, hooks, app]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s

  api-admin:
    <<: *backend
    command: ["api-admin"]
    environment:
      <<: *backend-env
      DOCKER_HOST: tcp://docker-proxy:2375
    # Только loopback хоста: доступ по SSH-туннелю (дизайн §9).
    ports: ["127.0.0.1:8080:8080"]
    volumes:
      - pki:/var/lib/ocmanager-pki:ro
      - ocserv-state:/var/lib/ocmanager
    depends_on:
      <<: *after-migrate
      docker-proxy: { condition: service_started }
    networks: [app, docker]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/admin/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s

  worker:
    <<: *backend
    command: ["worker"]
    environment:
      <<: *backend-env
      DOCKER_HOST: tcp://docker-proxy:2375
      OCM_SERVER_CERT_PATH: /caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/${DOMAIN_VPN}/${DOMAIN_VPN}.crt
    volumes:
      - pki:/var/lib/ocmanager-pki:ro
      - ocserv-state:/var/lib/ocmanager
      - caddy-data:/caddy-data:ro
    depends_on:
      <<: *after-migrate
      docker-proxy: { condition: service_started }
    networks: [app, docker]

  bot:
    <<: *backend
    command: ["bot"]
    environment: *backend-env
    depends_on: *after-migrate
    networks: [app]

  # Разовые команды: docker compose run --rm cli pki init
  cli:
    <<: *backend
    restart: "no"
    profiles: [tools]
    # Без роли образа: docker compose run cli <аргументы> подменяет command целиком.
    entrypoint: ["ocmanager"]
    command: ["--help"]
    environment: *backend-env
    volumes:
      - pki:/var/lib/ocmanager-pki
      - ocserv-state:/var/lib/ocmanager
    depends_on: *after-migrate
    networks: [app]

  ocserv:
    build: ../ocserv
    image: ocmanager/ocserv:${OCM_VERSION:-latest}
    container_name: ocm-ocserv # зашито в docker-proxy/haproxy.cfg
    restart: unless-stopped
    logging: *logging
    cap_add: [NET_ADMIN]
    devices: ["/dev/net/tun"]
    sysctls: { net.ipv4.ip_forward: 1 }
    # TCP 443 принимает nginx; DTLS (UDP) идёт прямо в ocserv.
    ports: ["443:443/udp"]
    environment:
      OCSERV_SERVER_CERT: /caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/${DOMAIN_VPN}/${DOMAIN_VPN}.crt
      OCSERV_SERVER_KEY: /caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/${DOMAIN_VPN}/${DOMAIN_VPN}.key
      OCSERV_IPV4_NETWORK: ${OCSERV_IPV4_NETWORK:-10.77.0.0/24}
      OCSERV_CAMOUFLAGE_SECRET: ${OCM_CAMOUFLAGE_SECRET}
      OCSERV_PROXY_PROTOCOL: "true"
      OCSERV_CERT_WAIT_S: "900" # Caddy выпускает сертификат спустя минуты после первого старта
      OCM_INTERNAL_TOKEN: ${OCM_INTERNAL_TOKEN}
      OCM_SESSION_END_URL: http://api-public:8000/internal/session-end
    volumes:
      - ocserv-state:/var/lib/ocmanager:ro
      - caddy-data:/caddy-data:ro
    depends_on:
      volume-init: { condition: service_completed_successfully }
      caddy: { condition: service_started }
    networks: [edge, hooks]

  caddy:
    build:
      context: ..
      dockerfile: deploy/web/Dockerfile
      args:
        VITE_SUPPORT_HANDLE: ${VITE_SUPPORT_HANDLE:-@ocmanager_help}
    image: ocmanager/web:${OCM_VERSION:-latest}
    restart: unless-stopped
    logging: *logging
    # Порт 80 — ACME HTTP-01 и редирект на https; 443 принимает nginx, Caddy слушает 8443.
    ports: ["80:80"]
    environment:
      DOMAIN_APP: ${DOMAIN_APP}
      DOMAIN_VPN: ${DOMAIN_VPN}
      ACME_EMAIL: ${ACME_EMAIL}
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    networks: [edge, web]

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    logging: *logging
    ports: ["443:443/tcp"]
    environment: { DOMAIN_VPN: "${DOMAIN_VPN}" }
    volumes:
      - ./nginx/nginx.conf.template:/etc/nginx/nginx.conf.template:ro
    command:
      - sh
      - -c
      - "envsubst '$${DOMAIN_VPN}' </etc/nginx/nginx.conf.template >/etc/nginx/nginx.conf && exec nginx -g 'daemon off;'"
    depends_on:
      caddy: { condition: service_started }
      ocserv: { condition: service_started }
    networks: [edge]

networks:
  # Фиксированная подсеть: Caddy принимает PROXY-заголовок только отсюда (решение П7-3).
  edge:
    ipam:
      config: [{ subnet: 172.29.10.0/24 }]
  web: {}
  # ocserv ↔ api-public: только POST /internal/session-end; наружу из этой сети выхода нет.
  hooks: { internal: true }
  app: {}
  # Прокси к Docker: без выхода наружу, в ней только прокси, worker и api-admin.
  docker: { internal: true }

volumes:
  pgdata:
  redisdata:
  pki:
  ocserv-state:
  caddy-data:
  caddy-config:
```

- [ ] **Шаг 4: Проверить конфигурацию**

```bash
cd deploy
docker compose --env-file .env.example config -q && echo "compose: валиден"
docker compose --env-file .env.example config --services | sort | tr '\n' ' '; echo
docker compose --env-file .env.example config | grep -E 'docker.sock|published:' 
cd .. && scripts/check-deploy-configs.sh
```
Ожидается: «compose: валиден»; в списке сервисов нет `cli` (профиль `tools`) — `docker compose --profile tools
config --services` покажет и его; `docker.sock` смонтирован **только** в `docker-proxy`; опубликованы порты
`80`, `443` (tcp и udp) и `127.0.0.1:8080` — ничего больше. Если `config` ругается на якоря `*after-migrate` в
`depends_on` с `<<:` — пришлите вывод, развернём слияние явно.

- [ ] **Шаг 5: Собрать образы**

```bash
cd deploy
docker compose --env-file .env.example build
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep ocmanager
```
Ожидается: `ocmanager/backend`, `ocmanager/ocserv`, `ocmanager/web` с тегом `latest`.

- [ ] **Шаг 6: Коммит**

```bash
git add .gitignore deploy/docker-compose.yml deploy/.env.example
git commit -m "chore(deploy): production compose with isolated networks and least-privilege volumes"
```

---

### Задача 7.8: `scripts/doctor.sh`

**Files:**
- Create: `scripts/doctor.sh`

**Interfaces:**
- Consumes: боевой стек из Задачи 7.7, `deploy/.env`; на сервере — `docker compose`, `openssl`, `curl`, `ss`.
- Produces: `scripts/doctor.sh` — код выхода `0`, если всё зелёное, иначе число проваленных проверок.

- [ ] **Шаг 1: `scripts/doctor.sh`**

```bash
#!/usr/bin/env bash
# Диагностика боевого стенда. На сервере из любого каталога: scripts/doctor.sh
# Каждая строка — одна проверка; код выхода = число проваленных.
set -uo pipefail
cd "$(dirname "$0")/../deploy"
set -a
# shellcheck disable=SC1091
. ./.env
set +a

fails=0
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fails=$((fails + 1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }

compose() { docker compose "$@"; }
resolve_app() { echo "--resolve $DOMAIN_APP:443:127.0.0.1"; }

# --- контейнеры ----------------------------------------------------------------------------------
no_dead_services() {
    ! compose ps --status exited --format '{{.Service}}' | grep -vE '^(migrate|volume-init)$' | grep -q .
}
check "все сервисы запущены (кроме разовых migrate и volume-init)" no_dead_services

# --- порты ---------------------------------------------------------------------------------------
check "80/tcp слушается"  bash -c "ss -H -ltn 'sport = :80'  | grep -q ."
check "443/tcp слушается" bash -c "ss -H -ltn 'sport = :443' | grep -q ."
check "443/udp слушается (DTLS)" bash -c "ss -H -lun 'sport = :443' | grep -q ."
admin_only_on_loopback() {
    local addrs
    addrs=$(ss -H -ltn 'sport = :8080' | awk '{print $4}')
    [ -n "$addrs" ] && ! echo "$addrs" | grep -qvE '^(127\.0\.0\.1|\[::1\]):8080$'
}
check "админка 8080 слушается только на loopback" admin_only_on_loopback
check "Postgres и Redis не опубликованы" bash -c "! ss -H -ltn 'sport = :5432 or sport = :6379' | grep -q ."

# --- сертификаты обоих доменов ---------------------------------------------------------------------
cert_valid() { echo | openssl s_client -connect 127.0.0.1:443 -servername "$1" -verify_hostname "$1" 2>/dev/null | grep -q 'Verify return code: 0 (ok)'; }
cert_days() { echo | openssl s_client -connect 127.0.0.1:443 -servername "$1" 2>/dev/null | openssl x509 -noout -checkend $(($2 * 86400)); }
for domain in "$DOMAIN_APP" "$DOMAIN_VPN"; do
    check "сертификат $domain действителен (цепочка и имя)" cert_valid "$domain"
    check "сертификат $domain не истекает в ближайшие 14 дней" cert_days "$domain" 14
done

# --- публичный API --------------------------------------------------------------------------------
# shellcheck disable=SC2046
check "api-public отвечает через Caddy" bash -c "curl -fsS $(resolve_app) https://$DOMAIN_APP/api/health | grep -q '\"ok\"'"
internal_blocked() {
    local get post
    # shellcheck disable=SC2046
    get=$(curl -s -o /dev/null -w '%{http_code}' $(resolve_app) "https://$DOMAIN_APP/internal/session-end")
    # shellcheck disable=SC2046
    post=$(curl -s -o /dev/null -w '%{http_code}' -X POST $(resolve_app) "https://$DOMAIN_APP/internal/session-end")
    [ "$get" = 404 ] && [ "$post" = 404 ]
}
check "/internal снаружи недоступен (404 на GET и POST)" internal_blocked
check "Mini App отдаёт страницу" bash -c "curl -fsS $(resolve_app) https://$DOMAIN_APP/ | grep -qi '<div id=\"root\"'"
vpn_answers() { curl -ks -o /dev/null --max-time 5 --resolve "$DOMAIN_VPN:443:127.0.0.1" "https://$DOMAIN_VPN/"; }
check "VPN-домен отвечает по TLS через nginx и ocserv" vpn_answers

# --- нода ------------------------------------------------------------------------------------------------
ocserv_healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' ocm-ocserv)" = healthy ]; }
check "ocserv healthy" ocserv_healthy
crl_fresh() {
    compose exec -T worker python - <<'PY'
import sys
from datetime import UTC, datetime, timedelta
from cryptography import x509

crl = x509.load_pem_x509_crl(open("/var/lib/ocmanager/crl.pem", "rb").read())
sys.exit(0 if crl.next_update_utc - datetime.now(UTC) > timedelta(days=3) else 1)
PY
}
check "CRL не истекает в ближайшие 3 дня" crl_fresh
reconcile_ok() {
    compose exec -T postgres psql -U ocm -d ocmanager -tA -c \
        "select count(*) from nodes where last_reconcile_at > now() - interval '15 minutes' and coalesce(last_reconcile_report->>'error', '') = ''" \
        | grep -qx 1
}
check "последняя сверка ноды (reconcile) — меньше 15 минут назад, без ошибки" reconcile_ok
docker_proxy_restricts() { ! compose exec -T worker docker ps; }
check "worker не может выполнить docker ps (прокси ограничивает)" docker_proxy_restricts
proxy_protocol_enforced() { ! docker exec ocm-ocserv curl -ks --max-time 3 -o /dev/null https://localhost:443/; }
check "ocserv требует PROXY-заголовок на TCP (адрес клиента не теряется)" proxy_protocol_enforced

echo
if [ "$fails" -eq 0 ]; then
    printf '\033[32mвсё в порядке\033[0m\n'
else
    printf '\033[31mпроваленных проверок: %d\033[0m\n' "$fails"
fi
exit "$fails"
```

```bash
chmod +x scripts/doctor.sh
```

- [ ] **Шаг 2: Синтаксис** (без сервера)

```bash
bash -n scripts/doctor.sh && echo "синтаксис ok"
command -v shellcheck >/dev/null && shellcheck scripts/doctor.sh scripts/check-deploy-configs.sh deploy/docker-proxy/check.sh || echo "shellcheck не установлен — пропущено"
```
Ожидается: «синтаксис ok». Прогон на настоящем стенде — шаг 5 Задачи 7.10.

- [ ] **Шаг 3: Коммит**

```bash
git add scripts/doctor.sh
git commit -m "chore(deploy): doctor script for ports, certificates, isolation and reconcile"
```

---

### Задача 7.9: CI — образы, конфиги и интеграционные тесты

**Files:**
- Modify: `.github/workflows/backend.yml`
- Create: `.github/workflows/tma.yml`

**Interfaces:**
- Consumes: `make check`, `make ocserv-up`, `make test-ocserv`, `scripts/check-deploy-configs.sh`,
  `deploy/docker-proxy/check.sh`.
- Produces: на каждый PR — `check` (как сейчас), `images` (сборка образов + проверка конфигов),
  `integration` (после `check`, с настоящим ocserv) и отдельный workflow Mini App.

- [ ] **Шаг 1: `.github/workflows/backend.yml`.** Расширьте фильтры путей и добавьте два job после `check`:

```yaml
name: backend

on:
  push:
    branches: [main]
    paths: &paths
      - "backend/**"
      - "ocserv/**"
      - "deploy/**"
      - "scripts/**"
      - ".github/workflows/backend.yml"
  pull_request:
    paths: *paths

jobs:
  check:
    # …без изменений (services postgres/redis, uv sync, make check)…

  images:
    runs-on: ubuntu-latest
    needs: check
    steps:
      - uses: actions/checkout@v4
      - name: Образ бэкенда собирается и знает роли
        run: |
          docker build -t ocmanager/backend:ci backend
          docker run --rm ocmanager/backend:ci cli --help >/dev/null
          test "$(docker run --rm ocmanager/backend:ci nonsense 2>/dev/null; echo $?)" = 64
      - name: Образ ocserv собирается
        run: docker build -t ocmanager/ocserv:ci ocserv
      - name: Образ Mini App собирается (внутри — защита от моков)
        run: docker build -f deploy/web/Dockerfile -t ocmanager/web:ci .
      - name: Конфиги деплоя валидны
        run: scripts/check-deploy-configs.sh

  integration:
    runs-on: ubuntu-latest
    needs: check
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - run: uv sync --frozen
      # Настройки для CLI: dev-значения совпадают с deploy/docker-compose.dev.yml.
      - run: cp .env.example .env
      - run: make dev-up
      - name: PKI и серверный сертификат
        run: |
          uv run ocmanager pki init
          uv run ocmanager pki dev-server-cert --host ocserv --host localhost
      - run: make ocserv-up
      - run: docker compose -f ../deploy/docker-compose.dev.yml --profile tools build vpn-client
      - run: make test-ocserv
      - name: Прокси к Docker пропускает только нужное
        run: ../deploy/docker-proxy/check.sh
      - name: Логи ноды при падении
        if: failure()
        run: docker logs ocm-ocserv > ocserv.log 2>&1 || true
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: ocserv-log
          path: backend/ocserv.log
          if-no-files-found: ignore
```

Блок `check:` оставьте таким, каким он сейчас в файле, — в примере он свёрнут комментарием. Если GitHub не
принимает якорь `&paths` в `on:` — продублируйте список путей явно в обоих событиях.

- [ ] **Шаг 2: `.github/workflows/tma.yml`.** Mini App раньше в CI не проверялся совсем.

```yaml
name: tma

on:
  push:
    branches: [main]
    paths: ["frontend/tma/**", "deploy/web/**", ".github/workflows/tma.yml"]
  pull_request:
    paths: ["frontend/tma/**", "deploy/web/**", ".github/workflows/tma.yml"]

jobs:
  check:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend/tma
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/tma/package-lock.json
      - run: npm ci
      - run: npm run typecheck
      - run: npm run lint
      - run: npm test
      # Сборка + защита от моков в бандле (src/build.test.ts).
      - run: npm run build
      - run: npm test -- src/build.test.ts
```

- [ ] **Шаг 3: Проверить локально то, что можно**

```bash
python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]; print('yaml ok')" \
  .github/workflows/backend.yml .github/workflows/tma.yml
```
Ожидается: `yaml ok`. (Якорь в `on:` PyYAML разворачивает; GitHub — тоже, но см. примечание выше.)

- [ ] **Шаг 4: Открыть PR и дождаться зелёного прогона.** Сразу после пуша ветки следите за тремя job:
  `check`, `images`, `integration`. Если `integration` падает на `ocserv-up` с ошибкой про `/dev/net/tun` —
  пришлите артефакт `ocserv-log` и вывод шага.

- [ ] **Шаг 5: Красный прогон на сломанном хуке** (как в дорожной карте — доказательство, что набор что-то
  ловит). В той же ветке временно замените тело `ocserv/hooks/connect.sh` на `exit 0` и запушьте:

```bash
cp ocserv/hooks/connect.sh /tmp/connect.sh.bak
printf '#!/bin/sh\nexit 0\n' > ocserv/hooks/connect.sh
git commit -am "wip: break connect.sh on purpose"
git push
```
Ожидается: `integration` краснеет на `test_not_allowed_is_refused`. Затем откат:

```bash
git revert --no-edit HEAD && git push
```
Ожидается: `integration` снова зелёный. Не сливайте PR, пока откат не прошёл.

- [ ] **Шаг 6: Коммит** (до шагов 4–5)

```bash
git add .github
git commit -m "chore(ci): build images, validate deploy configs and run live ocserv integration suite"
```

---

### Задача 7.10: README и развёртывание на чистом сервере

**Files:**
- Create: `deploy/README.md`

**Interfaces:**
- Produces: исполнимая инструкция «чистый VPS → работающий сервис»; это же — критерий готовности фазы.

- [ ] **Шаг 1: `deploy/README.md`**

````markdown
# Развёртывание ocmanager

Один сервер, два домена: `DOMAIN_APP` (Mini App, вебхуки) и `DOMAIN_VPN` (шлюз ocserv).

## Что нужно

- Сервер Debian 12+/Ubuntu 22.04+, root или sudo, публичный IPv4. Docker 24+ с Compose v2.
- Две A-записи (`app.…` и `vpn.…`) на IP сервера. Порты **80/tcp, 443/tcp, 443/udp** свободны и открыты.
- Бот из @BotFather. Ключ API Tribute — позже, вебхуки без него просто отвечают 404.

Docker сам публикует порты в обход `ufw`: закрывайте лишнее на уровне облачного firewall провайдера.
Наружу должны смотреть только 80, 443 (tcp и udp) и ваш SSH.

## Первый запуск

```bash
git clone <репозиторий> ocmanager && cd ocmanager/deploy
cp .env.example .env && chmod 600 .env
# заполните домены, пароли (openssl rand -hex 24), OCM_SECRET_KEY, OCM_INTERNAL_TOKEN,
# OCM_CAMOUFLAGE_SECRET, OCM_BOT_TOKEN
docker compose build
```

Порядок важен: ocserv не стартует без CA и CRL, а панель — без миграций.

```bash
# 1. Базы, миграции и права на тома
docker compose up -d postgres redis volume-init
# 2. CA (создаётся один раз; повторный запуск откажется перезаписывать)
docker compose run --rm cli pki init
# 3. Первый администратор (пароль ≥ 12 символов)
docker compose run --rm cli admin create owner
# 4. Всё остальное. Caddy выпустит оба сертификата (1–3 минуты); ocserv дождётся своего
docker compose up -d
docker compose logs -f caddy      # ждём «certificate obtained successfully» для обоих доменов
```

Проверка:

```bash
../scripts/doctor.sh
```

Все строки должны быть зелёными. Что значит красная — в тексте самой проверки.

## После запуска

1. **Mini App.** @BotFather → `/myapps` → ваше приложение → Edit Web App URL → `https://<DOMAIN_APP>`.
2. **Админка** — только через SSH-туннель:
   ```bash
   ssh -L 8080:127.0.0.1:8080 user@сервер
   # затем в браузере: http://localhost:8080/admin/docs
   ```
3. **Алерты админу.** Напишите боту `/whoami`, получите число — добавьте его в настройку `admin_chat_ids`
   (`PATCH /admin/settings` в документации админки).
4. **Тарифы** — `docker compose run --rm cli plan --help` или раздел «Тарифы» админки.
5. **Tribute.** В кабинете автора укажите вебхук `https://<DOMAIN_APP>/webhooks/tribute` и впишите ключ API
   в `OCM_TRIBUTE_API_KEY`; `docker compose up -d` применит.

## Обновление

```bash
git pull
docker compose build
docker compose up -d      # миграции накатываются сами (сервис migrate)
../scripts/doctor.sh
```

## Резервные копии (пока вручную)

Автоматических бэкапов нет. **Потеря тома `pki` — это потеря CA: все выданные клиентам ключи придётся
выпускать заново.** Делайте копию после `pki init` и по расписанию:

```bash
docker compose exec -T postgres pg_dump -U ocm ocmanager | gzip > ocmanager-$(date +%F).sql.gz
docker run --rm -v ocmanager_pki:/pki:ro -v "$PWD":/out alpine tar czf /out/pki-$(date +%F).tgz -C /pki .
```

Храните копии вне сервера. Файл с `pki` содержит приватный ключ CA — шифруйте его.

## Если что-то не так

| Симптом | Куда смотреть |
|---|---|
| ocserv перезапускается | `docker compose logs ocserv` — нет CA/CRL (шаг 2) или сертификата (Caddy ещё выпускает) |
| Сертификат не выпускается | A-записи, порт 80 снаружи, `docker compose logs caddy` (лимиты Let's Encrypt — 5 неудач в час) |
| Клиенты не подключаются через месяцы работы | `docker compose logs worker \| grep server_cert` — продление сертификата подхватывается воркером раз в 6 часов |
| Mini App — белый экран | Edit Web App URL в @BotFather; `curl -I https://<DOMAIN_APP>` не должен содержать `X-Frame-Options` |
| Нет уведомлений | `docker compose logs worker \| grep notifications`; `admin_chat_ids` не задан |
````

- [ ] **Шаг 2: Развернуть на тестовом VPS.** Нужны сервер и два поддомена (можно временные). Пройдите
  `README.md` **буквально**, не правя исходников; всё, что пришлось поправить руками, — дефект плана или
  README: запишите и пришлите.

- [ ] **Шаг 3: Прогнать `doctor.sh`.** Ожидается: все строки `OK`, код выхода `0`.

- [ ] **Шаг 4: Реальный клиент.**
  1. В Mini App оформите trial, выпустите устройство, скачайте `.p12`.
  2. Подключитесь десктопным клиентом (`openconnect` или Cisco Secure Client): адрес
     `https://<DOMAIN_VPN>/?<OCM_CAMOUFLAGE_SECRET>`.
  3. Повторите с **iPhone** (открытый вопрос №3 спеки: импорт `.p12` на iOS).
  4. Убедитесь, что трафик идёт через сервер (`curl ifconfig.me` с устройства показывает IP сервера).

- [ ] **Шаг 5: Камуфляж и реальный адрес клиента** (Review Focus №1):
  - браузер на `https://<DOMAIN_VPN>/` (без секрета) не открывает шлюз: запрос авторизации или обычная
    страница, но не меню ocserv;
  - с подключённого клиента:
    ```bash
    docker exec ocm-ocserv occtl show users
    ```
    в колонке с адресом — **ваш настоящий IP**, а не `172.29.10.x`;
  - `docker compose logs api-public | tail` после запроса `https://<DOMAIN_APP>/api/health` с вашего ноутбука
    показывает **ваш** IP, а не адрес Caddy.

- [ ] **Шаг 6: Сертификат продлевается без простоя** (Review Focus №2). Не ждите 60 дней — имитируйте:

```bash
# запомненный отпечаток сертификата есть; стираем его, будто сертификат сменился:
docker compose exec -T redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning keys "ocm:server_cert:*"'
docker compose exec -T redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning del "ocm:server_cert:1"'
docker compose exec -T worker python - <<'PY'
import asyncio
from ocmanager.apps.worker import check_server_cert, startup, shutdown
from ocmanager.core.config import get_settings
async def main():
    ctx = {"settings": get_settings()}
    await startup(ctx)
    from ocmanager.core.redis import create_redis
    ctx["redis"] = await create_redis(get_settings().redis_url)
    print(await check_server_cert(ctx))
    await shutdown(ctx)
asyncio.run(main())
PY
```
Ожидается: `reloaded` (отпечаток стёрт — воркер перечитал сертификат), затем повторный запуск даёт
`unchanged`. Подключённый клиент не обрывается.

- [ ] **Шаг 7: Тест холодного рестарта.**

```bash
docker compose down            # тома остаются
docker compose up -d
sleep 90 && ../scripts/doctor.sh
```
Ожидается: стек поднялся без ручных действий, `doctor.sh` зелёный.

- [ ] **Шаг 8: Коммит**

```bash
git add deploy/README.md
git commit -m "docs(deploy): first run, update and backup instructions"
```

---

## Что Фаза 7 передаёт дальше

| Что | Кому | Контракт |
|---|---|---|
| `docker compose up -d` по `deploy/.env.example` | Эксплуатация | Тот же стек можно пересобрать на втором сервере: тома `pki` и `pgdata` переносятся копированием |
| Образ бэкенда с ролями | Этап 2 (новые процессы) | Новая роль — ветка в `docker-entrypoint.sh` и сервис в compose |
| `check_server_cert` | Этап 4 (несколько нод) | Функция уже принимает `node_id` и драйвер; путь к сертификату станет полем ноды |
| Белый список HAProxy | Этап 4 | Имя контейнера зашито; при нескольких нодах каждая получит свой прокси на своём хосте |
| `scripts/doctor.sh` | Установщик (этап 3) | Установщик вызывает его последним шагом и показывает вывод |

## Определение готовности фазы

- [ ] Задачи 7.1–7.9 закоммичены, CI зелёный (`check`, `images`, `integration`, `tma`).
- [ ] Чистый сервер разворачивается по `deploy/README.md` без правки исходников (7.10, шаг 2).
- [ ] `scripts/doctor.sh` зелёный (7.10, шаг 3); после `docker compose down && up -d` — снова зелёный (шаг 7).
- [ ] Подключение реальным клиентом работает на десктопе и iPhone; камуфляж не открывает шлюз без секрета;
  `occtl show users` показывает настоящий адрес клиента (шаги 4–5).
- [ ] Для каждого пункта Review Focus есть проверка (тест, скрипт или строка `doctor.sh`) и она зелёная.
- [ ] PR со сломанным `connect.sh` краснеет, откат — зеленеет (7.9, шаг 5).

## Покрытие требований

| Требование | Источник | Задача |
|---|---|---|
| `docker compose up -d` на чистом сервере, два домена | дорожная карта, Фаза 7 | 7.7, 7.10 |
| Снаружи только 443 (+80 для ACME) | дорожная карта, Фаза 7 | 7.7, 7.8 |
| Админка — только через SSH-туннель | дизайн §9, §11 | 7.7, 7.8 |
| Multi-stage образ, непривилегированный пользователь, роли | дорожная карта 7.1 | 7.1 |
| SNI-мультиплексор, UDP 443 напрямую в ocserv | дорожная карта 7.2, дизайн §4.4 | 7.5, 7.7 |
| Настоящий сертификат Let's Encrypt для камуфляжа | дизайн §4.4 | 7.5, 7.7 |
| Сертификат ocserv из тома Caddy, `check_server_cert` | дорожная карта 7.2 | 7.5, 7.6 |
| Доступ к Docker с ограничением до одной ноды | дорожная карта 7.2 | 7.4 |
| Сети `edge`/`app`/`hooks`, Postgres и Redis не публикуются | дорожная карта 7.2 | 7.7 |
| `/internal` не проксируется, 404 | дорожная карта 7.2 | 7.5, 7.8 |
| Тома: `pki` read-only, `ocserv-state`, `caddy-data` | дорожная карта 7.2 | 7.7 |
| `doctor.sh` | дорожная карта 7.2, стек §2.6 | 7.8 |
| Mini App без моков, без `X-Frame-Options`, SPA-фоллбэк | план TMA, Задача 21 | 7.3, 7.5 |
| CI: `check` + `integration` с настоящим ocserv | дорожная карта 7.3 | 7.9 |
| Проверка реального клиента, iPhone, камуфляж | дорожная карта 7.2, вопрос №3 | 7.10 |
| Реальный адрес клиента за мультиплексором | новое (Review Focus №1) | 7.2, 7.5, 7.7 |
