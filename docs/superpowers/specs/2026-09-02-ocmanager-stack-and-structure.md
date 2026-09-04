# ocmanager — стек и структура проекта

**Дата:** 2026-09-02
**Статус:** рекомендация к реализации
**Основание:** [2026-09-02-ocmanager-saas-design.md](2026-09-02-ocmanager-saas-design.md)

Документ отвечает на два вопроса: **какой стек** и **как разложены файлы**. Каждый выбор
привязан к конкретному требованию из спецификации — если требование изменится, видно, что
пересматривать.

---

## Часть 1. Стек

### 1.1. Сводка

| Слой | Выбор | Версия |
|---|---|---|
| Язык бэкенда | Python | 3.12 |
| HTTP-фреймворк | FastAPI + Uvicorn | 0.115+ / 0.32+ |
| ORM и миграции | SQLAlchemy 2 (async) + Alembic | 2.0+ / 1.14+ |
| Драйвер БД | asyncpg | 0.30+ |
| Валидация и конфиг | Pydantic v2 + pydantic-settings | 2.9+ |
| База данных | PostgreSQL | 16 |
| Очередь и планировщик | Redis + arq | 7.4 / 0.26+ |
| Telegram-бот | aiogram | 3.x |
| Криптография и PKI | `cryptography` | 43+ |
| Фронтенд | React + TypeScript + Vite | 18 / 5.x / 5.x |
| TMA SDK | `@telegram-apps/sdk-react` (+ `@telegram-apps/sdk`) | 3.x |
| Стили | Tailwind CSS | 3.x |
| Графики (этап 2) | Recharts | 2.x |
| Прокси и TLS | nginx (stream) + Caddy | 1.27 / 2.8 |
| VPN-сервер | ocserv | 1.3.x |
| Контейнеризация | Docker + Compose | 24+ / v2 |
| Тесты | pytest + pytest-asyncio + httpx + respx | — |
| Качество кода | ruff + mypy | — |
| Логирование | structlog | 24+ |

### 1.2. Почему Python и FastAPI

Требование «мультинодовость потом, одна нода сейчас» и «коробка для полутехнаря» тянут в
разные стороны: первое просит нормальной архитектуры, второе — минимума движущихся частей.
Python закрывает оба: один язык на API, воркер, бота и работу с ocserv, один образ для всех
трёх процессов.

Практическая причина не менее весомая: оба ваших прототипа на Python, и рабочие приёмы —
асинхронный `subprocess` со списком аргументов, стриминг `docker compose logs -f` в SSE с
корректным закрытием процесса, парсеры вывода `occtl` — переносятся почти как есть. На Go это
пришлось бы писать заново ради выигрыша, которого при одной ноде не видно.

FastAPI конкретно: асинхронность нужна не для нагрузки, а потому что система по своей природе
состоит из ожиданий — вызовы `docker exec`, HTTP к Telegram и платёжным провайдерам, SSE-потоки
логов, опрос `occtl`. На синхронном фреймворке каждое из этих ожиданий занимает воркер целиком;
именно на этом упирается ваш `ocserv-manager` на Flask.

**Что отвергнуто:** Go + Vue (один бинарник удобнее для дистрибуции, но выбрасывает весь
существующий код и опыт); Django (ORM и админка сильные, но асинхронность частичная, а
готовая админка всё равно не подходит под нужные экраны); Node.js (нет выигрыша, зато работа с
процессами и PKI менее удобна).

### 1.3. PostgreSQL, а не SQLite

Требование идемпотентности вебхуков реализуется через `UNIQUE(provider, external_id)` плюс
транзакция, охватывающая запись платежа и переход подписки. Одновременно с этим воркер каждые
5 минут пишет пачку `traffic_samples` и делает `UPSERT` в `traffic_daily`. SQLite при такой
смеси даёт `database is locked` — это ровно тот сценарий, на котором ломается ваш нынешний
`ocserv-manager`.

