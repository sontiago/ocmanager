# TMA: развёртывание и начало разработки

Практическая инструкция по части Telegram Mini App: как поднять её на сервере и как начать
писать код. Опирается на [спецификацию](../superpowers/specs/2026-09-02-ocmanager-saas-design.md)
и [документ о стеке](../superpowers/specs/2026-09-02-ocmanager-stack-and-structure.md).

**Главное упрощение:** для работы над TMA **ocserv не нужен**. Ни VPN-сервер, ни PKI, ни
камуфляж, ни SNI-мультиплексор на 443. На этом этапе есть только домен, Caddy, `api-public`
и Postgres — Caddy держит 443 целиком и сам берёт сертификат. nginx с `ssl_preread` появится
позже, когда рядом встанет ocserv. Не поднимайте его сейчас: это лишний слой, который нечего
отлаживать.

---

## Часть A. Развёртывание

### A0. Что нужно заранее

| Что | Зачем | Комментарий |
|---|---|---|
| Домен | Telegram открывает Mini App только по HTTPS с валидным сертификатом | Достаточно поддомена: `app.example.com` |
| VPS с публичным IP | ACME-проверка и приём вебхуков | Минимально 1 vCPU / 1 ГБ |
| Docker + Compose v2 | запуск стека | — |
| Аккаунт Telegram | создание бота | — |

Самоподписанный сертификат Telegram не примет, `localhost` в качестве URL Mini App — тоже.
Для локальной разработки это обходится (раздел B1 и B6), но боевой стенд требует настоящего
домена.

### A1. Создание бота и Mini App в BotFather