Плюс конкретные фичи, которые используются: `JSONB` для `payload` вебхуков, `name_i18n` и
`details` аудита; частичные индексы для выборок вроде «активные подписки, истекающие за 3 дня»;
`SELECT ... FOR UPDATE SKIP LOCKED` для безопасной выборки задач из `outbox` и `revocations`.

Цена — плюс один контейнер в коробке. Для целевого пользователя, который и так поднимает
`docker compose`, это не барьер.

### 1.4. Redis + arq для фоновой работы

Фоновых процессов в системе пять: обработка вебхуков с ретраями, reconcile каждые 5 минут,
сбор трафика каждые 5 минут, применение отзывов каждые 30 секунд, рассылка из `outbox`.
Первый — очередь, остальные четыре — расписание.

**arq** покрывает и то и другое одним инструментом: у него есть и очередь задач с ретраями и
backoff, и `cron`-задачи. Написан автором pydantic, работает на asyncio нативно, конфигурация
умещается в один файл.

**Что отвергнуто:** Celery (мощнее, но тяжелее и родом из синхронного мира — под asyncio живёт
неохотно, а его возможности здесь не нужны); чистый APScheduler (даёт расписание, но не даёт
надёжной очереди с ретраями, а она нужна для вебхуков); `asyncio.create_task` в процессе API
(отпадает сразу — задачи теряются при рестарте, а терять обработку оплаты нельзя).

Redis здесь же закрывает rate-limiting на TMA-эндпоинтах и кэш статуса ноды.

### 1.5. PKI на `cryptography`, а не на easy-rsa

Оба референса используют easy-rsa, потому что оба — обёртки над shell. У нас другая ситуация:
выпуск сертификата инициируется HTTP-запросом, результат нужно положить в БД одной транзакцией
с созданием `device`, а `.p12` собрать в память и не писать на диск.

Библиотека `cryptography` даёт всё это напрямую: генерацию ключа, выпуск сертификата с нужным
CN, сборку CRL, упаковку в PKCS#12 (`serialize_key_and_certificates`). Никаких временных
файлов, никакого разбора кодов возврата `openssl`, состояние PKI живёт в Postgres, а не в
`pki/index.txt`. Тестируется без контейнера и без файловой системы.

На диск попадают только приватный ключ и сертификат CA (режим `0600`, отдельный volume) и
сгенерированный CRL — его читает ocserv.

### 1.6. Фронтенд: два React-приложения

TMA обязана быть SPA — это требование платформы. Админку рекомендую делать тоже на React, в
том же Vite-монорепо: общие типы из OpenAPI-схемы, общий Tailwind-конфиг, общие компоненты
таблиц и форматирования байтов. Экраны админки — плотные таблицы с фильтрами, живые сессии и
графики за год; на HTMX это делается, но каждый следующий экран дороже предыдущего.

**Альтернатива, если хочется меньше сборки:** админка на Jinja + HTMX + SSE, как в вашем
`openconnect-manager`. Это честный вариант для этапа 1 — там админка тонкая. Но графики
этапа 2 и живые таблицы всё равно приведут к JavaScript, и переписывать придётся именно тогда,
когда будет меньше всего времени. Рекомендую сразу React.

Типы фронтенда генерируются из OpenAPI-схемы FastAPI (`openapi-typescript`) — контракт между
бэкендом и фронтендом проверяется компилятором, а не глазами.

### 1.7. Прокси и TLS

Задача нестандартная: на 443 должны сосуществовать ocserv с камуфляжем и HTTPS панели, а
сертификаты обоих доменов должны обновляться автоматически.

```
:80   ──► Caddy            ACME HTTP-01 для обоих доменов
:443  ──► nginx stream     ssl_preread, маршрутизация по SNI:
              vpn.example.com ──► ocserv:443      (TLS терминирует ocserv)
              app.example.com ──► caddy:8443      (TLS терминирует Caddy)
```

**Caddy** выпускает и продлевает оба сертификата — и свой, и для `vpn.example.com`, который
кладёт в общий volume; хук на продление дёргает `occtl reload`. Один ACME-клиент, ноль
ручной работы с certbot.

**nginx** здесь работает исключительно как L4-мультиплексор по SNI — он не расшифровывает
трафик и ничего не знает о содержимом. Модуль `ssl_preread` входит в стандартную сборку.

Админский процесс в прокси не заведён вообще: он слушает `127.0.0.1:8080`, доступ через
SSH-туннель.

### 1.8. Тестирование

`pytest` + `pytest-asyncio` для юнит-тестов; `httpx.AsyncClient` для API; `respx` для мока
Telegram и платёжных провайдеров; фикстуры реальных payload Tribute как контрактные тесты.

Главный тест продукта — интеграционный, поднимает настоящий ocserv в compose: выпуск
сертификата → подключение клиентом `openconnect` → проверка сессии в `occtl` → истечение
подписки → отказ в подключении. Он проверяет ровно то, за что платит клиент, и должен гоняться
в CI на каждый PR.

---

## Часть 2. Структура файлов

### 2.1. Верхний уровень

```
ocmanager/
├── backend/            весь Python: API, воркер, бот
├── frontend/           два Vite-приложения: TMA и админка
├── ocserv/             образ VPN-сервера, конфиг-шаблон, хуки
├── deploy/             compose, прокси, .env.example, установщик
├── scripts/            обслуживание: бэкап, восстановление, диагностика
├── tests/              интеграционные тесты (юнит-тесты живут рядом с кодом)
├── docs/
│   └── superpowers/specs/
├── .github/workflows/
├── Makefile
└── README.md
```

Граница проведена по **артефакту сборки**, а не по слою: `backend` даёт один Docker-образ,
из которого запускаются три процесса; `frontend` даёт статику; `ocserv` — свой образ.

### 2.2. Бэкенд