Откройте [@BotFather](https://t.me/BotFather).

**Шаг 1 — бот:**

```
/newbot
→ имя:     ocmanager VPN
→ username: ocmanager_vpn_bot        (должен заканчиваться на bot)
```

В ответ придёт **токен вида `1234567890:AA...`**. Это главный секрет системы: им подписывается
`initData`, и по нему проверяется каждый запрос из Mini App. Сразу положите его в `.env` как
`BOT_TOKEN` и никогда не коммитьте.

**Шаг 2 — Mini App:**

```
/newapp
→ выбрать бота
→ название, описание, иконка 640×360
→ Web App URL:  https://app.example.com
→ short name:   app
```

Получите прямую ссылку `https://t.me/ocmanager_vpn_bot/app`.

**Шаг 3 — кнопка меню** (чтобы приложение открывалось из чата с ботом):

```
/mybots → выбрать бота → Bot Settings → Menu Button → Edit menu button URL
→ https://app.example.com
→ текст кнопки: Открыть
```

Проверить, что дошло: `curl "https://api.telegram.org/bot$BOT_TOKEN/getMe"` — должен вернуть
`"ok": true`.

### A2. DNS

A-запись `app.example.com` → IP сервера. Проверка:

```bash
dig +short app.example.com
```

Значение должно совпасть с IP сервера, иначе Caddy не получит сертификат. Если домен за
Cloudflare — на время выпуска сертификата переведите запись в режим **DNS only** (серое
облако), либо настройте Caddy на DNS-01.

### A3. Стек этапа TMA

`deploy/docker-compose.tma.yml` — урезанная стека без ocserv, nginx, воркера и бота:

```yaml
services:
  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - ../frontend/tma/dist:/srv/tma:ro
      - caddy-data:/data
    depends_on: [api-public]

  api-public:
    build: ../backend
    restart: unless-stopped
    command: uvicorn ocmanager.apps.public_api:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on: [postgres]

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ocmanager
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ocmanager
    volumes: [pg-data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ocmanager"]
      interval: 10s

volumes:
  caddy-data:
  pg-data:
```

`deploy/caddy/Caddyfile`:

```
app.example.com {
	encode gzip

	handle /api/* {
		reverse_proxy api-public:8000
	}

	handle /webhooks/* {
		reverse_proxy api-public:8000
	}

	handle {
		root * /srv/tma
		try_files {path} /index.html      # SPA: любой путь отдаёт index.html
		file_server
	}

	header {
		Referrer-Policy strict-origin-when-cross-origin
		X-Content-Type-Options nosniff
	}
}
```

Два момента, которые ломают TMA чаще всего:

**`try_files {path} /index.html`** обязателен. Без него любой маршрут кроме корня даёт 404, а
Telegram открывает Mini App по URL со своими query-параметрами.

**Не ставьте `X-Frame-Options: DENY`.** Telegram открывает Mini App в iframe (веб-клиент), и
этот заголовок сделает приложение пустым белым экраном без единой ошибки в консоли.

### A4. Переменные окружения

`deploy/.env` (в git — только `.env.example`):

```bash
BOT_TOKEN=1234567890:AA...
PUBLIC_URL=https://app.example.com
POSTGRES_PASSWORD=<openssl rand -base64 24>
DATABASE_URL=postgresql+asyncpg://ocmanager:<пароль>@postgres:5432/ocmanager
SECRET_KEY=<openssl rand -hex 32>
INIT_DATA_TTL_SECONDS=300
DEFAULT_LANG=ru
```

### A5. Сборка и запуск

```bash
cd frontend && npm ci && npm run build -w tma
cd ../deploy && docker compose -f docker-compose.tma.yml up -d --build
docker compose -f docker-compose.tma.yml logs -f caddy
```

В логах Caddy должна появиться строка о полученном сертификате. Если её нет — почти всегда
дело в DNS или в закрытом 80 порту (ACME HTTP-01 ходит именно туда).

### A6. Проверка

```bash
curl -I https://app.example.com                 # 200, валидный TLS
curl -s https://app.example.com/api/health      # {"status":"ok"}
```

Дальше откройте `https://t.me/ocmanager_vpn_bot/app` с телефона. Если приложение открылось и
показало данные пользователя — развёртывание закончено.

---

## Часть B. Как начать программировать

### B1. Принцип: разрабатывать в браузере, а не в Telegram

Самая частая ошибка на старте — пытаться отлаживать Mini App внутри Telegram. Там нет
нормального DevTools, нет hot-reload, а каждая правка требует передеплоя.

Правильный цикл: **99 % времени приложение открыто в обычном браузере на `localhost:5173`**, а
окружение Telegram подменяется моком. В настоящем Telegram проверяются только вещи, которые
без него не работают: тема, нативные кнопки, платёжный поток. Это раздел B6.

### B2. Создание проекта

```bash
mkdir -p frontend && cd frontend
npm init -y
npm pkg set workspaces='["tma","admin","packages/*"]' --json

npm create vite@latest tma -- --template react-ts
cd tma
npm i @telegram-apps/sdk-react @telegram-apps/sdk
npm i -D tailwindcss postcss autoprefixer openapi-typescript
npx tailwindcss init -p
```

Зафиксируйте версии в `package.json` точными числами, а не диапазонами: SDK Telegram
развивается быстро, и `^` однажды приведёт сборку в нерабочее состояние.

`vite.config.ts`:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,          // слушать 0.0.0.0 — нужно для туннеля
    allowedHosts: true,  // иначе Vite отклонит хост туннеля (см. B6)
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
```

### B3. Мок окружения Telegram

`src/mockEnv.ts` — подключается **только в dev-сборке**, в production не попадает:

```ts
import { mockTelegramEnv } from '@telegram-apps/sdk-react'

if (import.meta.env.DEV) {
  const user = {
    id: 99281932,
    first_name: 'Иван',
    username: 'ivan',
    language_code: 'ru',
  }

  const initDataRaw = new URLSearchParams([
    ['user', JSON.stringify(user)],
    ['auth_date', Math.floor(Date.now() / 1000).toString()],
    ['hash', 'dev-mock-hash'],
  ]).toString()

  mockTelegramEnv({
    launchParams: {
      tgWebAppVersion: '8.0',
      tgWebAppPlatform: 'tdesktop',
      tgWebAppThemeParams: { bg_color: '#ffffff', text_color: '#000000' },
      tgWebAppData: initDataRaw,
    },
  })

  console.warn('Telegram environment mocked — только для разработки')
}
```

Подпись здесь заведомо недействительная, поэтому бэкенд должен принимать её **только** при
включённом флаге `TMA_ALLOW_DEV_INITDATA=true`, который в production выключен. Это единственное
место во всей системе, где проверка подписи может быть ослаблена, и оно должно быть громко
помечено в коде.

### B4. Инициализация SDK

`src/init.ts`:

```ts
import { init, initDataRaw, backButton, themeParams } from '@telegram-apps/sdk-react'

export function initApp() {
  init()
  backButton.mount()
  themeParams.mount()
  themeParams.bindCssVars()   // цвета Telegram становятся CSS-переменными
  return initDataRaw()
}
```

`src/main.tsx`:

```tsx
import './mockEnv'            // ВАЖНО: строго первым импортом
import React from 'react'
import { createRoot } from 'react-dom/client'
import { initApp } from './init'
import { App } from './App'
import './index.css'

initApp()

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

Порядок импортов принципиален: `mockEnv` обязан отработать до `init()`, иначе SDK не найдёт
окружения и упадёт.

### B5. Передача initData на бэкенд

`src/api.ts` — сырая строка `initData` уходит в заголовке при **каждом** запросе. Своих
токенов, cookie и сессий у TMA нет: Telegram уже подписал пользователя, и это единственный
источник его личности.

```ts
import { initDataRaw } from '@telegram-apps/sdk-react'

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const raw = initDataRaw()
  if (!raw) throw new Error('Нет initData — приложение открыто вне Telegram')

  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `tma ${raw}`,
      ...init?.headers,
    },
  })

  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}
```

### B6. Проверка подписи на бэкенде

`backend/src/ocmanager/tma/auth.py`. Алгоритм задан Telegram и не допускает вольностей.

```python
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl


class InitDataInvalid(Exception):
    pass


def parse_and_validate(raw: str, bot_token: str, ttl: timedelta) -> dict:
    """Проверяет подпись initData и возвращает объект пользователя Telegram."""
    pairs = dict(parse_qsl(raw, strict_parsing=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataInvalid("нет поля hash")

    # Все оставшиеся поля, отсортированные по ключу, через перевод строки
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    # Ключ выводится из токена бота с константной солью "WebAppData"
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataInvalid("подпись не совпала")

    auth_date = datetime.fromtimestamp(int(pairs["auth_date"]), tz=timezone.utc)
    if datetime.now(timezone.utc) - auth_date > ttl:
        raise InitDataInvalid("initData просрочена")

    return json.loads(pairs["user"])
```

Три детали, каждая из которых ломает проверку, если сделать иначе:

- Из строки убирается **только** `hash`. Все прочие поля участвуют в подписи.
- Значения берутся **уже декодированными** — `parse_qsl` делает это сам. Повторное или
  пропущенное декодирование даёт несовпадение подписи.
- Сравнение — `hmac.compare_digest`, а не `==`.

Проверка `auth_date` против TTL обязательна: без неё перехваченная строка `initData` работает
вечно. В спецификации зафиксировано 5 минут.

У Telegram есть и второй путь — поле `signature` с подписью Ed25519, которое позволяет
проверять данные без токена бота (при таком способе из строки исключаются оба поля — и `hash`,
и `signature`). Нам он не нужен: токен бота и так на этом сервере.

Зависимость FastAPI:

```python
from fastapi import Depends, Header, HTTPException

async def current_client(authorization: str = Header(...)) -> Client:
    if not authorization.startswith("tma "):
        raise HTTPException(401, "ожидается схема tma")
    try:
        tg_user = parse_and_validate(
            authorization[4:], settings.bot_token, settings.init_data_ttl
        )
    except InitDataInvalid as exc:
        raise HTTPException(401, str(exc)) from exc
    return await clients.get_or_create(tg_user)
```

`get_or_create` — то место, где клиент впервые появляется в базе: `telegram_id`, `username`,
`lang` из `language_code`. Отдельной регистрации в системе нет.

### B7. Первый вертикальный срез

Не начинайте с вёрстки всех экранов. Первым делом доведите до конца **одну** цепочку
«фронтенд → бэкенд → база» — она вскроет все проблемы интеграции, пока их дёшево чинить.

Бэкенд, `tma/router.py`:

```python
@router.get("/plans", response_model=list[PlanOut])
async def list_plans(client: Client = Depends(current_client)):
    return await plans.list_active(lang=client.lang)
```

Фронтенд, `src/screens/Plans.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { api } from '../api'

type Plan = {
  code: string
  name: string
  price_amount: number
  currency: string
  duration_days: number
  device_limit: number
}

export function Plans() {
  const [plans, setPlans] = useState<Plan[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Plan[]>('/tma/plans').then(setPlans).catch(e => setError(String(e)))
  }, [])

  if (error) return <p className="p-4 text-red-500">{error}</p>
  if (!plans) return <p className="p-4">Загрузка…</p>

  return (
    <ul className="p-4 space-y-3">
      {plans.map(p => (
        <li key={p.code} className="rounded-xl border p-4">
          <div className="font-semibold">{p.name}</div>
          <div className="text-sm opacity-70">
            {p.duration_days} дней · {p.device_limit} устройств
          </div>
          <div className="mt-2">{p.price_amount} {p.currency}</div>
        </li>
      ))}
    </ul>
  )
}
```

Запуск в двух терминалах:

```bash
cd backend && uvicorn ocmanager.apps.public_api:app --reload --port 8000
```

```bash
cd frontend/tma && npm run dev
```

Откройте `http://localhost:5173`. Должен появиться список тарифов, а в логах бэкенда — принятая
`initData` от замоканного пользователя.

### B8. Проверка в настоящем Telegram

Когда срез работает в браузере, проверьте его в реальном клиенте, не выкладывая на сервер.

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:5173
```

Команда выдаст адрес вида `https://random-words-1234.trycloudflare.com`. Впишите его в
BotFather (`/myapps` → приложение → Edit Web App URL) и откройте бота.

Если Vite ответит `Blocked request. This host is not allowed` — это `server.allowedHosts` из
раздела B2; убедитесь, что параметр стоит.

После проверки верните боевой URL в BotFather: адрес туннеля живёт до завершения команды.

### B9. Порядок работы над TMA

1. `/health` через Caddy — проверка, что сеть и прокси собраны верно.
2. `current_client` и `get_or_create` — клиент появляется в базе.
3. Экран тарифов (B7) — первый сквозной срез.
4. Экран подписки: срок, остаток трафика, статус.
5. Список устройств и выпуск нового: выбор ОС → пароль и одноразовая ссылка.
6. Экран инструкций с QR под выбранную ОС.
7. Покупка: кнопка ведёт на checkout-ссылку Tribute, приложение закрывается через
   `miniApp.close()`, возврат — по уведомлению бота.

Пункты 1–3 не требуют ни ocserv, ни платёжного провайдера. Пункт 5 требует готового
`provisioning`, пункт 7 — рабочего вебхука Tribute; их можно вести параллельно на бэкенде,
пока фронтенд идёт по 1–4.

### B10. Частые грабли

| Симптом | Причина |
|---|---|
| Белый экран в веб-клиенте Telegram, в консоли пусто | заголовок `X-Frame-Options` — уберите его |
| 404 на любом маршруте кроме корня | нет `try_files {path} /index.html` в Caddyfile |
| `Blocked request. This host is not allowed` | не задан `server.allowedHosts` в `vite.config.ts` |
| `initDataRaw()` возвращает `undefined` | `mockEnv` импортирован не первым, либо `init()` не вызван |
| Подпись не сходится, хотя всё «правильно» | значения перекодированы вручную поверх `parse_qsl`, либо из строки убрано лишнее поле |
| Работает в браузере, 401 в Telegram | включён `TMA_ALLOW_DEV_INITDATA` — в production он обязан быть выключен |
| Caddy не берёт сертификат | закрыт 80 порт, неверная A-запись, либо Cloudflare в режиме proxy |
| Тема не совпадает с клиентом | не вызван `themeParams.bindCssVars()` |