```
backend/
├── pyproject.toml              зависимости, ruff, mypy, pytest — всё в одном файле
├── Dockerfile                  multi-stage, один образ для api/worker/bot
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
└── src/ocmanager/
    │
    ├── apps/                   ── точки входа, по одной на процесс ──
    │   ├── public_api.py         FastAPI: /tma, /webhooks, /internal
    │   ├── admin_api.py          FastAPI: /admin  (bind 127.0.0.1)
    │   ├── worker.py             arq WorkerSettings: очередь + cron
    │   └── bot.py                aiogram: polling/webhook
    │
    ├── core/                   ── инфраструктура, без бизнес-логики ──
    │   ├── config.py             pydantic-settings, чтение .env
    │   ├── settings_store.py     таблица settings: то, что меняется из админки
    │   ├── db.py                 async engine, sessionmaker, Base
    │   ├── logging.py            structlog, JSON в stdout
    │   ├── security.py           bcrypt, TOTP, одноразовые токены
    │   ├── errors.py             доменные исключения и их HTTP-отображение
    │   ├── i18n.py               загрузка каталогов, выбор локали
    │   └── shell.py              async subprocess: run() и stream()
    │
    ├── events/                 ── связь между модулями ──
    │   ├── types.py              SubscriptionActivated, DeviceRevoked, …
    │   └── bus.py                публикация и подписка, доставка через arq
    │
    ├── billing/                ── деньги. Не знает про ocserv ──
    │   ├── models.py             Plan, Payment, WebhookEvent
    │   ├── schemas.py
    │   ├── service.py            приём платежа → доменное событие
    │   ├── router.py             POST /webhooks/{provider}
    │   └── providers/
    │       ├── base.py           PaymentProvider: verify(), parse(), checkout_url()
    │       ├── tribute.py        trbt-signature, маппинг событий
    │       ├── stars.py          этап 2
    │       └── crypto.py         этап 2
    │
    ├── subscriptions/          ── право доступа. Не знает, кто заплатил ──
    │   ├── models.py             Client, Subscription
    │   ├── schemas.py
    │   ├── state.py              FSM: разрешённые переходы и их эффекты
    │   ├── service.py            activate / extend / cancel / expire
    │   ├── quotas.py             учёт трафика против лимита плана (этап 2)
    │   └── tasks.py              cron: истечения, предупреждения
    │
    ├── provisioning/           ── ключи. Не знает про деньги ──
    │   ├── models.py             Device, Revocation
    │   ├── schemas.py
    │   ├── service.py            issue_device / revoke_device
    │   ├── allowlist.py          построение и атомарная запись allowed.list
    │   ├── tasks.py              cron: применение отзывов, перестройка CRL
    │   └── pki/
    │       ├── ca.py             создание и загрузка CA
    │       ├── certs.py          выпуск клиентского сертификата
    │       ├── crl.py            сборка CRL
    │       └── p12.py            упаковка PKCS#12 в память
    │
    ├── nodes/                  ── ocserv. Не знает про подписки ──
    │   ├── models.py             Node, TrafficSample, TrafficDaily, SessionLog
    │   ├── schemas.py
    │   ├── service.py            статус, сессии, действия
    │   ├── traffic.py            дельты, агрегация в traffic_daily, ретеншн
    │   ├── reconcile.py          желаемое состояние против фактического
    │   ├── logs.py               стриминг логов для SSE
    │   ├── router_internal.py    POST /internal/session-end от disconnect-script
    │   ├── driver/
    │   │   ├── base.py           NodeDriver: интерфейс
    │   │   └── local_docker.py   docker exec + работа с volume
    │   └── occtl/
    │       ├── client.py         вызовы occtl
    │       └── parser.py         разбор вывода в структуры
    │
    ├── notifications/          ── доставка. Не знает ни про что ──
    │   ├── models.py             OutboxMessage
    │   ├── service.py            постановка в очередь
    │   ├── telegram.py           отправка, обработка лимитов
    │   ├── tasks.py              cron: разбор outbox с ретраями
    │   └── templates/
    │       ├── ru.json
    │       └── en.json
    │
    ├── tma/                    ── Mini App API ──
    │   ├── auth.py               валидация initData, TTL, защита от replay
    │   ├── router.py             /tma/plans, /tma/subscription, /tma/devices
    │   ├── schemas.py
    │   └── instructions.py       тексты и deep-link под iOS/Android/Win/macOS
    │
    ├── admin/                  ── админ-API и UI ──
    │   ├── deps.py               авторизация, права
    │   ├── auth.py               логин, сессии, TOTP
    │   └── routers/
    │       ├── overview.py
    │       ├── clients.py
    │       ├── subscriptions.py
    │       ├── plans.py
    │       ├── payments.py
    │       ├── devices.py
    │       ├── node.py           статус, действия, SSE-логи
    │       ├── stats.py          выборки для графиков (этап 2)
    │       └── audit.py
    │
    └── audit/
        ├── models.py             AuditLog
        └── service.py            запись действий admin / system / client
```

**Как читать эту раскладку.** Каждый доменный модуль — самодостаточная папка с моделями,
схемами и сервисом. Импорт между доменными модулями запрещён: они общаются через
`events/`. Разрешено всем импортировать `core/` и `events/`.

Проверка, что граница не поехала:

```bash
# billing не должен знать про ocserv и сертификаты
grep -rE "from ocmanager\.(nodes|provisioning)" backend/src/ocmanager/billing/ && echo НАРУШЕНИЕ
```

Такую проверку имеет смысл поставить в CI отдельным шагом — граница модулей сама себя не
защитит, а её размывание и есть главный способ превратить этот проект в неподдерживаемый.

**Юнит-тесты лежат рядом с кодом** (`subscriptions/test_state.py`), а не в отдельном дереве:
так их видно при чтении модуля и труднее забыть обновить.

### 2.3. Фронтенд

```
frontend/
├── package.json                npm workspaces
├── tsconfig.base.json
├── packages/
│   ├── api-types/              сгенерировано из OpenAPI, в git не коммитится
│   └── ui/                     общее: форматирование байтов, дат, таблицы, тосты
├── tma/
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── telegram.ts          initData, тема, кнопки Telegram
│       ├── api.ts
│       ├── i18n/{ru,en}.json
│       └── screens/
│           ├── Plans.tsx
│           ├── Subscription.tsx
│           ├── Devices.tsx
│           ├── DeviceCreate.tsx   выбор ОС → выпуск → пароль и ссылка
│           └── Instructions.tsx   пошаговая инструкция + QR
└── admin/
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── api.ts
        ├── i18n/{ru,en}.json
        └── pages/
            ├── Overview.tsx
            ├── Clients.tsx  ClientDetail.tsx
            ├── Subscriptions.tsx
            ├── Plans.tsx
            ├── Payments.tsx
            ├── Devices.tsx
            ├── Node.tsx          статус, действия, live-логи
            ├── Stats.tsx         этап 2
            ├── Audit.tsx
            └── Settings.tsx
```

`packages/api-types` генерируется командой из `Makefile` и намеренно не коммитится — иначе он
разъезжается с бэкендом незаметно.

### 2.4. ocserv

```
ocserv/
├── Dockerfile                  ocserv + скрипты хуков
├── ocserv.conf.tmpl            шаблон: домен, камуфляж-токен, сеть, пути
├── entrypoint.sh               подстановка значений из окружения, старт
└── hooks/
    ├── connect.sh              grep в allowed.list; exit 1 = отказ в подключении
    └── disconnect.sh           POST финальных счётчиков в /internal/session-end
```

Хуки намеренно предельно примитивны — это shell без сетевых вызовов и без зависимостей.
`connect.sh` вызывается на каждое подключение, и любая его хрупкость становится отказом
в обслуживании оплатившего клиента.

### 2.5. Деплой

```
deploy/
├── docker-compose.yml          ocserv, nginx, caddy, api-public, api-admin,
│                               worker, bot, postgres, redis
├── docker-compose.dev.yml      оверрайд: hot-reload, порты наружу, без прокси
├── .env.example                все переменные с комментариями
├── nginx/
│   └── stream.conf             ssl_preread, маршрутизация по SNI
├── caddy/
│   └── Caddyfile               ACME для обоих доменов, прокси на api-public
└── install.sh                  проверки, генерация секретов и CA, первый запуск
```

### 2.6. Скрипты и тесты

```
scripts/
├── backup.sh                   pg_dump + tar PKI, шифрование, ретеншн
├── restore.sh                  восстановление из бэкапа
├── create_admin.py             первый администратор
├── issue_device.py             выпуск ключа из CLI, в обход TMA
└── doctor.sh                   диагностика: порты, сертификаты, связность, reconcile

tests/
├── conftest.py
├── integration/
│   ├── test_purchase_flow.py       вебхук → подписка → устройство → .p12
│   ├── test_vpn_connection.py      реальный ocserv + клиент openconnect
│   ├── test_expiry_cutoff.py       истечение → отказ в подключении
│   └── test_reconcile.py           порча состояния → самовосстановление
└── fixtures/
    └── webhooks/tribute/*.json     зафиксированные реальные payload
```

`tests/integration/test_vpn_connection.py` — главный тест продукта. Он единственный
проверяет всю цепочку до фактического подключения; остальные тесты проверяют части.

### 2.7. Порядок появления файлов в этапе 1

Раскладка выше — целевая. В этапе 1 создаются не все папки: `billing/providers/stars.py` и
`crypto.py`, `subscriptions/quotas.py`, `admin/routers/stats.py` появляются в этапе 2,
`scripts/backup.sh` и `restore.sh` — в этапе 3, второй `NodeDriver` — в этапе 4. Каталог
`docs/superpowers/specs/` пополняется отдельной спецификацией на каждый этап.
