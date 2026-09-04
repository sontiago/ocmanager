# TMA (Telegram Mini App) — план реализации на моках

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ САБ-СКИЛЛ — используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения плана задача за задачей.
> Шаги размечены чекбоксами (`- [ ]`) для отслеживания прогресса.

**Дата:** 2026-09-03
**Основание:** [SaaS-дизайн](../specs/2026-09-02-ocmanager-saas-design.md) ·
[стек и структура](../specs/2026-09-02-ocmanager-stack-and-structure.md) ·
[руководство по TMA](../../guides/tma-setup-and-development.md)

**Goal:** Полностью работающее клиентское приложение Telegram Mini App —
тарифы, trial, подписка, устройства, выдача `.p12`, инструкции под ОС, покупка —
разработанное и оттестированное целиком на моках, с переключением на реальный
бэкенд изменением одной переменной окружения.

**Architecture:** Приложение разделено швом `ApiClient` — TypeScript-интерфейс,
описывающий ровно те девять операций, которые TMA нужны от бэкенда. У интерфейса
две реализации: `createMockClient()` (состояние в памяти, сценарии, задержки,
инъекция ошибок) и `createHttpClient()` (`fetch` с заголовком
`Authorization: tma <initDataRaw>`). Реализация выбирается на старте по
`VITE_API_MODE`. Ни один экран, ни один хук и ни один тест не знает, какая из них
активна. Второй мок — окружение Telegram (`mockTelegramEnv` из SDK), он даёт
разработку в обычном браузере с DevTools и hot-reload вместо отладки внутри
Telegram.

**Tech Stack:** React 19.2 · TypeScript 6 · Vite 8 · Tailwind CSS 4 ·
`@telegram-apps/sdk-react` 3.3 · `react-router` 7 · `@tanstack/react-query` 5 ·
`qrcode` 1.5 · Vitest 4 + Testing Library 16 · oxlint

---

## Global Constraints

Требования уровня проекта. Они неявно входят в требования **каждой** задачи ниже.

- **i18n `ru` / `en` с первого дня.** Ни одной строки, видимой пользователю,
  в JSX напрямую. Язык клиента берётся из Telegram (`language_code`), по
  умолчанию — `ru` (`DEFAULT_LANG=ru`).
- **Точные версии зависимостей в `package.json`**, без диапазонов `^` и `~`.
  Обоснование из руководства: SDK Telegram развивается быстро, и `^` однажды
  приведёт сборку в нерабочее состояние. Диапазоны в текущем scaffold —
  технический долг, который снимается в Задаче 1.
- **`mockEnv` и мок-клиент не попадают в production-бандл.** Оба подключаются
  через динамический `import()` под `if (import.meta.env.DEV)`. Проверяется
  тестом на содержимое собранного бандла (Задача 21).
- **Сырая строка `initData` уходит в заголовке при каждом запросе**
  (`Authorization: tma <raw>`). Своих токенов, cookie и сессий у TMA нет.
- **Ни одного `X-Frame-Options`** в раздаче фронтенда — Telegram открывает
  Mini App в iframe.
- **SPA-фоллбэк обязателен** (`try_files {path} /index.html` в Caddyfile) —
  иначе любой маршрут кроме корня даёт 404.
- **Деньги — только целые числа в минорных единицах** (копейки, центы).
  Никаких `float` для сумм.
- **Даты — строки ISO 8601 в UTC** на границе API; в `Date` превращаются
  только в форматтерах.
- **Одноразовый пароль `.p12` и ссылка на скачивание показываются ровно один
  раз** и не сохраняются ни в `localStorage`, ни в кэше React Query, ни в
  URL. TTL ссылки — 15 минут.
- **Статусы подписки** — ровно этот набор, без расширений:
  `pending_payment`, `trial`, `active`, `expired`, `exhausted`, `cancelled`,
  `blocked`.
- **`cancelled` не отключает доступ.** Это `auto_renew = false` при живом
  `expires_at`. UI обязан показывать такую подписку как работающую.
- **Одно устройство = один сертификат = один ocserv-username.** Устройств не
  больше `plan.device_limit`.
- **Все тесты пишутся до реализации** (TDD), запускаются и наблюдаются
  падающими, прежде чем писать код.
- **Коммит в конце каждой задачи**, формат `feat(tma): ...` / `test(tma): ...` /
  `chore(tma): ...`.

---

## Принятые решения и допущения

Пункты, по которым спецификация не даёт однозначного ответа. Каждый — реальная
развилка; если бэкенд решит иначе, правка локализована в указанном файле.

| # | Решение | Где живёт | Что если бэкенд решит иначе |
|---|---|---|---|
| 1 | Контракт API пишется руками сейчас, генерация из OpenAPI (`openapi-typescript`) подключается в Задаче 20, когда бэкенд появится | `src/api/types.ts` | Сверка типов — единственная работа Задачи 20 |
| 2 | Тексты инструкций под ОС живут во фронтенде (i18n-каталоги), а не приходят из `tma/instructions.py`. С бэкенда берутся только параметры подключения: хост шлюза и камуфляж-токен | `src/i18n/*.ts`, `GET /tma/connection` | Заменить статический каталог на данные ответа — меняется один компонент |
| 3 | `price_amount` — целое в минорных единицах | `src/api/types.ts` | Правка форматтера `formatMoney` |
| 4 | `GET /tma/subscription` возвращает `200 {"subscription": null}` для клиента без подписки, а не `404` | `src/api/http.ts` | Правка одного метода в `http.ts` |
| 5 | Ошибки API — тело `{"error": {"code": "...", "message": "..."}}` с фиксированным списком кодов | `src/api/errors.ts` | Правка маппинга в `http.ts` |
| 6 | Навигация — `BrowserRouter` (Caddyfile уже даёт `try_files`), а не `HashRouter`: Telegram кладёт `tgWebAppData` в hash, и HashRouter с ним конфликтует | `src/app/router.tsx` | — |
| 7 | Возврат из оплаты — приложение закрывается через `miniApp.close()`, статус приходит уведомлением бота; при повторном открытии подписка перечитывается | `src/screens/Checkout` | Если Tribute даёт `return_url` — добавить экран ожидания |

---

## Карта файлов

Целевая раскладка `frontend/tma/src`. Каждый файл — одна ответственность.
Колонка «Задача» — где файл появляется.

```
src/
├── main.tsx                     точка входа: bootstrap → mockEnv → init → render   T2
├── env.ts                       чтение и валидация import.meta.env                 T1
│
├── telegram/                 ── всё, что знает про SDK Telegram ──
│   ├── init.ts                  init(), mount компонентов, bindCssVars             T2
│   ├── mockEnv.ts               mockTelegramEnv, только DEV                        T2
│   ├── auth.ts                  initDataRaw() + user, единая точка доступа         T2
│   ├── backButton.ts            useBackButton(): синхронизация с роутером          T10
│   ├── haptics.ts               безопасные обёртки (в браузере — no-op)            T2
│   └── links.ts                 openLink / openTelegramLink / close                T14
│
├── api/                      ── шов между UI и бэкендом ──
│   ├── types.ts                 DTO: Plan, Subscription, Device, …                 T4
│   ├── errors.ts                ApiError + коды                                    T4
│   ├── contract.ts              interface ApiClient — девять операций              T4
│   ├── http.ts                  createHttpClient(): реальная реализация            T7
│   ├── index.ts                 createApiClient() по env.apiMode                   T8
│   ├── ApiProvider.tsx          React-контекст, точка инъекции в тестах            T8
│   ├── queryClient.ts           настройка кэша и политики повторов                 T8
│   ├── queryKeys.ts             ключи кэша React Query                             T8
│   ├── hooks.ts                 usePlans / useSubscription / useDevices / мутации  T8
│   └── generated.d.ts           из OpenAPI, в git не коммитится                    T20
│   └── mock/
│       ├── fixtures.ts          справочные данные: планы, устройства               T5
│       ├── scenarios.ts         именованные сценарии состояния                     T5
│       ├── store.ts             мутабельное состояние в памяти + reset             T5
│       └── client.ts            createMockClient(): задержки, ошибки, мутации      T6
│
├── i18n/                     ── тексты ──
│   ├── ru.ts                    каталог-эталон, из него выводится MessageKey       T3
│   ├── en.ts                    Record<MessageKey, string> — полнота на компиляции T3
│   ├── plural.ts                Intl.PluralRules для ru/en                         T3
│   ├── I18nProvider.tsx         контекст, определение языка из Telegram            T3
│   └── useT.ts                  t(key, params) с интерполяцией                     T3
│
├── lib/                      ── чистые функции ──
│   ├── format.ts                байты, деньги, даты, длительности                  T9
│   ├── subscription.ts          производные от статуса: активна? сколько осталось? T9
│   └── clipboard.ts             копирование с фоллбэком                            T17
│
├── ui/                       ── примитивы на теме Telegram ──
│   ├── Button.tsx                                                                  T11
│   ├── Cell.tsx  List.tsx  Section.tsx                                             T11
│   ├── Badge.tsx  ProgressBar.tsx                                                  T11
│   ├── Skeleton.tsx  Spinner.tsx                                                   T11
│   ├── EmptyState.tsx  ErrorState.tsx                                              T11
│   ├── Sheet.tsx                модальный лист снизу                               T11
│   ├── CopyField.tsx            значение с кнопкой «скопировать»                    T17
│   └── QrCode.tsx               обёртка над qrcode                                 T17
│
├── app/                      ── каркас ──
│   ├── App.tsx                  провайдеры: Query → Api → I18n → Router            T12
│   ├── routes.ts                константы путей (отдельно во избежание цикла)      T12
│   ├── router.tsx               таблица маршрутов, ленивые экраны                  T12
│   ├── Layout.tsx               контейнер + таб-бар + safe-area                    T12
│   ├── TabBar.tsx                                                                  T12
│   ├── DevPanel.tsx             переключатель сценариев, только DEV                T13
│   ├── ErrorBoundary.tsx        перехват исключений рендера                        T19
│   └── Gate.tsx                 вне Telegram / заблокирован — дальше не пускает    T19
│
├── screens/
│   ├── Plans/                   тарифы, trial, запуск покупки                      T14
│   ├── Subscription/            статус, срок, трафик, автопродление                T15
│   ├── Devices/                 список, онлайн, трафик, отзыв                      T16
│   ├── DeviceCreate/            выбор ОС → выпуск                                  T17
│   ├── DeviceSecret/            пароль + одноразовая ссылка + QR (показ один раз)  T17
│   └── Instructions/            пошагово под ОС + deep-link                        T18
│
├── test/
│   ├── setup.ts                 jest-dom и cleanup после каждого теста             T1
│   ├── renderWithProviders.tsx  хелпер: обёртка всеми провайдерами                 T11
│   └── contract.suite.ts        общий набор тестов для обеих реализаций ApiClient  T7
│
├── vite-env.d.ts                типы import.meta.env                               T1
└── index.css                    Tailwind 4 + мост темы Telegram                    T1
```

---

## Фазы

| Фаза | Задачи | Что готово в конце |
|---|---|---|
| 0. Фундамент | 1–3 | Сборка, тесты, Telegram-окружение, i18n |
| 1. Шов данных | 4–8 | `ApiClient`, мок, HTTP-реализация, хуки |
| 2. Каркас | 9–13 | Форматтеры, примитивы, роутинг, dev-панель |
| 3. Экраны | 14–19 | Шесть экранов и глобальные состояния, всё на моках |
| 4. Переключение | 20–21 | Реальный бэкенд, production-сборка |

Фаза 3 — единственная, где работа может идти параллельно: экраны не зависят
друг от друга, только от Фаз 0–2.

---

# Фаза 0. Фундамент

### Задача 1: Тулчейн — Tailwind 4, Vitest, чистка scaffold

Сейчас в `frontend/tma` лежит дефолтный шаблон Vite: демо-счётчик, логотипы,
`App.css` на 200 строк. Tailwind 4 стоит в `devDependencies`, но не подключён:
нет плагина `@tailwindcss/vite` и нет `@import "tailwindcss"` в CSS. Тестового
раннера нет вообще. Задача снимает всё это одним заходом, потому что каждая
часть по отдельности не даёт проверяемого результата.

**Files:**
- Modify: `frontend/tma/package.json`
- Modify: `frontend/tma/vite.config.ts`
- Modify: `frontend/tma/src/index.css`
- Modify: `frontend/tma/index.html`
- Modify: `frontend/tma/tsconfig.app.json`
- Create: `frontend/tma/src/env.ts`
- Create: `frontend/tma/src/test/setup.ts`
- Create: `frontend/tma/src/env.test.ts`
- Create: `frontend/tma/.env.example`
- Create: `frontend/tma/.env.development`
- Delete: `src/App.tsx`, `src/App.css`, `src/assets/*`, `public/icons.svg`

**Interfaces:**
- Consumes: ничего
- Produces: `env: { apiMode: 'mock' | 'http', apiBaseUrl: string, devPanel: boolean }`
  из `src/env.ts`; команды `npm test`, `npm run test:watch`, `npm run typecheck`

- [ ] **Шаг 1: Установить зависимости точными версиями**

```bash
cd frontend/tma
npm i -E @tailwindcss/vite@4.3.3 react-router@7.9.1 @tanstack/react-query@5.62.7 qrcode@1.5.4
npm i -DE vitest@4.0.5 jsdom@25.0.1 @vitest/coverage-v8@4.0.5 \
  @testing-library/react@16.1.0 @testing-library/user-event@14.5.2 \
  @testing-library/jest-dom@6.6.3 @types/qrcode@1.5.5
npm uninstall autoprefixer postcss
```

`autoprefixer` и `postcss` не нужны: Tailwind 4 через `@tailwindcss/vite`
использует Lightning CSS и делает префиксы сам.

- [ ] **Шаг 2: Убрать диапазоны версий у остальных зависимостей**

Открыть `package.json` и снять `^` со всех номеров, зафиксировав то, что
реально стоит в `node_modules`:

```json
{
  "dependencies": {
    "@tailwindcss/vite": "4.3.3",
    "@tanstack/react-query": "5.62.7",
    "@telegram-apps/sdk": "3.11.8",
    "@telegram-apps/sdk-react": "3.3.9",
    "qrcode": "1.5.4",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-router": "7.9.1"
  }
}
```

То же самое для `devDependencies`. Проверить, что ничего не сломалось:

```bash
rm -rf node_modules package-lock.json && npm install
```

- [ ] **Шаг 3: Добавить npm-скрипты**

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "oxlint",
    "typecheck": "tsc -b --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:cov": "vitest run --coverage"
  }
}
```

- [ ] **Шаг 4: Удалить демо-файлы шаблона**

```bash
cd frontend/tma
rm -f src/App.tsx src/App.css public/icons.svg
rm -rf src/assets
```

`src/main.tsx` временно перестанет компилироваться — это ожидаемо, он
переписывается в Задаче 2. Чтобы репозиторий оставался собираемым между
задачами, положить заглушку:

```tsx
// src/main.tsx
import { createRoot } from 'react-dom/client'
import './index.css'

createRoot(document.getElementById('root')!).render(<div />)
```

- [ ] **Шаг 5: Подключить Tailwind 4 и настроить dev-сервер**

`vite.config.ts` целиком:

```ts
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // слушать 0.0.0.0 — нужно для cloudflared-туннеля
    allowedHosts: true, // иначе Vite отклонит хост туннеля
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: { provider: 'v8', reporter: ['text', 'html'] },
  },
})
```

`server.proxy` бьёт в бэкенд только в режиме `VITE_API_MODE=http`; в режиме
`mock` до сети дело не доходит вовсе.

- [ ] **Шаг 6: Заменить `index.css` на Tailwind и мост темы Telegram**

Telegram отдаёт цвета клиента как CSS-переменные `--tg-theme-*` (их ставит
`themeParams.bindCssVars()` в Задаче 2). Блок `@theme` превращает их в
токены Tailwind, поэтому классы вроде `bg-tg-bg` работают и в Telegram, и в
браузере — во втором случае срабатывают фоллбэки.

```css
@import 'tailwindcss';

@theme {
  --color-tg-bg: var(--tg-theme-bg-color, #ffffff);
  --color-tg-text: var(--tg-theme-text-color, #000000);
  --color-tg-hint: var(--tg-theme-hint-color, #707579);
  --color-tg-link: var(--tg-theme-link-color, #2481cc);
  --color-tg-button: var(--tg-theme-button-color, #2481cc);
  --color-tg-button-text: var(--tg-theme-button-text-color, #ffffff);
  --color-tg-secondary-bg: var(--tg-theme-secondary-bg-color, #f0f0f0);
  --color-tg-section-bg: var(--tg-theme-section-bg-color, #ffffff);
  --color-tg-separator: var(--tg-theme-section-separator-color, #e5e5e5);
  --color-tg-destructive: var(--tg-theme-destructive-text-color, #df3f40);
  --color-tg-accent: var(--tg-theme-accent-text-color, #2481cc);
}

:root {
  color-scheme: light dark;
  --safe-top: var(--tg-safe-area-inset-top, 0px);
  --safe-bottom: var(--tg-safe-area-inset-bottom, 0px);
}

html,
body,
#root {
  height: 100%;
}

body {
  margin: 0;
  background: var(--color-tg-secondary-bg);
  color: var(--color-tg-text);
  font:
    16px / 1.4 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    Roboto,
    sans-serif;
  overscroll-behavior-y: none;
  -webkit-font-smoothing: antialiased;
}

/* Telegram открывает Mini App в iframe — горизонтальный скролл выглядит сломанным */
body {
  overflow-x: hidden;
}
```

- [ ] **Шаг 7: Поправить `index.html`**

```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover"
    />
    <title>VPN</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`maximum-scale=1.0, user-scalable=no` убирает зум по двойному тапу, из-за
которого TMA ощущается как сайт, а не как приложение. `viewport-fit=cover`
включает `safe-area-inset-*`.

- [ ] **Шаг 8: Объявить типы окружения**

Создать `src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: string
  readonly VITE_API_BASE_URL?: string
  readonly VITE_DEV_PANEL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
```

Добавить в `tsconfig.app.json` в `types` пакет `vitest/globals`:

```json
{
  "compilerOptions": {
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  }
}
```

- [ ] **Шаг 9: Написать падающий тест на `env.ts`**

`src/env.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { readEnv } from './env'

describe('readEnv', () => {
  it('по умолчанию работает на моках', () => {
    expect(readEnv({}).apiMode).toBe('mock')
  })

  it('читает http-режим', () => {
    expect(readEnv({ VITE_API_MODE: 'http' }).apiMode).toBe('http')
  })

  it('падает на неизвестном режиме, а не молча берёт дефолт', () => {
    expect(() => readEnv({ VITE_API_MODE: 'grpc' })).toThrow(/VITE_API_MODE/)
  })

  it('база API по умолчанию — /api', () => {
    expect(readEnv({}).apiBaseUrl).toBe('/api')
  })

  it('срезает хвостовой слэш у базы API', () => {
    expect(readEnv({ VITE_API_BASE_URL: 'https://x.dev/api/' }).apiBaseUrl).toBe(
      'https://x.dev/api',
    )
  })

  it('dev-панель выключена, если флаг не выставлен', () => {
    expect(readEnv({}).devPanel).toBe(false)
  })
})
```

- [ ] **Шаг 10: Убедиться, что тест падает**

Создать `src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
```

Запустить: `npm test -- src/env.test.ts`
Ожидается: FAIL, `Failed to resolve import "./env"`.

- [ ] **Шаг 11: Реализовать `env.ts`**

```ts
export type ApiMode = 'mock' | 'http'

export interface AppEnv {
  apiMode: ApiMode
  apiBaseUrl: string
  devPanel: boolean
}

type RawEnv = Record<string, string | undefined>

/**
 * Чистая функция ради тестируемости: `import.meta.env` подставляется Vite
 * на этапе сборки и в тестах не переопределяется.
 */
export function readEnv(raw: RawEnv): AppEnv {
  const mode = raw.VITE_API_MODE ?? 'mock'
  if (mode !== 'mock' && mode !== 'http') {
    throw new Error(
      `VITE_API_MODE должен быть "mock" или "http", получено: ${mode}`,
    )
  }

  return {
    apiMode: mode,
    apiBaseUrl: (raw.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, ''),
    devPanel: raw.VITE_DEV_PANEL === 'true',
  }
}

export const env: AppEnv = readEnv(import.meta.env as RawEnv)
```

- [ ] **Шаг 12: Убедиться, что тесты проходят**

Run: `npm test`
Expected: 6 passed.

- [ ] **Шаг 13: Завести файлы окружения**

`.env.example` (коммитится):

```bash
# mock — приложение работает без бэкенда, на данных из src/api/mock
# http — реальные запросы к api-public
VITE_API_MODE=mock
VITE_API_BASE_URL=/api
# Панель переключения сценариев мока. Работает только в dev-сборке.
VITE_DEV_PANEL=true
```

`.env.development` (тоже коммитится — это дефолт разработчика):

```bash
VITE_API_MODE=mock
VITE_DEV_PANEL=true
```

Добавить в `.gitignore`: `.env`, `.env.local`, `.env.production.local`.

- [ ] **Шаг 14: Проверить сборку и линт**

```bash
npm run typecheck && npm run lint && npm run build
```

Expected: три команды подряд без ошибок.

- [ ] **Шаг 15: Коммит**

```bash
git add frontend/tma
git commit -m "chore(tma): tailwind 4, vitest, pinned deps, env config"
```

---

### Задача 2: Окружение Telegram — мок, инициализация SDK, доступ к initData

Приложение должно запускаться в трёх местах: в обычном браузере на
`localhost:5173` (99 % времени разработки), в клиенте Telegram через туннель и
в production. Первый случай требует мока окружения, остальные два — настоящего
SDK. Один слой закрывает все три.

**Files:**
- Create: `frontend/tma/src/telegram/mockEnv.ts`
- Create: `frontend/tma/src/telegram/init.ts`
- Create: `frontend/tma/src/telegram/auth.ts`
- Create: `frontend/tma/src/telegram/haptics.ts`
- Create: `frontend/tma/src/telegram/auth.test.ts`
- Modify: `frontend/tma/src/main.tsx`
- Modify: `frontend/tma/src/test/setup.ts`

**Interfaces:**
- Consumes: `env` из `src/env.ts`
- Produces:
  - `initTelegram(): void` — из `telegram/init.ts`
  - `getInitDataRaw(): string | undefined`, `getTelegramUser(): TelegramUser | undefined`,
    `getTelegramLang(): 'ru' | 'en'` — из `telegram/auth.ts`
  - `haptic.impact('light'|'medium'|'heavy')`, `haptic.notification('success'|'error'|'warning')`,
    `haptic.selection()` — из `telegram/haptics.ts`
  - тип `TelegramUser = { id: number; first_name: string; last_name?: string; username?: string; language_code?: string }`

- [ ] **Шаг 1: Написать мок окружения**

`src/telegram/mockEnv.ts` — файл существует только для dev-сборки и
импортируется динамически:

```ts
import { mockTelegramEnv } from '@telegram-apps/sdk-react'

/**
 * ВНИМАНИЕ. Здесь подделывается окружение Telegram, включая подпись initData.
 * Подпись заведомо недействительная. Бэкенд обязан принимать её ТОЛЬКО при
 * включённом TMA_ALLOW_DEV_INITDATA=true, который в production выключен.
 * Это единственное место во всей системе, где проверка подписи ослабляется.
 */
const user = {
  id: 99281932,
  first_name: 'Иван',
  last_name: 'Петров',
  username: 'ivan',
  language_code: 'ru',
  is_premium: false,
  allows_write_to_pm: true,
}

const initDataRaw = new URLSearchParams([
  ['user', JSON.stringify(user)],
  ['auth_date', Math.floor(Date.now() / 1000).toString()],
  ['chat_instance', '-1234567890123456789'],
  ['chat_type', 'private'],
  ['signature', 'dev-mock-signature'],
  ['hash', 'dev-mock-hash'],
]).toString()

mockTelegramEnv({
  launchParams: {
    tgWebAppVersion: '8.0',
    tgWebAppPlatform: 'tdesktop',
    tgWebAppThemeParams: {
      accent_text_color: '#168acd',
      bg_color: '#ffffff',
      button_color: '#40a7e3',
      button_text_color: '#ffffff',
      destructive_text_color: '#d14e4e',
      hint_color: '#999999',
      link_color: '#168acd',
      secondary_bg_color: '#f1f1f1',
      section_bg_color: '#ffffff',
      section_separator_color: '#e7e7e7',
      subtitle_text_color: '#999999',
      text_color: '#000000',
    },
    tgWebAppData: initDataRaw,
  },
})

console.warn(
  '[tma] окружение Telegram замокано — только для разработки, в production этот модуль не собирается',
)
```

- [ ] **Шаг 2: Написать инициализацию SDK**

`src/telegram/init.ts`:

```ts
import {
  backButton,
  init,
  miniApp,
  themeParams,
  viewport,
} from '@telegram-apps/sdk-react'

let initialized = false

/**
 * Вызывается ровно один раз, до первого рендера.
 * Каждый mount обёрнут в проверку доступности: часть компонентов появилась
 * в поздних версиях Bot API, и на старом клиенте mount бросает исключение.
 */
export function initTelegram(): void {
  if (initialized) return
  initialized = true

  init()

  if (backButton.mount.isAvailable()) backButton.mount()
  if (themeParams.mountSync.isAvailable()) {
    themeParams.mountSync()
    themeParams.bindCssVars()
  }
  if (miniApp.mountSync.isAvailable()) {
    miniApp.mountSync()
    miniApp.bindCssVars()
  }
  if (viewport.mount.isAvailable()) {
    void viewport.mount().then(() => {
      if (viewport.bindCssVars.isAvailable()) viewport.bindCssVars()
      if (viewport.expand.isAvailable()) viewport.expand()
    })
  }
}
```

`bindCssVars` — то, из-за отсутствия чего тема «не совпадает с клиентом»
(см. таблицу граблей в руководстве). `viewport.expand()` разворачивает Mini App
на всю высоту, иначе приложение открывается половиной экрана.

- [ ] **Шаг 3: Написать падающий тест на слой доступа к личности**

`src/telegram/auth.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  initDataRaw: vi.fn<() => string | undefined>(),
  initDataState: vi.fn<() => { user?: unknown } | undefined>(),
}))

vi.mock('@telegram-apps/sdk-react', () => ({
  initDataRaw: mocks.initDataRaw,
  initDataState: mocks.initDataState,
}))

const { getInitDataRaw, getTelegramUser, getTelegramLang } = await import('./auth')

describe('telegram/auth', () => {
  beforeEach(() => {
    mocks.initDataRaw.mockReset()
    mocks.initDataState.mockReset()
  })

  it('отдаёт сырую строку initData', () => {
    mocks.initDataRaw.mockReturnValue('user=%7B%7D&hash=abc')
    expect(getInitDataRaw()).toBe('user=%7B%7D&hash=abc')
  })

  it('не падает вне Telegram, а возвращает undefined', () => {
    mocks.initDataRaw.mockImplementation(() => {
      throw new Error('LaunchParamsRetrieveError')
    })
    expect(getInitDataRaw()).toBeUndefined()
  })

  it('отдаёт пользователя', () => {
    mocks.initDataState.mockReturnValue({
      user: { id: 1, firstName: 'Иван', languageCode: 'ru' },
    })
    expect(getTelegramUser()?.id).toBe(1)
  })

  it('русский язык клиента распознаётся', () => {
    mocks.initDataState.mockReturnValue({ user: { id: 1, languageCode: 'ru' } })
    expect(getTelegramLang()).toBe('ru')
  })

  it('неподдерживаемый язык клиента даёт en', () => {
    mocks.initDataState.mockReturnValue({ user: { id: 1, languageCode: 'de' } })
    expect(getTelegramLang()).toBe('en')
  })

  it('отсутствие языка даёт ru — дефолт инсталляции', () => {
    mocks.initDataState.mockReturnValue({ user: { id: 1 } })
    expect(getTelegramLang()).toBe('ru')
  })
})
```

- [ ] **Шаг 4: Убедиться, что тест падает**

Run: `npm test -- src/telegram/auth.test.ts`
Expected: FAIL, `Failed to resolve import "./auth"`.

- [ ] **Шаг 5: Реализовать `auth.ts`**

```ts
import { initDataRaw, initDataState } from '@telegram-apps/sdk-react'

export type Lang = 'ru' | 'en'

export interface TelegramUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  language_code?: string
}

/** Вне Telegram и до init() сигналы SDK бросают — наружу это не выпускаем. */
function safe<T>(fn: () => T): T | undefined {
  try {
    return fn()
  } catch {
    return undefined
  }
}

export function getInitDataRaw(): string | undefined {
  return safe(() => initDataRaw())
}

export function getTelegramUser(): TelegramUser | undefined {
  const state = safe(() => initDataState()) as
    | {
        user?: {
          id: number
          firstName?: string
          lastName?: string
          username?: string
          languageCode?: string
        }
      }
    | undefined

  const u = state?.user
  if (!u) return undefined

  return {
    id: u.id,
    first_name: u.firstName ?? '',
    last_name: u.lastName,
    username: u.username,
    language_code: u.languageCode,
  }
}

export function getTelegramLang(): Lang {
  const code = getTelegramUser()?.language_code
  if (!code) return 'ru'
  return code.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}
```

- [ ] **Шаг 6: Написать безопасные хаптики**

`src/telegram/haptics.ts` — в браузере на localhost вибрации нет, и вызов
обязан быть no-op, а не исключением:

```ts
import { hapticFeedback } from '@telegram-apps/sdk-react'

type ImpactStyle = 'light' | 'medium' | 'heavy'
type NotificationType = 'success' | 'error' | 'warning'

export const haptic = {
  impact(style: ImpactStyle = 'light'): void {
    if (hapticFeedback.impactOccurred.isAvailable()) {
      hapticFeedback.impactOccurred(style)
    }
  },
  notification(type: NotificationType): void {
    if (hapticFeedback.notificationOccurred.isAvailable()) {
      hapticFeedback.notificationOccurred(type)
    }
  },
  selection(): void {
    if (hapticFeedback.selectionChanged.isAvailable()) {
      hapticFeedback.selectionChanged()
    }
  },
}
```

- [ ] **Шаг 7: Переписать `main.tsx` с асинхронным bootstrap**

Порядок принципиален: мок обязан отработать **до** `init()`, иначе SDK не
найдёт окружения. Динамический `import()` под `import.meta.env.DEV` даёт и
правильный порядок, и исключение мока из production-бандла.

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { initTelegram } from './telegram/init'
import './index.css'

async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV) {
    await import('./telegram/mockEnv')
  }

  initTelegram()

  const { App } = await import('./app/App')

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void bootstrap()
```

`app/App.tsx` появится в Задаче 12. До того — временная заглушка, чтобы
сборка была зелёной:

```tsx
// src/app/App.tsx — временно, заменяется в Задаче 12
export function App() {
  return <div className="p-4 text-tg-text">ocmanager</div>
}
```

- [ ] **Шаг 8: Прогнать тесты, типы и сборку**

```bash
npm test && npm run typecheck && npm run build
```

Expected: 12 passed; типы чистые; сборка успешна.

- [ ] **Шаг 9: Проверить руками в браузере**

```bash
npm run dev
```

Открыть `http://localhost:5173`. В консоли — предупреждение
`[tma] окружение Telegram замокано`. В DevTools → Elements на `<html>` должны
появиться переменные `--tg-theme-bg-color` и остальные: это доказательство,
что `bindCssVars()` отработал.

- [ ] **Шаг 10: Коммит**

```bash
git add frontend/tma/src
git commit -m "feat(tma): telegram env mock, sdk bootstrap, initData access layer"
```

---

### Задача 3: i18n — типизированные каталоги ru/en

Требование «i18n с первого дня» реализуется без библиотеки: локалей две,
каталоги плоские, и типизация даёт то, чего не даёт `i18next` — **отсутствие
перевода ломает компиляцию, а не показывает ключ пользователю**. Русский
каталог объявляется эталоном, из него выводится тип ключей, английский обязан
быть его полным `Record`.

**Files:**
- Create: `frontend/tma/src/i18n/ru.ts`
- Create: `frontend/tma/src/i18n/en.ts`
- Create: `frontend/tma/src/i18n/plural.ts`
- Create: `frontend/tma/src/i18n/I18nProvider.tsx`
- Create: `frontend/tma/src/i18n/useT.ts`
- Create: `frontend/tma/src/i18n/i18n.test.tsx`

**Interfaces:**
- Consumes: `getTelegramLang()` из `telegram/auth.ts`
- Produces:
  - `<I18nProvider lang?>` — из `i18n/I18nProvider.tsx`
  - `useT(): { t, tPlural, lang, setLang }` — из `i18n/useT.ts`
  - `t(key: MessageKey, params?: Record<string, string | number>): string`
  - `tPlural(key: PluralKey, count: number, params?): string`
  - типы `MessageKey`, `PluralKey`, `Lang`

- [ ] **Шаг 1: Написать падающие тесты**

`src/i18n/i18n.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from './I18nProvider'
import { en } from './en'
import { ru } from './ru'
import { useT } from './useT'

function Probe({ render: r }: { render: (api: ReturnType<typeof useT>) => string }) {
  return <span data-testid="out">{r(useT())}</span>
}

function show(node: React.ReactNode, lang: 'ru' | 'en' = 'ru') {
  render(<I18nProvider lang={lang}>{node}</I18nProvider>)
  return screen.getByTestId('out').textContent
}

describe('i18n', () => {
  it('английский каталог покрывает русский целиком', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort())
  })

  it('ни одно значение не пустое', () => {
    for (const [key, value] of Object.entries({ ...ru, ...en })) {
      expect(value, `пустой перевод: ${key}`).not.toBe('')
    }
  })

  it('отдаёт строку по ключу', () => {
    expect(show(<Probe render={({ t }) => t('plans.title')} />)).toBe('Тарифы')
  })

  it('переключает язык', () => {
    expect(show(<Probe render={({ t }) => t('plans.title')} />, 'en')).toBe('Plans')
  })

  it('подставляет параметры', () => {
    expect(
      show(<Probe render={({ t }) => t('subscription.expiresOn', { date: '5 мая' })} />),
    ).toBe('Действует до 5 мая')
  })

  it('оставляет плейсхолдер, если параметр не передан', () => {
    expect(show(<Probe render={({ t }) => t('subscription.expiresOn')} />)).toBe(
      'Действует до {date}',
    )
  })

  it('русские множественные: 1 / 2 / 5 / 21', () => {
    const day = (n: number) => (
      <Probe render={({ tPlural }) => tPlural('unit.day', n)} />
    )
    expect(show(day(1))).toBe('1 день')
    expect(show(day(2))).toBe('2 дня')
    expect(show(day(5))).toBe('5 дней')
    expect(show(day(21))).toBe('21 день')
  })

  it('английские множественные: 1 / 2', () => {
    const dev = (n: number) => (
      <Probe render={({ tPlural }) => tPlural('unit.device', n)} />
    )
    expect(show(dev(1), 'en')).toBe('1 device')
    expect(show(dev(3), 'en')).toBe('3 devices')
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/i18n`
Expected: FAIL, модули не найдены.

- [ ] **Шаг 3: Написать русский каталог-эталон**

`src/i18n/ru.ts`. Ключи — `<экран>.<элемент>`, множественные вынесены отдельно.
Здесь стартовый набор; экранные задачи дописывают свои ключи в оба каталога.

```ts
export const ru = {
  // Общее
  'common.retry': 'Повторить',
  'common.cancel': 'Отмена',
  'common.close': 'Закрыть',
  'common.copy': 'Скопировать',
  'common.copied': 'Скопировано',
  'common.loading': 'Загрузка…',
  'common.done': 'Готово',
  'common.back': 'Назад',

  // Ошибки
  'error.title': 'Что-то пошло не так',
  'error.network': 'Нет связи с сервером. Проверьте интернет.',
  'error.unauthorized': 'Откройте приложение из Telegram.',
  'error.initdata_expired': 'Сессия устарела. Закройте и откройте приложение заново.',
  'error.rate_limited': 'Слишком много запросов. Подождите минуту.',
  'error.device_limit_reached': 'Достигнут лимит устройств для вашего тарифа.',
  'error.trial_already_used': 'Пробный период уже был использован.',
  'error.subscription_inactive': 'Подписка неактивна.',
  'error.node_unavailable': 'Сервер временно недоступен. Попробуйте позже.',
  'error.not_found': 'Не найдено.',
  'error.internal': 'Внутренняя ошибка сервера.',

  // Навигация
  'nav.subscription': 'Подписка',
  'nav.devices': 'Устройства',
  'nav.plans': 'Тарифы',

  // Тарифы
  'plans.title': 'Тарифы',
  'plans.subtitle': 'Выберите подходящий вариант',
  'plans.buy': 'Купить за {price}',
  'plans.current': 'Текущий тариф',
  'plans.unlimitedTraffic': 'Безлимитный трафик',
  'plans.trafficPerMonth': '{amount} в месяц',
  'plans.trialTitle': 'Попробовать бесплатно',
  'plans.trialBody': '{days} и {traffic} — без оплаты и привязки карты',
  'plans.trialStart': 'Активировать пробный период',
  'plans.trialUsed': 'Пробный период уже использован',
  'plans.empty': 'Тарифы пока не настроены',

  // Подписка
  'subscription.title': 'Подписка',
  'subscription.none': 'Подписки нет',
  'subscription.noneBody': 'Выберите тариф, чтобы начать пользоваться VPN',
  'subscription.choosePlan': 'Выбрать тариф',
  'subscription.expiresOn': 'Действует до {date}',
  'subscription.expiredOn': 'Закончилась {date}',
  'subscription.autoRenewOn': 'Продлевается автоматически',
  'subscription.autoRenewOff': 'Автопродление отключено',
  'subscription.traffic': 'Трафик',
  'subscription.trafficUsed': '{used} из {limit}',
  'subscription.trafficUnlimited': 'Без ограничений',
  'subscription.trafficResets': 'Обнулится {date}',
  'subscription.devicesUsed': 'Устройства: {used} из {limit}',
  'subscription.extend': 'Продлить',
  'subscription.renew': 'Возобновить',

  // Статусы
  'status.trial': 'Пробный период',
  'status.active': 'Активна',
  'status.expired': 'Истекла',
  'status.exhausted': 'Трафик исчерпан',
  'status.cancelled': 'Активна до конца периода',
  'status.blocked': 'Заблокирована',
  'status.pending_payment': 'Ожидает оплаты',

  // Устройства
  'devices.title': 'Устройства',
  'devices.add': 'Добавить устройство',
  'devices.empty': 'Устройств пока нет',
  'devices.emptyBody': 'Добавьте устройство, чтобы получить ключ подключения',
  'devices.online': 'Подключено',
  'devices.lastSeen': 'Был(а) {when}',
  'devices.neverConnected': 'Ни разу не подключалось',
  'devices.revoke': 'Отозвать',
  'devices.revokeTitle': 'Отозвать устройство?',
  'devices.revokeBody':
    'Ключ «{name}» перестанет работать немедленно и восстановлению не подлежит.',
  'devices.revoked': 'Устройство отозвано',
  'devices.limitReached': 'Достигнут лимит устройств тарифа',
  'devices.instructions': 'Инструкция',

  // Выпуск устройства
  'deviceCreate.title': 'Новое устройство',
  'deviceCreate.pickPlatform': 'Выберите операционную систему',
  'deviceCreate.name': 'Название',
  'deviceCreate.namePlaceholder': 'iPhone Ивана',
  'deviceCreate.submit': 'Выпустить ключ',
  'deviceCreate.issuing': 'Выпускаем ключ…',

  // Секрет — показывается один раз
  'deviceSecret.title': 'Ключ готов',
  'deviceSecret.warning':
    'Пароль и ссылка показываются один раз. Скачайте файл сейчас — восстановить его нельзя.',
  'deviceSecret.password': 'Пароль от файла',
  'deviceSecret.download': 'Скачать ключ',
  'deviceSecret.expiresIn': 'Ссылка действует ещё {time}',
  'deviceSecret.expired': 'Ссылка истекла. Выпустите новое устройство.',
  'deviceSecret.qrHint': 'Отсканируйте, чтобы открыть на телефоне',
  'deviceSecret.next': 'Перейти к инструкции',

  // Инструкции
  'instructions.title': 'Как подключиться',
  'instructions.step': 'Шаг {n}',
  'instructions.server': 'Адрес сервера',
  'instructions.openStore': 'Открыть в магазине приложений',

  // Покупка
  'checkout.opening': 'Открываем оплату…',
  'checkout.hint':
    'После оплаты вернитесь в Telegram — бот пришлёт сообщение, когда подписка активируется.',
  'checkout.failed': 'Не удалось открыть оплату. Попробуйте ещё раз.',
} as const

export const ruPlural = {
  'unit.day': { one: '{n} день', few: '{n} дня', many: '{n} дней', other: '{n} дня' },
  'unit.device': {
    one: '{n} устройство',
    few: '{n} устройства',
    many: '{n} устройств',
    other: '{n} устройства',
  },
  'unit.dayLeft': {
    one: 'остался {n} день',
    few: 'осталось {n} дня',
    many: 'осталось {n} дней',
    other: 'осталось {n} дня',
  },
} as const

export type MessageKey = keyof typeof ru
export type PluralKey = keyof typeof ruPlural
```

- [ ] **Шаг 4: Написать английский каталог**

`src/i18n/en.ts` — аннотация типом `Record<MessageKey, string>` и есть
механизм проверки: пропущенный ключ не компилируется.

```ts
import type { MessageKey, PluralKey } from './ru'

export const en: Record<MessageKey, string> = {
  'common.retry': 'Retry',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.copy': 'Copy',
  'common.copied': 'Copied',
  'common.loading': 'Loading…',
  'common.done': 'Done',
  'common.back': 'Back',

  'error.title': 'Something went wrong',
  'error.network': 'No connection to the server. Check your internet.',
  'error.unauthorized': 'Open the app from Telegram.',
  'error.initdata_expired': 'Session expired. Close and reopen the app.',
  'error.rate_limited': 'Too many requests. Wait a minute.',
  'error.device_limit_reached': 'Device limit reached for your plan.',
  'error.trial_already_used': 'The trial period has already been used.',
  'error.subscription_inactive': 'Subscription is not active.',
  'error.node_unavailable': 'The server is temporarily unavailable. Try later.',
  'error.not_found': 'Not found.',
  'error.internal': 'Internal server error.',

  'nav.subscription': 'Subscription',
  'nav.devices': 'Devices',
  'nav.plans': 'Plans',

  'plans.title': 'Plans',
  'plans.subtitle': 'Pick the one that fits',
  'plans.buy': 'Buy for {price}',
  'plans.current': 'Current plan',
  'plans.unlimitedTraffic': 'Unlimited traffic',
  'plans.trafficPerMonth': '{amount} per month',
  'plans.trialTitle': 'Try for free',
  'plans.trialBody': '{days} and {traffic} — no payment, no card',
  'plans.trialStart': 'Start free trial',
  'plans.trialUsed': 'Trial already used',
  'plans.empty': 'No plans configured yet',

  'subscription.title': 'Subscription',
  'subscription.none': 'No subscription',
  'subscription.noneBody': 'Pick a plan to start using the VPN',
  'subscription.choosePlan': 'Choose a plan',
  'subscription.expiresOn': 'Valid until {date}',
  'subscription.expiredOn': 'Ended on {date}',
  'subscription.autoRenewOn': 'Renews automatically',
  'subscription.autoRenewOff': 'Auto-renewal is off',
  'subscription.traffic': 'Traffic',
  'subscription.trafficUsed': '{used} of {limit}',
  'subscription.trafficUnlimited': 'Unlimited',
  'subscription.trafficResets': 'Resets on {date}',
  'subscription.devicesUsed': 'Devices: {used} of {limit}',
  'subscription.extend': 'Extend',
  'subscription.renew': 'Resume',

  'status.trial': 'Trial',
  'status.active': 'Active',
  'status.expired': 'Expired',
  'status.exhausted': 'Traffic used up',
  'status.cancelled': 'Active until period ends',
  'status.blocked': 'Blocked',
  'status.pending_payment': 'Awaiting payment',

  'devices.title': 'Devices',
  'devices.add': 'Add device',
  'devices.empty': 'No devices yet',
  'devices.emptyBody': 'Add a device to get a connection key',
  'devices.online': 'Connected',
  'devices.lastSeen': 'Last seen {when}',
  'devices.neverConnected': 'Never connected',
  'devices.revoke': 'Revoke',
  'devices.revokeTitle': 'Revoke this device?',
  'devices.revokeBody':
    'The key "{name}" will stop working immediately and cannot be restored.',
  'devices.revoked': 'Device revoked',
  'devices.limitReached': 'Plan device limit reached',
  'devices.instructions': 'Setup guide',

  'deviceCreate.title': 'New device',
  'deviceCreate.pickPlatform': 'Choose the operating system',
  'deviceCreate.name': 'Name',
  'deviceCreate.namePlaceholder': "Ivan's iPhone",
  'deviceCreate.submit': 'Issue key',
  'deviceCreate.issuing': 'Issuing the key…',

  'deviceSecret.title': 'Your key is ready',
  'deviceSecret.warning':
    'The password and the link are shown once. Download the file now — it cannot be restored.',
  'deviceSecret.password': 'File password',
  'deviceSecret.download': 'Download key',
  'deviceSecret.expiresIn': 'The link is valid for {time} more',
  'deviceSecret.expired': 'The link has expired. Issue a new device.',
  'deviceSecret.qrHint': 'Scan to open on your phone',
  'deviceSecret.next': 'Go to the setup guide',

  'instructions.title': 'How to connect',
  'instructions.step': 'Step {n}',
  'instructions.server': 'Server address',
  'instructions.openStore': 'Open in the app store',

  'checkout.opening': 'Opening payment…',
  'checkout.hint':
    'After paying, come back to Telegram — the bot will message you once the subscription is active.',
  'checkout.failed': 'Could not open the payment page. Try again.',
}

export const enPlural: Record<
  PluralKey,
  { one: string; few: string; many: string; other: string }
> = {
  'unit.day': { one: '{n} day', few: '{n} days', many: '{n} days', other: '{n} days' },
  'unit.device': {
    one: '{n} device',
    few: '{n} devices',
    many: '{n} devices',
    other: '{n} devices',
  },
  'unit.dayLeft': {
    one: '{n} day left',
    few: '{n} days left',
    many: '{n} days left',
    other: '{n} days left',
  },
}
```

- [ ] **Шаг 5: Реализовать выбор формы множественного числа**

`src/i18n/plural.ts`. Правила русского языка (1 день / 2 дня / 5 дней /
21 день) руками не пишутся — их знает `Intl.PluralRules`:

```ts
import type { Lang } from '../telegram/auth'

export type PluralForm = 'one' | 'few' | 'many' | 'other'

const rules: Record<Lang, Intl.PluralRules> = {
  ru: new Intl.PluralRules('ru-RU'),
  en: new Intl.PluralRules('en-US'),
}

export function pluralForm(lang: Lang, count: number): PluralForm {
  const form = rules[lang].select(count)
  return form === 'zero' || form === 'two' ? 'other' : (form as PluralForm)
}
```

- [ ] **Шаг 6: Реализовать провайдер и хук**

`src/i18n/I18nProvider.tsx`:

```tsx
import { createContext, useMemo, useState, type ReactNode } from 'react'
import { getTelegramLang, type Lang } from '../telegram/auth'
import { en, enPlural } from './en'
import { ru, ruPlural } from './ru'
import type { MessageKey, PluralKey } from './ru'
import { pluralForm } from './plural'

export interface I18nApi {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: MessageKey, params?: Record<string, string | number>) => string
  tPlural: (
    key: PluralKey,
    count: number,
    params?: Record<string, string | number>,
  ) => string
}

export const I18nContext = createContext<I18nApi | null>(null)

const catalogs = { ru, en } as const
const plurals = { ru: ruPlural, en: enPlural } as const

/** Заменяет `{name}` на значение; неизвестные плейсхолдеры остаются как есть. */
function interpolate(
  template: string,
  params?: Record<string, string | number>,
): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in params ? String(params[key]) : match,
  )
}

export function I18nProvider({
  lang: forced,
  children,
}: {
  lang?: Lang
  children: ReactNode
}) {
  const [lang, setLang] = useState<Lang>(forced ?? getTelegramLang())

  const api = useMemo<I18nApi>(
    () => ({
      lang,
      setLang,
      t: (key, params) => interpolate(catalogs[lang][key], params),
      tPlural: (key, count, params) => {
        const forms = plurals[lang][key]
        const template = forms[pluralForm(lang, count)]
        return interpolate(template, { n: count, ...params })
      },
    }),
    [lang],
  )

  return <I18nContext.Provider value={api}>{children}</I18nContext.Provider>
}
```

`src/i18n/useT.ts`:

```ts
import { useContext } from 'react'
import { I18nContext, type I18nApi } from './I18nProvider'

export function useT(): I18nApi {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useT вызван вне <I18nProvider>')
  return ctx
}
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/i18n`
Expected: 8 passed.

- [ ] **Шаг 8: Проверить, что типизация ловит пропущенный перевод**

Временно удалить любую строку из `en.ts` и выполнить `npm run typecheck`.
Expected: ошибка `Property '...' is missing in type`. Вернуть строку.
Это ручная проверка механизма — она не оставляет за собой изменений.

- [ ] **Шаг 9: Коммит**

```bash
git add frontend/tma/src/i18n
git commit -m "feat(tma): typed ru/en catalogs with Intl plural rules"
```

---

# Фаза 1. Шов данных

Здесь строится единственное место, которое меняется при переходе с моков на
реальный бэкенд. Всё остальное приложение об этом переходе не узнает.

### Задача 4: Контракт — типы, ошибки, интерфейс `ApiClient`

Три файла без единой строки логики. Они фиксируют, что именно TMA просит у
бэкенда, и становятся тем, против чего пишутся обе реализации и все тесты.

**Files:**
- Create: `frontend/tma/src/api/types.ts`
- Create: `frontend/tma/src/api/errors.ts`
- Create: `frontend/tma/src/api/contract.ts`
- Create: `frontend/tma/src/api/errors.test.ts`

**Interfaces:**
- Consumes: `MessageKey` из `i18n/ru.ts`
- Produces: типы `Me`, `Plan`, `Subscription`, `SubscriptionStatus`, `Device`,
  `Platform`, `IssuedDevice`, `Checkout`, `ConnectionInfo`, `CreateDeviceInput`;
  класс `ApiError` с полями `code`, `status`, `retryable` и методом
  `messageKey()`; интерфейс `ApiClient`

- [ ] **Шаг 1: Объявить DTO**

`src/api/types.ts`. Имена полей — `snake_case`, как их отдаёт FastAPI; ломать
это ради конвенции TypeScript означало бы держать слой перекладывания ключей
ради косметики.

```ts
/** Идентификатор клиента, каким его видит TMA. */
export interface Me {
  telegram_id: number
  first_name: string
  username: string | null
  lang: 'ru' | 'en'
  is_blocked: boolean
  trial_available: boolean
}

export interface Plan {
  code: string
  /** Уже локализовано бэкендом под язык клиента. */
  name: string
  description: string
  duration_days: number
  device_limit: number
  /** null = безлимит. */
  traffic_limit_bytes: number | null
  speed_limit_kbps: number | null
  /** Целое в минорных единицах: 49900 = 499,00 ₽. */
  price_amount: number
  /** ISO 4217: RUB, USD, XTR (Telegram Stars). */
  currency: string
  /** Скрытый системный тариф пробного периода. */
  is_trial: boolean
  sort_order: number
}

export type SubscriptionStatus =
  | 'pending_payment'
  | 'trial'
  | 'active'
  | 'expired'
  | 'exhausted'
  | 'cancelled'
  | 'blocked'

export interface Subscription {
  id: string
  plan: Plan
  status: SubscriptionStatus
  /** ISO 8601 UTC. */
  started_at: string | null
  expires_at: string | null
  traffic_used_bytes: number
  /** Дублирует plan.traffic_limit_bytes: у подписки лимит зафиксирован на момент покупки. */
  traffic_limit_bytes: number | null
  traffic_period_start: string | null
  device_limit: number
  devices_used: number
  auto_renew: boolean
}

export type Platform = 'ios' | 'android' | 'windows' | 'macos' | 'linux'

export interface Device {
  id: string
  name: string
  platform: Platform
  issued_at: string
  cert_expires_at: string
  last_seen_at: string | null
  is_online: boolean
  /** Потрачено за текущий период подписки. */
  traffic_used_bytes: number
}

export interface CreateDeviceInput {
  name: string
  platform: Platform
}

/**
 * Ответ на выпуск устройства. Пароль и ссылка приходят один раз и
 * не должны попадать ни в кэш, ни в хранилища браузера, ни в URL.
 */
export interface IssuedDevice {
  device: Device
  p12_password: string
  download_url: string
  /** ISO 8601 UTC, обычно issued_at + 15 минут. */
  download_expires_at: string
}

export interface Checkout {
  checkout_url: string
  payment_id: string
}

export interface ConnectionInfo {
  /** Хост шлюза: vpn.example.com */
  server_host: string
  /** Полный адрес с камуфляж-токеном, его вводит клиент в AnyConnect. */
  gateway_url: string
}
```

- [ ] **Шаг 2: Написать падающий тест на `ApiError`**

`src/api/errors.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from './errors'

describe('ApiError', () => {
  it('сетевые и серверные ошибки помечены как повторяемые', () => {
    expect(new ApiError('network', 0).retryable).toBe(true)
    expect(new ApiError('internal', 500).retryable).toBe(true)
    expect(new ApiError('node_unavailable', 503).retryable).toBe(true)
  })

  it('ошибки бизнес-правил не повторяются', () => {
    expect(new ApiError('device_limit_reached', 409).retryable).toBe(false)
    expect(new ApiError('trial_already_used', 409).retryable).toBe(false)
    expect(new ApiError('unauthorized', 401).retryable).toBe(false)
  })

  it('каждый код отображается в ключ перевода', () => {
    expect(new ApiError('rate_limited', 429).messageKey()).toBe('error.rate_limited')
  })

  it('toApiError пропускает ApiError без изменений', () => {
    const original = new ApiError('not_found', 404)
    expect(toApiError(original)).toBe(original)
  })

  it('toApiError превращает любую другую ошибку во внутреннюю', () => {
    const converted = toApiError(new TypeError('boom'))
    expect(converted.code).toBe('internal')
    expect(converted.message).toBe('boom')
  })
})
```

- [ ] **Шаг 3: Убедиться, что тест падает**

Run: `npm test -- src/api/errors.test.ts`
Expected: FAIL, `Failed to resolve import "./errors"`.

- [ ] **Шаг 4: Реализовать `errors.ts`**

```ts
import type { MessageKey } from '../i18n/ru'

export type ApiErrorCode =
  | 'network'
  | 'unauthorized'
  | 'initdata_expired'
  | 'rate_limited'
  | 'device_limit_reached'
  | 'trial_already_used'
  | 'subscription_inactive'
  | 'node_unavailable'
  | 'not_found'
  | 'internal'

const RETRYABLE: ReadonlySet<ApiErrorCode> = new Set([
  'network',
  'internal',
  'node_unavailable',
])

export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly status: number

  constructor(code: ApiErrorCode, status: number, message?: string) {
    super(message ?? code)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }

  /** Повторять запрос имеет смысл только при сбое транспорта или сервера. */
  get retryable(): boolean {
    return RETRYABLE.has(this.code)
  }

  /** Ключ каталога i18n. Список кодов и список ключей error.* держатся синхронно. */
  messageKey(): MessageKey {
    return `error.${this.code}` as MessageKey
  }
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  return new ApiError('internal', 0, err instanceof Error ? err.message : String(err))
}
```

- [ ] **Шаг 5: Объявить интерфейс `ApiClient`**

`src/api/contract.ts` — девять операций и больше ничего. Каждый метод
отображается ровно в один HTTP-эндпоинт; специфика мока (сценарии, задержки)
сюда не протекает, иначе шов перестанет быть швом.

```ts
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from './types'

/**
 * Всё, что TMA просит у бэкенда. Две реализации: mock/client.ts и http.ts.
 * Любой метод при неуспехе бросает ApiError — других способов сообщить об
 * ошибке у реализаций нет.
 */
export interface ApiClient {
  /** GET /tma/me */
  getMe(): Promise<Me>
  /** GET /tma/plans — только активные, отсортированы по sort_order */
  listPlans(): Promise<Plan[]>
  /** GET /tma/subscription — null, если подписки никогда не было */
  getSubscription(): Promise<Subscription | null>
  /** POST /tma/subscription/trial */
  startTrial(): Promise<Subscription>
  /** POST /tma/checkout */
  createCheckout(planCode: string): Promise<Checkout>
  /** GET /tma/devices — только неотозванные */
  listDevices(): Promise<Device[]>
  /** POST /tma/devices — пароль и ссылка приходят один раз */
  createDevice(input: CreateDeviceInput): Promise<IssuedDevice>
  /** DELETE /tma/devices/{id} */
  revokeDevice(deviceId: string): Promise<void>
  /** GET /tma/connection */
  getConnection(): Promise<ConnectionInfo>
}
```

- [ ] **Шаг 6: Убедиться, что тесты и типы проходят**

Run: `npm test -- src/api && npm run typecheck`
Expected: 5 passed, типы чистые.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma/src/api
git commit -m "feat(tma): api contract, dto types and typed error taxonomy"
```

---

### Задача 5: Мок — фикстуры, сценарии, состояние в памяти

Состояние мока — не константа, а мутабельный стор: выпуск устройства должен
менять список устройств, отзыв — убирать из него, активация trial — создавать
подписку. Иначе на моках нельзя пройти ни один сквозной сценарий, а именно
ради этого всё и затевается.

Сценарий — именованная стартовая точка. Их одиннадцать, и каждый соответствует
состоянию, которое иначе воспроизводится только неделей ожидания или ручной
правкой БД.

**Files:**
- Create: `frontend/tma/src/api/mock/fixtures.ts`
- Create: `frontend/tma/src/api/mock/scenarios.ts`
- Create: `frontend/tma/src/api/mock/store.ts`
- Create: `frontend/tma/src/api/mock/store.test.ts`

**Interfaces:**
- Consumes: типы из `api/types.ts`
- Produces:
  - `type ScenarioId`, `SCENARIOS: readonly { id: ScenarioId; label: string }[]`
  - `type FaultId = 'none' | 'network' | 'internal' | 'rate_limited' | 'node_unavailable'`
  - `getState(): MockState`, `resetStore(scenario: ScenarioId): void`,
    `setFault(fault: FaultId): void`, `setLatency(ms: number): void`,
    `subscribeStore(fn: () => void): () => void`
  - `PLANS: Plan[]`, `TRIAL_PLAN: Plan`, `CONNECTION: ConnectionInfo`

- [ ] **Шаг 1: Написать фикстуры**

`src/api/mock/fixtures.ts`:

```ts
import type { ConnectionInfo, Me, Plan } from '../types'

const GB = 1024 ** 3

export const TRIAL_PLAN: Plan = {
  code: 'trial',
  name: 'Пробный период',
  description: '3 дня и 5 ГБ, чтобы проверить скорость',
  duration_days: 3,
  device_limit: 1,
  traffic_limit_bytes: 5 * GB,
  speed_limit_kbps: null,
  price_amount: 0,
  currency: 'RUB',
  is_trial: true,
  sort_order: 0,
}

export const PLANS: Plan[] = [
  {
    code: 'month_1',
    name: 'Месяц',
    description: '3 устройства, 200 ГБ трафика',
    duration_days: 30,
    device_limit: 3,
    traffic_limit_bytes: 200 * GB,
    speed_limit_kbps: null,
    price_amount: 29900,
    currency: 'RUB',
    is_trial: false,
    sort_order: 10,
  },
  {
    code: 'month_6',
    name: 'Полгода',
    description: '5 устройств, безлимитный трафик',
    duration_days: 180,
    device_limit: 5,
    traffic_limit_bytes: null,
    speed_limit_kbps: null,
    price_amount: 149900,
    currency: 'RUB',
    is_trial: false,
    sort_order: 20,
  },
  {
    code: 'year_1',
    name: 'Год',
    description: '5 устройств, безлимитный трафик, лучшая цена',
    duration_days: 365,
    device_limit: 5,
    traffic_limit_bytes: null,
    speed_limit_kbps: null,
    price_amount: 249900,
    currency: 'RUB',
    is_trial: false,
    sort_order: 30,
  },
]

export const CONNECTION: ConnectionInfo = {
  server_host: 'vpn.example.com',
  gateway_url: 'https://vpn.example.com/f4a91c7b',
}

export const ME: Me = {
  telegram_id: 99281932,
  first_name: 'Иван',
  username: 'ivan',
  lang: 'ru',
  is_blocked: false,
  trial_available: true,
}
```

- [ ] **Шаг 2: Описать сценарии**

`src/api/mock/scenarios.ts`. Каждый сценарий — чистая функция, собирающая
подписку и устройства от «сейчас», чтобы даты никогда не протухали:

```ts
import type { Device, Plan, Subscription } from '../types'
import { PLANS, TRIAL_PLAN } from './fixtures'

export type ScenarioId =
  | 'new_user'
  | 'trial_used'
  | 'trial_active'
  | 'active'
  | 'expiring_soon'
  | 'traffic_low'
  | 'exhausted'
  | 'expired'
  | 'cancelled'
  | 'blocked'
  | 'device_limit'

export const SCENARIOS: readonly { id: ScenarioId; label: string }[] = [
  { id: 'new_user', label: 'Новый клиент, trial доступен' },
  { id: 'trial_used', label: 'Без подписки, trial израсходован' },
  { id: 'trial_active', label: 'Активный пробный период' },
  { id: 'active', label: 'Платная подписка, 2 из 3 устройств' },
  { id: 'expiring_soon', label: 'Истекает через 2 дня' },
  { id: 'traffic_low', label: 'Осталось 12 % трафика' },
  { id: 'exhausted', label: 'Трафик исчерпан' },
  { id: 'expired', label: 'Подписка истекла' },
  { id: 'cancelled', label: 'Автопродление выключено, доступ есть' },
  { id: 'blocked', label: 'Клиент заблокирован' },
  { id: 'device_limit', label: 'Лимит устройств выбран полностью' },
]

const GB = 1024 ** 3
const DAY = 86_400_000

const iso = (offsetMs: number): string => new Date(Date.now() + offsetMs).toISOString()

function device(over: Partial<Device> & Pick<Device, 'id' | 'name' | 'platform'>): Device {
  return {
    issued_at: iso(-20 * DAY),
    cert_expires_at: iso(377 * DAY),
    last_seen_at: iso(-2 * 3600_000),
    is_online: false,
    traffic_used_bytes: 12 * GB,
    ...over,
  }
}

function subscription(plan: Plan, over: Partial<Subscription>): Subscription {
  return {
    id: 'sub_1',
    plan,
    status: 'active',
    started_at: iso(-10 * DAY),
    expires_at: iso(20 * DAY),
    traffic_used_bytes: 34 * GB,
    traffic_limit_bytes: plan.traffic_limit_bytes,
    traffic_period_start: iso(-10 * DAY),
    device_limit: plan.device_limit,
    devices_used: 2,
    auto_renew: true,
    ...over,
  }
}

export interface ScenarioState {
  subscription: Subscription | null
  devices: Device[]
  trialAvailable: boolean
  isBlocked: boolean
}

const MONTH = PLANS[0]
const SIX = PLANS[1]

const iphone = device({ id: 'dev_1', name: 'iPhone Ивана', platform: 'ios', is_online: true })
const laptop = device({
  id: 'dev_2',
  name: 'MacBook',
  platform: 'macos',
  traffic_used_bytes: 22 * GB,
})
const desktop = device({
  id: 'dev_3',
  name: 'Домашний ПК',
  platform: 'windows',
  last_seen_at: null,
  traffic_used_bytes: 0,
})

export function buildScenario(id: ScenarioId): ScenarioState {
  switch (id) {
    case 'new_user':
      return { subscription: null, devices: [], trialAvailable: true, isBlocked: false }

    case 'trial_used':
      return { subscription: null, devices: [], trialAvailable: false, isBlocked: false }

    case 'trial_active':
      return {
        subscription: subscription(TRIAL_PLAN, {
          status: 'trial',
          expires_at: iso(2 * DAY),
          started_at: iso(-1 * DAY),
          traffic_used_bytes: 1.4 * GB,
          traffic_limit_bytes: TRIAL_PLAN.traffic_limit_bytes,
          device_limit: 1,
          devices_used: 1,
          auto_renew: false,
        }),
        devices: [iphone],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'active':
      return {
        subscription: subscription(MONTH, {}),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'expiring_soon':
      return {
        subscription: subscription(MONTH, { expires_at: iso(2 * DAY) }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'traffic_low':
      return {
        subscription: subscription(MONTH, { traffic_used_bytes: 176 * GB }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'exhausted':
      return {
        subscription: subscription(MONTH, {
          status: 'exhausted',
          traffic_used_bytes: 200 * GB,
        }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'expired':
      return {
        subscription: subscription(MONTH, {
          status: 'expired',
          started_at: iso(-40 * DAY),
          expires_at: iso(-3 * DAY),
        }),
        devices: [],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'cancelled':
      return {
        subscription: subscription(MONTH, { status: 'cancelled', auto_renew: false }),
        devices: [iphone, laptop],
        trialAvailable: false,
        isBlocked: false,
      }

    case 'blocked':
      return {
        subscription: subscription(MONTH, { status: 'blocked' }),
        devices: [iphone],
        trialAvailable: false,
        isBlocked: true,
      }

    case 'device_limit':
      return {
        subscription: subscription(MONTH, { devices_used: 3 }),
        devices: [iphone, laptop, desktop],
        trialAvailable: false,
        isBlocked: false,
      }
  }
}

export const DEFAULT_SCENARIO: ScenarioId = 'active'
export { SIX }
```

- [ ] **Шаг 3: Написать падающий тест на стор**

`src/api/mock/store.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getState,
  resetStore,
  setFault,
  setLatency,
  subscribeStore,
} from './store'

describe('mock/store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    resetStore('active')
  })

  it('сценарий new_user не даёт подписки и оставляет trial доступным', () => {
    resetStore('new_user')
    expect(getState().subscription).toBeNull()
    expect(getState().me.trial_available).toBe(true)
  })

  it('сценарий active даёт подписку и два устройства', () => {
    expect(getState().subscription?.status).toBe('active')
    expect(getState().devices).toHaveLength(2)
  })

  it('сценарий device_limit заполняет лимит целиком', () => {
    resetStore('device_limit')
    const s = getState()
    expect(s.devices).toHaveLength(s.subscription!.device_limit)
  })

  it('сброс не тащит мутации предыдущего сценария', () => {
    getState().devices.pop()
    expect(getState().devices).toHaveLength(1)
    resetStore('active')
    expect(getState().devices).toHaveLength(2)
  })

  it('подписчики вызываются на каждое изменение', () => {
    const spy = vi.fn()
    const unsubscribe = subscribeStore(spy)
    setFault('network')
    setLatency(0)
    expect(spy).toHaveBeenCalledTimes(2)
    unsubscribe()
    setFault('none')
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('выбранный сценарий переживает перезагрузку страницы', () => {
    resetStore('exhausted')
    expect(sessionStorage.getItem('tma.mock.scenario')).toBe('exhausted')
  })

  it('неизвестный сценарий в sessionStorage не роняет приложение', () => {
    sessionStorage.setItem('tma.mock.scenario', 'нет-такого')
    expect(() => resetStore()).not.toThrow()
    expect(getState().scenario).toBe('active')
  })
})
```

- [ ] **Шаг 4: Убедиться, что тест падает**

Run: `npm test -- src/api/mock/store.test.ts`
Expected: FAIL, `Failed to resolve import "./store"`.

- [ ] **Шаг 5: Реализовать стор**

`src/api/mock/store.ts`:

```ts
import type { ConnectionInfo, Device, Me, Plan, Subscription } from '../types'
import { CONNECTION, ME, PLANS, TRIAL_PLAN } from './fixtures'
import {
  buildScenario,
  DEFAULT_SCENARIO,
  SCENARIOS,
  type ScenarioId,
} from './scenarios'

export type FaultId =
  | 'none'
  | 'network'
  | 'internal'
  | 'rate_limited'
  | 'node_unavailable'

export interface MockState {
  scenario: ScenarioId
  me: Me
  plans: Plan[]
  trialPlan: Plan
  subscription: Subscription | null
  devices: Device[]
  connection: ConnectionInfo
  /** Счётчик для генерации id и CN новых устройств. */
  deviceSeq: number
  latencyMs: number
  fault: FaultId
}

const STORAGE_KEY = 'tma.mock.scenario'

const listeners = new Set<() => void>()
let state: MockState = build(DEFAULT_SCENARIO)

function isScenarioId(value: unknown): value is ScenarioId {
  return SCENARIOS.some((s) => s.id === value)
}

function readStoredScenario(): ScenarioId {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return isScenarioId(raw) ? raw : DEFAULT_SCENARIO
  } catch {
    return DEFAULT_SCENARIO
  }
}

function build(scenario: ScenarioId): MockState {
  const s = buildScenario(scenario)
  return {
    scenario,
    me: { ...ME, trial_available: s.trialAvailable, is_blocked: s.isBlocked },
    // Глубокое копирование: сценарии переиспользуют одни и те же объекты,
    // а стор мутабельный — иначе правки протекут между сбросами.
    plans: structuredClone(PLANS),
    trialPlan: structuredClone(TRIAL_PLAN),
    subscription: structuredClone(s.subscription),
    devices: structuredClone(s.devices),
    connection: { ...CONNECTION },
    deviceSeq: s.devices.length,
    latencyMs: 350,
    fault: 'none',
  }
}

function notify(): void {
  for (const fn of listeners) fn()
}

export function getState(): MockState {
  return state
}

/** Без аргумента — восстанавливает сценарий, выбранный до перезагрузки. */
export function resetStore(scenario?: ScenarioId): void {
  const next = scenario ?? readStoredScenario()
  const latency = state.latencyMs
  const fault = state.fault
  state = { ...build(next), latencyMs: latency, fault }
  try {
    sessionStorage.setItem(STORAGE_KEY, next)
  } catch {
    // приватный режим — не критично
  }
  notify()
}

export function setFault(fault: FaultId): void {
  state.fault = fault
  notify()
}

export function setLatency(ms: number): void {
  state.latencyMs = ms
  notify()
}

export function subscribeStore(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
```

- [ ] **Шаг 6: Убедиться, что тесты проходят**

Run: `npm test -- src/api/mock`
Expected: 7 passed.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma/src/api/mock
git commit -m "feat(tma): mock fixtures, scenarios and in-memory store"
```

---

### Задача 6: Мок-клиент — реализация `ApiClient` на сторе

Мок обязан вести себя как настоящий сервер: задержки, отказ при превышении
лимита устройств, отказ повторного trial, ошибка при выпуске устройства на
неактивной подписке. Мок, который всегда отвечает успехом, не даёт написать
обработку ошибок — а именно она потом ломается в бою.

**Files:**
- Create: `frontend/tma/src/api/mock/client.ts`
- Create: `frontend/tma/src/api/mock/client.test.ts`

**Interfaces:**
- Consumes: `ApiClient` из `api/contract.ts`, стор из `api/mock/store.ts`,
  `ApiError` из `api/errors.ts`
- Produces: `createMockClient(): ApiClient`

- [ ] **Шаг 1: Написать падающие тесты**

`src/api/mock/client.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError } from '../errors'
import { createMockClient } from './client'
import { getState, resetStore, setFault, setLatency } from './store'

const api = createMockClient()

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
  setFault('none')
})

describe('mock/client — чтение', () => {
  it('отдаёт активные тарифы без скрытого trial-тарифа', async () => {
    const plans = await api.listPlans()
    expect(plans.map((p) => p.code)).toEqual(['month_1', 'month_6', 'year_1'])
  })

  it('отдаёт подписку сценария', async () => {
    expect((await api.getSubscription())?.status).toBe('active')
  })

  it('для нового клиента подписки нет', async () => {
    resetStore('new_user')
    expect(await api.getSubscription()).toBeNull()
  })
})

describe('mock/client — trial', () => {
  it('создаёт подписку на trial-тарифе и закрывает повторную попытку', async () => {
    resetStore('new_user')
    const sub = await api.startTrial()
    expect(sub.status).toBe('trial')
    expect(sub.plan.is_trial).toBe(true)
    expect((await api.getMe()).trial_available).toBe(false)

    await expect(api.startTrial()).rejects.toMatchObject({
      code: 'trial_already_used',
    })
  })

  it('trial недоступен, если он уже был израсходован', async () => {
    resetStore('trial_used')
    await expect(api.startTrial()).rejects.toBeInstanceOf(ApiError)
  })
})

describe('mock/client — устройства', () => {
  it('выпускает устройство, кладёт его в список и отдаёт пароль один раз', async () => {
    const before = (await api.listDevices()).length
    const issued = await api.createDevice({ name: 'Планшет', platform: 'android' })

    expect(issued.p12_password).toMatch(/^[A-Za-z0-9]{12}$/)
    expect(issued.download_url).toContain('/download/')
    expect(new Date(issued.download_expires_at).getTime()).toBeGreaterThan(Date.now())
    expect(await api.listDevices()).toHaveLength(before + 1)
    expect((await api.getSubscription())?.devices_used).toBe(before + 1)
  })

  it('отказывает при исчерпанном лимите устройств', async () => {
    resetStore('device_limit')
    await expect(
      api.createDevice({ name: 'Ещё один', platform: 'ios' }),
    ).rejects.toMatchObject({ code: 'device_limit_reached', status: 409 })
  })

  it('отказывает в выпуске на истёкшей подписке', async () => {
    resetStore('expired')
    await expect(
      api.createDevice({ name: 'X', platform: 'ios' }),
    ).rejects.toMatchObject({ code: 'subscription_inactive' })
  })

  it('разрешает выпуск при cancelled — доступ живёт до expires_at', async () => {
    resetStore('cancelled')
    await expect(
      api.createDevice({ name: 'X', platform: 'ios' }),
    ).resolves.toBeTruthy()
  })

  it('отзыв убирает устройство из списка', async () => {
    const [first] = await api.listDevices()
    await api.revokeDevice(first.id)
    const rest = await api.listDevices()
    expect(rest.find((d) => d.id === first.id)).toBeUndefined()
    expect((await api.getSubscription())?.devices_used).toBe(rest.length)
  })

  it('отзыв несуществующего устройства даёт not_found', async () => {
    await expect(api.revokeDevice('dev_нет')).rejects.toMatchObject({
      code: 'not_found',
      status: 404,
    })
  })
})

describe('mock/client — покупка', () => {
  it('отдаёт checkout-ссылку по коду тарифа', async () => {
    const checkout = await api.createCheckout('month_1')
    expect(checkout.checkout_url).toMatch(/^https:\/\//)
    expect(checkout.payment_id).toBeTruthy()
  })

  it('неизвестный тариф даёт not_found', async () => {
    await expect(api.createCheckout('нет-такого')).rejects.toMatchObject({
      code: 'not_found',
    })
  })
})

describe('mock/client — инъекция сбоев', () => {
  it('fault=network даёт повторяемую ошибку сети', async () => {
    setFault('network')
    const err = await api.listPlans().catch((e: ApiError) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('network')
    expect((err as ApiError).retryable).toBe(true)
  })

  it('fault=rate_limited даёт 429 и не повторяется', async () => {
    setFault('rate_limited')
    const err = await api.listDevices().catch((e: ApiError) => e)
    expect((err as ApiError).status).toBe(429)
    expect((err as ApiError).retryable).toBe(false)
  })

  it('заблокированный клиент получает отказ на изменяющих операциях', async () => {
    resetStore('blocked')
    await expect(
      api.createDevice({ name: 'X', platform: 'ios' }),
    ).rejects.toMatchObject({ code: 'subscription_inactive' })
  })

  it('латентность соблюдается', async () => {
    setLatency(60)
    const started = Date.now()
    await api.listPlans()
    expect(Date.now() - started).toBeGreaterThanOrEqual(50)
  })
})

describe('mock/client — соединение', () => {
  it('отдаёт хост шлюза и адрес с камуфляж-токеном', async () => {
    const conn = await api.getConnection()
    expect(conn.server_host).toBe('vpn.example.com')
    expect(conn.gateway_url).toContain(conn.server_host)
  })

  it('состояние стора не утекает наружу по ссылке', async () => {
    const devices = await api.listDevices()
    devices[0].name = 'подменено'
    expect(getState().devices[0].name).not.toBe('подменено')
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/api/mock/client.test.ts`
Expected: FAIL, `Failed to resolve import "./client"`.

- [ ] **Шаг 3: Реализовать мок-клиент**

`src/api/mock/client.ts`:

```ts
import type { ApiClient } from '../contract'
import { ApiError, type ApiErrorCode } from '../errors'
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from '../types'
import { getState, type FaultId } from './store'

const DAY = 86_400_000
const LINK_TTL_MS = 15 * 60_000

/** Статусы, при которых клиент имеет право пользоваться сервисом. */
const LIVE_STATUSES = new Set(['trial', 'active', 'cancelled'])

const FAULT_TO_ERROR: Record<Exclude<FaultId, 'none'>, [ApiErrorCode, number]> = {
  network: ['network', 0],
  internal: ['internal', 500],
  rate_limited: ['rate_limited', 429],
  node_unavailable: ['node_unavailable', 503],
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Каждая операция проходит через это: задержка + сконфигурированный сбой. */
async function transport(): Promise<void> {
  const { latencyMs, fault } = getState()
  if (latencyMs > 0) await sleep(latencyMs)
  if (fault !== 'none') {
    const [code, status] = FAULT_TO_ERROR[fault]
    throw new ApiError(code, status)
  }
}

/** Наружу отдаются копии: экраны не должны иметь возможности править стор. */
function copy<T>(value: T): T {
  return structuredClone(value)
}

function randomPassword(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  return Array.from(
    { length: 12 },
    () => alphabet[Math.floor(Math.random() * alphabet.length)],
  ).join('')
}

function requireLiveSubscription(): Subscription {
  const state = getState()
  if (state.me.is_blocked) {
    throw new ApiError('subscription_inactive', 403)
  }
  const sub = state.subscription
  if (!sub || !LIVE_STATUSES.has(sub.status)) {
    throw new ApiError('subscription_inactive', 409)
  }
  return sub
}

export function createMockClient(): ApiClient {
  return {
    async getMe(): Promise<Me> {
      await transport()
      return copy(getState().me)
    },

    async listPlans(): Promise<Plan[]> {
      await transport()
      // Trial-тариф скрытый: он есть в сторе, но в каталог не попадает.
      return copy(getState().plans).sort((a, b) => a.sort_order - b.sort_order)
    },

    async getSubscription(): Promise<Subscription | null> {
      await transport()
      return copy(getState().subscription)
    },

    async startTrial(): Promise<Subscription> {
      await transport()
      const state = getState()
      if (!state.me.trial_available) {
        throw new ApiError('trial_already_used', 409)
      }

      const plan = state.trialPlan
      const now = Date.now()
      const sub: Subscription = {
        id: `sub_trial_${now}`,
        plan: copy(plan),
        status: 'trial',
        started_at: new Date(now).toISOString(),
        expires_at: new Date(now + plan.duration_days * DAY).toISOString(),
        traffic_used_bytes: 0,
        traffic_limit_bytes: plan.traffic_limit_bytes,
        traffic_period_start: new Date(now).toISOString(),
        device_limit: plan.device_limit,
        devices_used: 0,
        auto_renew: false,
      }

      state.subscription = sub
      state.me.trial_available = false
      return copy(sub)
    },

    async createCheckout(planCode: string): Promise<Checkout> {
      await transport()
      const state = getState()
      const plan = state.plans.find((p) => p.code === planCode)
      if (!plan) throw new ApiError('not_found', 404, `нет тарифа ${planCode}`)

      const paymentId = `pay_${Date.now().toString(36)}`
      return {
        payment_id: paymentId,
        checkout_url: `https://web.tribute.tg/checkout/${plan.code}?payload=${paymentId}`,
      }
    },

    async listDevices(): Promise<Device[]> {
      await transport()
      return copy(getState().devices)
    },

    async createDevice(input: CreateDeviceInput): Promise<IssuedDevice> {
      await transport()
      const state = getState()
      const sub = requireLiveSubscription()

      if (state.devices.length >= sub.device_limit) {
        throw new ApiError('device_limit_reached', 409)
      }

      const name = input.name.trim()
      if (!name) throw new ApiError('internal', 422, 'пустое имя устройства')

      state.deviceSeq += 1
      const now = Date.now()
      const device: Device = {
        id: `dev_${state.deviceSeq}_${now.toString(36)}`,
        name,
        platform: input.platform,
        issued_at: new Date(now).toISOString(),
        // Срок сертификата — 397 дней, он развязан со сроком подписки.
        cert_expires_at: new Date(now + 397 * DAY).toISOString(),
        last_seen_at: null,
        is_online: false,
        traffic_used_bytes: 0,
      }

      state.devices.push(device)
      sub.devices_used = state.devices.length

      return {
        device: copy(device),
        p12_password: randomPassword(),
        download_url: `https://app.example.com/download/${crypto.randomUUID()}`,
        download_expires_at: new Date(now + LINK_TTL_MS).toISOString(),
      }
    },

    async revokeDevice(deviceId: string): Promise<void> {
      await transport()
      const state = getState()
      const index = state.devices.findIndex((d) => d.id === deviceId)
      if (index === -1) throw new ApiError('not_found', 404)

      state.devices.splice(index, 1)
      if (state.subscription) {
        state.subscription.devices_used = state.devices.length
      }
    },

    async getConnection(): Promise<ConnectionInfo> {
      await transport()
      return copy(getState().connection)
    },
  }
}
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Run: `npm test -- src/api/mock`
Expected: 21 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/tma/src/api/mock
git commit -m "feat(tma): mock ApiClient with realistic failures and latency"
```

---

### Задача 7: HTTP-клиент и общий контрактный набор тестов

HTTP-реализация пишется **сейчас**, а не в конце. Причина конкретная: пока
существует только мок, в интерфейс легко просачиваются вещи, которых по HTTP
не бывает — синхронные ответы, объекты по ссылке, ошибки без кода. Вторая
реализация не даёт этому случиться. Включена она не будет: `VITE_API_MODE`
остаётся `mock` до Задачи 20.

Одновременно появляется `contract.suite.ts` — набор тестов, который гоняется
против **обеих** реализаций. Он и есть гарантия, что переключение флага ничего
не сломает.

**Files:**
- Create: `frontend/tma/src/api/http.ts`
- Create: `frontend/tma/src/api/http.test.ts`
- Create: `frontend/tma/src/test/contract.suite.ts`
- Create: `frontend/tma/src/api/contract.test.ts`

**Interfaces:**
- Consumes: `ApiClient`, `ApiError`, DTO
- Produces:
  - `createHttpClient(deps: HttpDeps): ApiClient`, где
    `HttpDeps = { baseUrl: string; getInitDataRaw: () => string | undefined; fetchImpl?: typeof fetch }`
  - `runContractSuite(name: string, makeClient: () => Promise<ApiClient>): void`

- [ ] **Шаг 1: Написать падающие тесты HTTP-клиента**

`src/api/http.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './errors'
import { createHttpClient } from './http'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function make(fetchImpl: typeof fetch, raw: string | undefined = 'user=%7B%7D&hash=a') {
  return createHttpClient({
    baseUrl: '/api',
    getInitDataRaw: () => raw,
    fetchImpl,
  })
}

describe('http client', () => {
  it('кладёт initData в заголовок Authorization по схеме tma', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json([]))
    await make(fetchImpl).listPlans()

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/tma/plans')
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'tma user=%7B%7D&hash=a',
    )
  })

  it('без initData не ходит в сеть, а сразу даёт unauthorized', async () => {
    const fetchImpl = vi.fn()
    await expect(make(fetchImpl, undefined).listPlans()).rejects.toMatchObject({
      code: 'unauthorized',
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('разворачивает конверт подписки', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ subscription: null }))
    expect(await make(fetchImpl).getSubscription()).toBeNull()
  })

  it('маппит код ошибки из тела ответа', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        json({ error: { code: 'device_limit_reached', message: 'лимит' } }, 409),
      )
    const err = await make(fetchImpl)
      .createDevice({ name: 'X', platform: 'ios' })
      .catch((e: ApiError) => e)

    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('device_limit_reached')
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).message).toBe('лимит')
  })

  it('неизвестный код ошибки не роняет клиент, а становится internal', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json({ error: { code: 'квантовый_сбой' } }, 500))
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: 'internal',
    })
  })

  it('ответ без JSON-тела не роняет клиент', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 }))
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: 'internal',
      status: 502,
    })
  })

  it('401 с истёкшей initData отличается от обычного 401', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json({ error: { code: 'initdata_expired' } }, 401))
    await expect(make(fetchImpl).getMe()).rejects.toMatchObject({
      code: 'initdata_expired',
    })
  })

  it('обрыв соединения превращается в network', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(make(fetchImpl).listPlans()).rejects.toMatchObject({
      code: 'network',
      status: 0,
    })
  })

  it('204 на отзыве устройства не пытается парсить тело', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    await expect(make(fetchImpl).revokeDevice('dev_1')).resolves.toBeUndefined()
  })

  it('id устройства экранируется в пути', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    await make(fetchImpl).revokeDevice('dev/../admin')
    expect((fetchImpl.mock.calls[0] as [string])[0]).toBe(
      '/api/tma/devices/dev%2F..%2Fadmin',
    )
  })

  it('POST отправляет тело в JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ device: {}, p12_password: 'x' }))
    await make(fetchImpl).createDevice({ name: 'Планшет', platform: 'android' })
    const init = (fetchImpl.mock.calls[0] as [string, RequestInit])[1]
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"name":"Планшет","platform":"android"}')
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/api/http.test.ts`
Expected: FAIL, `Failed to resolve import "./http"`.

- [ ] **Шаг 3: Реализовать HTTP-клиент**

`src/api/http.ts`:

```ts
import type { ApiClient } from './contract'
import { ApiError, type ApiErrorCode } from './errors'
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from './types'

export interface HttpDeps {
  baseUrl: string
  getInitDataRaw: () => string | undefined
  /** Подменяется в тестах; в приложении — глобальный fetch. */
  fetchImpl?: typeof fetch
}

const KNOWN_CODES: ReadonlySet<string> = new Set<ApiErrorCode>([
  'network',
  'unauthorized',
  'initdata_expired',
  'rate_limited',
  'device_limit_reached',
  'trial_already_used',
  'subscription_inactive',
  'node_unavailable',
  'not_found',
  'internal',
])

interface ErrorEnvelope {
  error?: { code?: string; message?: string }
}

export function createHttpClient(deps: HttpDeps): ApiClient {
  const fetchImpl = deps.fetchImpl ?? globalThis.fetch.bind(globalThis)

  async function request<T>(
    method: 'GET' | 'POST' | 'DELETE',
    path: string,
    body?: unknown,
  ): Promise<T> {
    const raw = deps.getInitDataRaw()
    if (!raw) {
      // До сети не доходим: без initData личности нет, и 401 гарантирован.
      throw new ApiError('unauthorized', 401, 'приложение открыто вне Telegram')
    }

    const headers: Record<string, string> = {
      Accept: 'application/json',
      Authorization: `tma ${raw}`,
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json'

    let response: Response
    try {
      response = await fetchImpl(`${deps.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch (cause) {
      throw new ApiError(
        'network',
        0,
        cause instanceof Error ? cause.message : 'сеть недоступна',
      )
    }

    if (!response.ok) throw await toApiErrorFromResponse(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async function toApiErrorFromResponse(response: Response): Promise<ApiError> {
    let envelope: ErrorEnvelope = {}
    try {
      envelope = (await response.json()) as ErrorEnvelope
    } catch {
      // Прокси и балансировщики отдают HTML — это нормальный случай, не сбой клиента.
    }

    const raw = envelope.error?.code
    const code: ApiErrorCode = KNOWN_CODES.has(raw ?? '')
      ? (raw as ApiErrorCode)
      : 'internal'

    return new ApiError(code, response.status, envelope.error?.message)
  }

  return {
    getMe: () => request<Me>('GET', '/tma/me'),
    listPlans: () => request<Plan[]>('GET', '/tma/plans'),

    async getSubscription() {
      const envelope = await request<{ subscription: Subscription | null }>(
        'GET',
        '/tma/subscription',
      )
      return envelope.subscription
    },

    startTrial: () => request<Subscription>('POST', '/tma/subscription/trial', {}),

    createCheckout: (planCode: string) =>
      request<Checkout>('POST', '/tma/checkout', { plan_code: planCode }),

    listDevices: () => request<Device[]>('GET', '/tma/devices'),

    createDevice: (input: CreateDeviceInput) =>
      request<IssuedDevice>('POST', '/tma/devices', input),

    revokeDevice: (deviceId: string) =>
      request<void>('DELETE', `/tma/devices/${encodeURIComponent(deviceId)}`),

    getConnection: () => request<ConnectionInfo>('GET', '/tma/connection'),
  }
}
```

- [ ] **Шаг 4: Убедиться, что тесты HTTP-клиента проходят**

Run: `npm test -- src/api/http.test.ts`
Expected: 11 passed.

- [ ] **Шаг 5: Написать общий контрактный набор**

`src/test/contract.suite.ts` — тесты, истинные для **любой** реализации.
Это то, что в Задаче 20 будет запущено против реального бэкенда.

```ts
import { describe, expect, it } from 'vitest'
import type { ApiClient } from '../api/contract'

/**
 * Набор инвариантов контракта, не зависящих от реализации.
 * Запускается против мока сейчас и против HTTP-клиента в Задаче 20.
 */
export function runContractSuite(
  name: string,
  makeClient: () => Promise<ApiClient>,
): void {
  describe(`контракт ApiClient: ${name}`, () => {
    it('listPlans отдаёт массив, отсортированный по sort_order', async () => {
      const plans = await (await makeClient()).listPlans()
      expect(Array.isArray(plans)).toBe(true)
      const orders = plans.map((p) => p.sort_order)
      expect(orders).toEqual([...orders].sort((a, b) => a - b))
    })

    it('в каталоге нет trial-тарифа — он скрытый', async () => {
      const plans = await (await makeClient()).listPlans()
      expect(plans.some((p) => p.is_trial)).toBe(false)
    })

    it('цены — целые неотрицательные числа', async () => {
      const plans = await (await makeClient()).listPlans()
      for (const p of plans) {
        expect(Number.isInteger(p.price_amount)).toBe(true)
        expect(p.price_amount).toBeGreaterThanOrEqual(0)
      }
    })

    it('даты подписки — валидный ISO 8601', async () => {
      const sub = await (await makeClient()).getSubscription()
      if (!sub) return
      for (const value of [sub.started_at, sub.expires_at]) {
        if (value === null) continue
        expect(Number.isNaN(Date.parse(value))).toBe(false)
      }
    })

    it('devices_used подписки совпадает с длиной списка устройств', async () => {
      const api = await makeClient()
      const [sub, devices] = await Promise.all([
        api.getSubscription(),
        api.listDevices(),
      ])
      if (!sub) return
      expect(sub.devices_used).toBe(devices.length)
    })

    it('устройств не больше лимита тарифа', async () => {
      const api = await makeClient()
      const [sub, devices] = await Promise.all([
        api.getSubscription(),
        api.listDevices(),
      ])
      if (!sub) return
      expect(devices.length).toBeLessThanOrEqual(sub.device_limit)
    })

    it('gateway_url содержит server_host', async () => {
      const conn = await (await makeClient()).getConnection()
      expect(conn.gateway_url).toContain(conn.server_host)
    })
  })
}
```

- [ ] **Шаг 6: Запустить набор против мока**

`src/api/contract.test.ts`:

```ts
import { beforeEach } from 'vitest'
import { runContractSuite } from '../test/contract.suite'
import { createMockClient } from './mock/client'
import { resetStore, setLatency } from './mock/store'

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
})

runContractSuite('mock', async () => createMockClient())
```

- [ ] **Шаг 7: Убедиться, что всё проходит**

Run: `npm test`
Expected: 7 контрактных тестов зелёные, общий счёт растёт, падений нет.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/api frontend/tma/src/test
git commit -m "feat(tma): http ApiClient implementation and shared contract suite"
```

---

### Задача 8: Сборка клиента, React Query и доменные хуки

Экраны не должны знать ни про `createApiClient`, ни про ключи кэша. Между ними
и контрактом встают хуки — по одному на операцию, с настроенной инвалидацией:
после выпуска устройства перечитываются и устройства, и подписка (в ней
изменился `devices_used`).

**Files:**
- Create: `frontend/tma/src/api/index.ts`
- Create: `frontend/tma/src/api/ApiProvider.tsx`
- Create: `frontend/tma/src/api/queryKeys.ts`
- Create: `frontend/tma/src/api/hooks.ts`
- Create: `frontend/tma/src/api/hooks.test.tsx`

**Interfaces:**
- Consumes: `createMockClient`, `createHttpClient`, `env`, `getInitDataRaw`
- Produces:
  - `createApiClient(): ApiClient`
  - `<ApiProvider client?>`, `useApi(): ApiClient`
  - `createQueryClient(): QueryClient`
  - `queryKeys.me | plans | subscription | devices | connection`
  - `usePlans()`, `useSubscription()`, `useDevices()`, `useMe()`, `useConnection()`
  - `useStartTrial()`, `useCreateDevice()`, `useRevokeDevice()`, `useCreateCheckout()`

- [ ] **Шаг 1: Реализовать фабрику клиента**

`src/api/index.ts` — единственное место во всём приложении, где написано
слово `mock` в рабочем коде:

```ts
import { env } from '../env'
import { getInitDataRaw } from '../telegram/auth'
import type { ApiClient } from './contract'
import { createHttpClient } from './http'

export function createApiClient(): ApiClient {
  if (env.apiMode === 'http') {
    return createHttpClient({
      baseUrl: env.apiBaseUrl,
      getInitDataRaw,
    })
  }

  // Синхронный require невозможен, поэтому мок подключается лениво:
  // в production-бандле этой ветки не остаётся.
  throw new Error('createApiClient(): режим mock требует createApiClientAsync()')
}

export async function createApiClientAsync(): Promise<ApiClient> {
  if (env.apiMode === 'http') return createApiClient()

  const { createMockClient } = await import('./mock/client')
  const { resetStore } = await import('./mock/store')
  resetStore()
  return createMockClient()
}

export type { ApiClient } from './contract'
```

`main.tsx` уже асинхронный (Задача 2), поэтому `createApiClientAsync()`
встраивается туда без переделок — правка `main.tsx` идёт в Задаче 12 вместе с
`App.tsx`.

- [ ] **Шаг 2: Реализовать контекст и ключи кэша**

`src/api/ApiProvider.tsx`:

```tsx
import { createContext, useContext, type ReactNode } from 'react'
import type { ApiClient } from './contract'

const ApiContext = createContext<ApiClient | null>(null)

export function ApiProvider({
  client,
  children,
}: {
  client: ApiClient
  children: ReactNode
}) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext)
  if (!client) throw new Error('useApi вызван вне <ApiProvider>')
  return client
}
```

`src/api/queryKeys.ts`:

```ts
export const queryKeys = {
  me: ['me'] as const,
  plans: ['plans'] as const,
  subscription: ['subscription'] as const,
  devices: ['devices'] as const,
  connection: ['connection'] as const,
}
```

- [ ] **Шаг 3: Написать падающие тесты хуков**

`src/api/hooks.test.tsx`:

```tsx
import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { ApiProvider } from './ApiProvider'
import { createQueryClient } from './queryClient'
import { useCreateDevice, useDevices, useRevokeDevice, useSubscription } from './hooks'
import { createMockClient } from './mock/client'
import { resetStore, setFault, setLatency } from './mock/store'

function wrapper({ children }: { children: ReactNode }) {
  const qc = createQueryClient()
  qc.setDefaultOptions({ queries: { retry: false, gcTime: 0 } })
  return (
    <QueryClientProvider client={qc}>
      <ApiProvider client={createMockClient()}>{children}</ApiProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
  setFault('none')
})

describe('хуки данных', () => {
  it('useDevices загружает список', async () => {
    const { result } = renderHook(() => useDevices(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(2)
  })

  it('выпуск устройства инвалидирует и устройства, и подписку', async () => {
    const { result } = renderHook(
      () => ({
        devices: useDevices(),
        subscription: useSubscription(),
        create: useCreateDevice(),
      }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.devices.isSuccess).toBe(true))
    await result.current.create.mutateAsync({ name: 'Планшет', platform: 'android' })

    await waitFor(() => expect(result.current.devices.data).toHaveLength(3))
    await waitFor(() => expect(result.current.subscription.data?.devices_used).toBe(3))
  })

  it('отзыв устройства убирает его из кэша', async () => {
    const { result } = renderHook(
      () => ({ devices: useDevices(), revoke: useRevokeDevice() }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.devices.isSuccess).toBe(true))
    const victim = result.current.devices.data![0].id
    await result.current.revoke.mutateAsync(victim)

    await waitFor(() =>
      expect(result.current.devices.data?.some((d) => d.id === victim)).toBe(false),
    )
  })

  it('ошибка бизнес-правила не ретраится', async () => {
    resetStore('device_limit')
    const { result } = renderHook(() => useCreateDevice(), { wrapper })
    await expect(
      result.current.mutateAsync({ name: 'Лишнее', platform: 'ios' }),
    ).rejects.toMatchObject({ code: 'device_limit_reached' })
  })
})
```

- [ ] **Шаг 4: Убедиться, что тесты падают**

Run: `npm test -- src/api/hooks.test.tsx`
Expected: FAIL, модули `./queryClient` и `./hooks` не найдены.

- [ ] **Шаг 5: Настроить QueryClient**

`src/api/queryClient.ts`:

```ts
import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './errors'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Мобильная сеть: два повтора, но только там, где повтор осмыслен.
        retry: (failureCount, error) =>
          error instanceof ApiError && error.retryable && failureCount < 2,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
        staleTime: 30_000,
        // Возврат в Mini App после оплаты — самый частый способ обновить данные.
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: {
        // Мутации не повторяем никогда: выпуск устройства не идемпотентен.
        retry: false,
      },
    },
  })
}
```

- [ ] **Шаг 6: Реализовать хуки**

`src/api/hooks.ts`:

```ts
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'
import { useApi } from './ApiProvider'
import type { ApiError } from './errors'
import { queryKeys } from './queryKeys'
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from './types'

export function useMe(): UseQueryResult<Me, ApiError> {
  const api = useApi()
  return useQuery({ queryKey: queryKeys.me, queryFn: () => api.getMe() })
}

export function usePlans(): UseQueryResult<Plan[], ApiError> {
  const api = useApi()
  return useQuery({
    queryKey: queryKeys.plans,
    queryFn: () => api.listPlans(),
    // Каталог тарифов меняется редко — незачем дёргать его при каждом фокусе.
    staleTime: 5 * 60_000,
  })
}

export function useSubscription(): UseQueryResult<Subscription | null, ApiError> {
  const api = useApi()
  return useQuery({
    queryKey: queryKeys.subscription,
    queryFn: () => api.getSubscription(),
  })
}

export function useDevices(): UseQueryResult<Device[], ApiError> {
  const api = useApi()
  return useQuery({ queryKey: queryKeys.devices, queryFn: () => api.listDevices() })
}

export function useConnection(): UseQueryResult<ConnectionInfo, ApiError> {
  const api = useApi()
  return useQuery({
    queryKey: queryKeys.connection,
    queryFn: () => api.getConnection(),
    staleTime: Infinity,
  })
}

/** Подписка и «я» меняются вместе: trial_available и devices_used живут в разных ответах. */
function useInvalidateAccount(): () => Promise<void> {
  const qc = useQueryClient()
  return async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: queryKeys.subscription }),
      qc.invalidateQueries({ queryKey: queryKeys.me }),
      qc.invalidateQueries({ queryKey: queryKeys.devices }),
    ])
  }
}

export function useStartTrial(): UseMutationResult<Subscription, ApiError, void> {
  const api = useApi()
  const invalidate = useInvalidateAccount()
  return useMutation({
    mutationFn: () => api.startTrial(),
    onSuccess: invalidate,
  })
}

export function useCreateDevice(): UseMutationResult<
  IssuedDevice,
  ApiError,
  CreateDeviceInput
> {
  const api = useApi()
  const invalidate = useInvalidateAccount()
  return useMutation({
    mutationFn: (input: CreateDeviceInput) => api.createDevice(input),
    onSuccess: invalidate,
  })
}

export function useRevokeDevice(): UseMutationResult<void, ApiError, string> {
  const api = useApi()
  const invalidate = useInvalidateAccount()
  return useMutation({
    mutationFn: (deviceId: string) => api.revokeDevice(deviceId),
    onSuccess: invalidate,
  })
}

export function useCreateCheckout(): UseMutationResult<Checkout, ApiError, string> {
  const api = useApi()
  return useMutation({ mutationFn: (planCode: string) => api.createCheckout(planCode) })
}
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/api`
Expected: 4 теста хуков зелёные, остальное без регрессий.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/api
git commit -m "feat(tma): api client factory, react-query setup and domain hooks"
```

---

# Фаза 2. Каркас

### Задача 9: Форматтеры и производные подписки

Байты, деньги, даты и «сколько осталось» встречаются на всех экранах. Это
чистые функции — их правильное место в `lib/`, и они тестируются без React.
Здесь же живут производные подписки: вопрос «активна ли она» имеет ровно один
правильный ответ, и он не должен решаться в каждом компоненте заново.

**Files:**
- Create: `frontend/tma/src/lib/format.ts`
- Create: `frontend/tma/src/lib/format.test.ts`
- Create: `frontend/tma/src/lib/subscription.ts`
- Create: `frontend/tma/src/lib/subscription.test.ts`

**Interfaces:**
- Consumes: `Lang` из `telegram/auth.ts`, `Subscription` из `api/types.ts`
- Produces:
  - `formatBytes(bytes: number, lang: Lang): string`
  - `formatMoney(minorUnits: number, currency: string, lang: Lang): string`
  - `formatDate(iso: string, lang: Lang): string`
  - `formatCountdown(msLeft: number): string`
  - `isLive(sub: Subscription | null): boolean`
  - `daysLeft(sub: Subscription, now?: number): number`
  - `trafficPercent(sub: Subscription): number | null`
  - `canIssueDevice(sub: Subscription | null): boolean`
  - `statusMessageKey(sub: Subscription): MessageKey`

- [ ] **Шаг 1: Написать падающие тесты форматтеров**

`src/lib/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatBytes, formatCountdown, formatDate, formatMoney } from './format'

/** Intl вставляет неразрывные пробелы — для читаемости утверждений нормализуем. */
const norm = (s: string) => s.replace(/[  ]/g, ' ')

describe('formatBytes', () => {
  it('ноль', () => {
    expect(norm(formatBytes(0, 'ru'))).toBe('0 Б')
  })

  it('килобайты, мегабайты, гигабайты, терабайты', () => {
    expect(norm(formatBytes(2048, 'ru'))).toBe('2 КБ')
    expect(norm(formatBytes(5 * 1024 ** 2, 'ru'))).toBe('5 МБ')
    expect(norm(formatBytes(1024 ** 3, 'ru'))).toBe('1 ГБ')
    expect(norm(formatBytes(3 * 1024 ** 4, 'ru'))).toBe('3 ТБ')
  })

  it('дробная часть — один знак и только когда нужна', () => {
    expect(norm(formatBytes(1.5 * 1024 ** 3, 'ru'))).toBe('1,5 ГБ')
    expect(norm(formatBytes(1.04 * 1024 ** 3, 'ru'))).toBe('1 ГБ')
  })

  it('английские единицы', () => {
    expect(norm(formatBytes(1024 ** 3, 'en'))).toBe('1 GB')
  })

  it('отрицательные и NaN не показываются пользователю как мусор', () => {
    expect(norm(formatBytes(-5, 'ru'))).toBe('0 Б')
    expect(norm(formatBytes(Number.NaN, 'ru'))).toBe('0 Б')
  })
})

describe('formatMoney', () => {
  it('минорные единицы превращаются в рубли', () => {
    expect(norm(formatMoney(29900, 'RUB', 'ru'))).toBe('299 ₽')
  })

  it('копейки показываются, когда они есть', () => {
    expect(norm(formatMoney(29950, 'RUB', 'ru'))).toBe('299,50 ₽')
  })

  it('доллары в английской локали', () => {
    expect(norm(formatMoney(999, 'USD', 'en'))).toBe('$9.99')
  })

  it('Telegram Stars — не ISO-валюта, Intl её не знает', () => {
    expect(formatMoney(150, 'XTR', 'ru')).toBe('150 ⭐')
  })

  it('неизвестная валюта не роняет приложение', () => {
    expect(norm(formatMoney(100, 'ZZZ', 'ru'))).toContain('1')
  })
})

describe('formatDate', () => {
  it('русская дата', () => {
    expect(norm(formatDate('2026-05-05T10:00:00Z', 'ru'))).toBe('5 мая 2026 г.')
  })

  it('английская дата', () => {
    expect(norm(formatDate('2026-05-05T10:00:00Z', 'en'))).toBe('May 5, 2026')
  })

  it('битая дата не роняет рендер', () => {
    expect(formatDate('не-дата', 'ru')).toBe('—')
  })
})

describe('formatCountdown', () => {
  it('минуты и секунды', () => {
    expect(formatCountdown(14 * 60_000 + 59_000)).toBe('14:59')
  })

  it('дополняет секунды нулём', () => {
    expect(formatCountdown(60_000 + 5_000)).toBe('01:05')
  })

  it('истёкшее время — нули, а не отрицательные значения', () => {
    expect(formatCountdown(-1)).toBe('00:00')
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/lib/format.test.ts`
Expected: FAIL, `Failed to resolve import "./format"`.

- [ ] **Шаг 3: Реализовать `format.ts`**

```ts
import type { Lang } from '../telegram/auth'

const LOCALES: Record<Lang, string> = { ru: 'ru-RU', en: 'en-US' }

/**
 * Единицы держим здесь, а не в i18n-каталогах: это формат числа, а не текст
 * интерфейса. Intl style:'unit' даёт нестабильный вывод между версиями ICU.
 */
const BYTE_UNITS: Record<Lang, readonly string[]> = {
  ru: ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ', 'ПБ'],
  en: ['B', 'KB', 'MB', 'GB', 'TB', 'PB'],
}

export function formatBytes(bytes: number, lang: Lang): string {
  const units = BYTE_UNITS[lang]
  if (!Number.isFinite(bytes) || bytes <= 0) return `0 ${units[0]}`

  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }

  const formatted = new Intl.NumberFormat(LOCALES[lang], {
    maximumFractionDigits: index === 0 ? 0 : 1,
  }).format(value)

  return `${formatted} ${units[index]}`
}

export function formatMoney(minorUnits: number, currency: string, lang: Lang): string {
  // Telegram Stars не входят в ISO 4217 — Intl на них бросает RangeError.
  if (currency === 'XTR') {
    return `${new Intl.NumberFormat(LOCALES[lang]).format(minorUnits)} ⭐`
  }

  const major = minorUnits / 100
  try {
    return new Intl.NumberFormat(LOCALES[lang], {
      style: 'currency',
      currency,
      // 299 ₽ вместо 299,00 ₽, но 299,50 ₽ сохраняется
      minimumFractionDigits: Number.isInteger(major) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(major)
  } catch {
    return `${new Intl.NumberFormat(LOCALES[lang]).format(major)} ${currency}`
  }
}

export function formatDate(iso: string, lang: Lang): string {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return '—'
  return new Intl.DateTimeFormat(LOCALES[lang], {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(ms))
}

/** Обратный отсчёт mm:ss для TTL одноразовой ссылки. */
export function formatCountdown(msLeft: number): string {
  const total = Math.max(0, Math.floor(msLeft / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
```

- [ ] **Шаг 4: Написать падающие тесты производных подписки**

`src/lib/subscription.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Plan, Subscription, SubscriptionStatus } from '../api/types'
import { canIssueDevice, daysLeft, isLive, statusMessageKey, trafficPercent } from './subscription'

const GB = 1024 ** 3
const DAY = 86_400_000
const NOW = Date.UTC(2026, 4, 1, 12, 0, 0)

const plan: Plan = {
  code: 'month_1',
  name: 'Месяц',
  description: '',
  duration_days: 30,
  device_limit: 3,
  traffic_limit_bytes: 200 * GB,
  speed_limit_kbps: null,
  price_amount: 29900,
  currency: 'RUB',
  is_trial: false,
  sort_order: 10,
}

function sub(over: Partial<Subscription> = {}): Subscription {
  return {
    id: 'sub_1',
    plan,
    status: 'active',
    started_at: new Date(NOW - 10 * DAY).toISOString(),
    expires_at: new Date(NOW + 20 * DAY).toISOString(),
    traffic_used_bytes: 50 * GB,
    traffic_limit_bytes: 200 * GB,
    traffic_period_start: new Date(NOW - 10 * DAY).toISOString(),
    device_limit: 3,
    devices_used: 1,
    auto_renew: true,
    ...over,
  }
}

describe('isLive', () => {
  it('active, trial и cancelled дают доступ', () => {
    for (const status of ['active', 'trial', 'cancelled'] as SubscriptionStatus[]) {
      expect(isLive(sub({ status })), status).toBe(true)
    }
  })

  it('expired, exhausted, blocked и pending_payment доступа не дают', () => {
    for (const status of [
      'expired',
      'exhausted',
      'blocked',
      'pending_payment',
    ] as SubscriptionStatus[]) {
      expect(isLive(sub({ status })), status).toBe(false)
    }
  })

  it('отсутствие подписки — не доступ', () => {
    expect(isLive(null)).toBe(false)
  })
})

describe('daysLeft', () => {
  it('считает полные дни до окончания', () => {
    expect(daysLeft(sub(), NOW)).toBe(20)
  })

  it('округляет вверх: неполный день ещё оплачен', () => {
    expect(daysLeft(sub({ expires_at: new Date(NOW + 1.2 * DAY).toISOString() }), NOW)).toBe(2)
  })

  it('прошедшая дата даёт ноль, а не отрицательное число', () => {
    expect(daysLeft(sub({ expires_at: new Date(NOW - 5 * DAY).toISOString() }), NOW)).toBe(0)
  })

  it('бессрочная подписка даёт Infinity', () => {
    expect(daysLeft(sub({ expires_at: null }), NOW)).toBe(Infinity)
  })
})

describe('trafficPercent', () => {
  it('25 % от лимита', () => {
    expect(trafficPercent(sub())).toBe(25)
  })

  it('безлимит даёт null, а не 0', () => {
    expect(trafficPercent(sub({ traffic_limit_bytes: null }))).toBeNull()
  })

  it('перерасход не выходит за 100', () => {
    expect(trafficPercent(sub({ traffic_used_bytes: 500 * GB }))).toBe(100)
  })
})

describe('canIssueDevice', () => {
  it('можно, пока есть свободные слоты и доступ живой', () => {
    expect(canIssueDevice(sub({ devices_used: 2 }))).toBe(true)
  })

  it('нельзя при выбранном лимите', () => {
    expect(canIssueDevice(sub({ devices_used: 3 }))).toBe(false)
  })

  it('нельзя на истёкшей подписке', () => {
    expect(canIssueDevice(sub({ status: 'expired', devices_used: 0 }))).toBe(false)
  })

  it('можно при cancelled — период оплачен', () => {
    expect(canIssueDevice(sub({ status: 'cancelled', devices_used: 0 }))).toBe(true)
  })
})

describe('statusMessageKey', () => {
  it('каждому статусу соответствует ключ каталога', () => {
    expect(statusMessageKey(sub({ status: 'cancelled' }))).toBe('status.cancelled')
    expect(statusMessageKey(sub({ status: 'exhausted' }))).toBe('status.exhausted')
  })
})
```

- [ ] **Шаг 5: Убедиться, что тесты падают**

Run: `npm test -- src/lib/subscription.test.ts`
Expected: FAIL, `Failed to resolve import "./subscription"`.

- [ ] **Шаг 6: Реализовать `subscription.ts`**

```ts
import type { Subscription, SubscriptionStatus } from '../api/types'
import type { MessageKey } from '../i18n/ru'

const DAY = 86_400_000

/**
 * cancelled входит сюда сознательно: отмена автопродления не отключает
 * доступ, клиент дорабатывает оплаченный период до expires_at.
 */
const LIVE: ReadonlySet<SubscriptionStatus> = new Set<SubscriptionStatus>([
  'trial',
  'active',
  'cancelled',
])

export function isLive(sub: Subscription | null): boolean {
  return sub !== null && LIVE.has(sub.status)
}

export function daysLeft(sub: Subscription, now: number = Date.now()): number {
  if (sub.expires_at === null) return Infinity
  const ms = Date.parse(sub.expires_at) - now
  if (Number.isNaN(ms)) return 0
  return Math.max(0, Math.ceil(ms / DAY))
}

/** null = безлимитный тариф. Число всегда в диапазоне 0…100. */
export function trafficPercent(sub: Subscription): number | null {
  if (sub.traffic_limit_bytes === null || sub.traffic_limit_bytes <= 0) return null
  const ratio = (sub.traffic_used_bytes / sub.traffic_limit_bytes) * 100
  return Math.min(100, Math.max(0, Math.round(ratio)))
}

export function canIssueDevice(sub: Subscription | null): boolean {
  return isLive(sub) && sub!.devices_used < sub!.device_limit
}

export function statusMessageKey(sub: Subscription): MessageKey {
  return `status.${sub.status}` as MessageKey
}
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/lib`
Expected: 26 passed.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/lib
git commit -m "feat(tma): locale-aware formatters and subscription derivations"
```

---

### Задача 10: Кнопка «Назад» Telegram, связанная с роутером

В Telegram нет браузерной панели: единственный способ вернуться назад —
нативная кнопка клиента. Она должна появляться на вложенных экранах, исчезать
на корневых и вести туда же, куда ведёт логическая иерархия, а не в историю
браузера (после `Купить → оплата → возврат` история непредсказуема).

**Files:**
- Create: `frontend/tma/src/telegram/backButton.ts`
- Create: `frontend/tma/src/telegram/backButton.test.tsx`

**Interfaces:**
- Consumes: `backButton` из `@telegram-apps/sdk-react`, `useNavigate` из `react-router`
- Produces: `useBackButton(target: string | null): void` — `null` прячет кнопку,
  строка показывает её и ведёт на указанный путь

- [ ] **Шаг 1: Написать падающий тест**

`src/telegram/backButton.test.tsx`:

```tsx
import { renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const navigate = vi.fn()
const offClick = vi.fn()

const sdk = vi.hoisted(() => ({
  show: vi.fn(),
  hide: vi.fn(),
  onClick: vi.fn(),
  isMounted: vi.fn(() => true),
}))

vi.mock('@telegram-apps/sdk-react', () => ({
  backButton: {
    show: Object.assign(sdk.show, { isAvailable: () => true }),
    hide: Object.assign(sdk.hide, { isAvailable: () => true }),
    onClick: Object.assign(sdk.onClick, { isAvailable: () => true }),
    isMounted: sdk.isMounted,
  },
}))

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => navigate }
})

const { useBackButton } = await import('./backButton')

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
)

beforeEach(() => {
  vi.clearAllMocks()
  sdk.onClick.mockReturnValue(offClick)
})

describe('useBackButton', () => {
  it('показывает кнопку, когда цель задана', () => {
    renderHook(() => useBackButton('/devices'), { wrapper })
    expect(sdk.show).toHaveBeenCalled()
    expect(sdk.hide).not.toHaveBeenCalled()
  })

  it('прячет кнопку на корневом экране', () => {
    renderHook(() => useBackButton(null), { wrapper })
    expect(sdk.hide).toHaveBeenCalled()
    expect(sdk.show).not.toHaveBeenCalled()
  })

  it('клик ведёт на указанный путь, а не в историю браузера', () => {
    renderHook(() => useBackButton('/devices'), { wrapper })
    const handler = sdk.onClick.mock.calls[0][0] as () => void
    handler()
    expect(navigate).toHaveBeenCalledWith('/devices')
  })

  it('отписывается при размонтировании — иначе обработчики копятся', () => {
    const { unmount } = renderHook(() => useBackButton('/devices'), { wrapper })
    unmount()
    expect(offClick).toHaveBeenCalled()
    expect(sdk.hide).toHaveBeenCalled()
  })
})
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `npm test -- src/telegram/backButton.test.tsx`
Expected: FAIL, `Failed to resolve import "./backButton"`.

- [ ] **Шаг 3: Реализовать хук**

`src/telegram/backButton.ts`:

```ts
import { backButton } from '@telegram-apps/sdk-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'

/**
 * Управляет нативной кнопкой «Назад» Telegram.
 * @param target путь, на который уводит кнопка; null — кнопку скрыть.
 *
 * Переход делается по явному пути, а не через history.back(): после
 * возврата из внешней checkout-страницы история браузера непредсказуема.
 */
export function useBackButton(target: string | null): void {
  const navigate = useNavigate()

  useEffect(() => {
    if (!backButton.isMounted()) return

    if (target === null) {
      if (backButton.hide.isAvailable()) backButton.hide()
      return
    }

    if (backButton.show.isAvailable()) backButton.show()

    const off = backButton.onClick.isAvailable()
      ? backButton.onClick(() => {
          void navigate(target)
        })
      : undefined

    return () => {
      off?.()
      if (backButton.hide.isAvailable()) backButton.hide()
    }
  }, [target, navigate])
}
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Run: `npm test -- src/telegram`
Expected: 10 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/tma/src/telegram
git commit -m "feat(tma): telegram back button bound to router paths"
```

---

### Задача 11: UI-примитивы на теме Telegram

Экраны Mini App выглядят как нативные списки Telegram: секции с заголовком,
ячейки с разделителями, крупная кнопка внизу. Собрать это один раз дешевле,
чем повторять на семи экранах. Все цвета — только токены `tg-*` из Задачи 1;
ни одного захардкоженного `#hex`, иначе тёмная тема клиента развалится.

**Files:**
- Create: `frontend/tma/src/ui/Button.tsx`
- Create: `frontend/tma/src/ui/Section.tsx`
- Create: `frontend/tma/src/ui/Cell.tsx`
- Create: `frontend/tma/src/ui/Badge.tsx`
- Create: `frontend/tma/src/ui/ProgressBar.tsx`
- Create: `frontend/tma/src/ui/Skeleton.tsx`
- Create: `frontend/tma/src/ui/EmptyState.tsx`
- Create: `frontend/tma/src/ui/ErrorState.tsx`
- Create: `frontend/tma/src/ui/Sheet.tsx`
- Create: `frontend/tma/src/ui/ui.test.tsx`
- Create: `frontend/tma/src/test/renderWithProviders.tsx`

**Interfaces:**
- Consumes: `useT`, `ApiError`, `haptic`
- Produces:
  - `<Button variant="primary"|"secondary"|"destructive" loading? disabled? onClick? type?>`
  - `<Section title? footer?>`, `<Cell title subtitle? right? onClick? destructive?>`
  - `<Badge tone="neutral"|"success"|"warning"|"danger">`
  - `<ProgressBar percent tone?>`, `<Skeleton className?>`
  - `<EmptyState icon title body? action?>`
  - `<ErrorState error onRetry?>`
  - `<Sheet open onClose title children>`
  - `renderWithProviders(ui, { client?, lang?, route? })` из `test/renderWithProviders.tsx`

- [ ] **Шаг 1: Написать хелпер рендера для тестов**

`src/test/renderWithProviders.tsx` — им пользуются все последующие задачи:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { ApiProvider } from '../api/ApiProvider'
import type { ApiClient } from '../api/contract'
import { createMockClient } from '../api/mock/client'
import { I18nProvider } from '../i18n/I18nProvider'
import type { Lang } from '../telegram/auth'

export interface RenderOptions {
  client?: ApiClient
  lang?: Lang
  route?: string
}

export function renderWithProviders(
  ui: ReactElement,
  { client = createMockClient(), lang = 'ru', route = '/' }: RenderOptions = {},
): RenderResult {
  // retry:false и gcTime:0 — иначе тесты ждут бэкоффов и текут кэшем между собой.
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiProvider client={client}>
          <I18nProvider lang={lang}>
            <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
          </I18nProvider>
        </ApiProvider>
      </QueryClientProvider>
    )
  }

  return render(ui, { wrapper: Wrapper })
}
```

- [ ] **Шаг 2: Написать падающие тесты примитивов**

`src/ui/ui.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { renderWithProviders } from '../test/renderWithProviders'
import { Button } from './Button'
import { Cell } from './Cell'
import { ErrorState } from './ErrorState'
import { ProgressBar } from './ProgressBar'
import { Sheet } from './Sheet'

describe('Button', () => {
  it('вызывает обработчик по клику', async () => {
    const onClick = vi.fn()
    renderWithProviders(<Button onClick={onClick}>Купить</Button>)
    await userEvent.click(screen.getByRole('button', { name: 'Купить' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('в состоянии loading заблокирована и помечена для скринридера', () => {
    renderWithProviders(
      <Button loading onClick={vi.fn()}>
        Купить
      </Button>,
    )
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
  })

  it('disabled не пропускает клики', async () => {
    const onClick = vi.fn()
    renderWithProviders(
      <Button disabled onClick={onClick}>
        Купить
      </Button>,
    )
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('Cell', () => {
  it('кликабельная ячейка — это кнопка, а не div с обработчиком', async () => {
    const onClick = vi.fn()
    renderWithProviders(<Cell title="iPhone" subtitle="онлайн" onClick={onClick} />)
    await userEvent.click(screen.getByRole('button', { name: /iPhone/ }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('некликабельная ячейка кнопкой не притворяется', () => {
    renderWithProviders(<Cell title="Трафик" subtitle="12 ГБ" />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('ProgressBar', () => {
  it('сообщает значение через ARIA', () => {
    renderWithProviders(<ProgressBar percent={42} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '42')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('зажимает выход за границы', () => {
    renderWithProviders(<ProgressBar percent={140} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })
})

describe('ErrorState', () => {
  it('показывает переведённое сообщение по коду ошибки', () => {
    renderWithProviders(<ErrorState error={new ApiError('rate_limited', 429)} />)
    expect(screen.getByText('Слишком много запросов. Подождите минуту.')).toBeVisible()
  })

  it('кнопка повтора появляется только для повторяемых ошибок', () => {
    const onRetry = vi.fn()
    renderWithProviders(
      <ErrorState error={new ApiError('device_limit_reached', 409)} onRetry={onRetry} />,
    )
    expect(screen.queryByRole('button', { name: 'Повторить' })).toBeNull()
  })

  it('повторяемая ошибка даёт кнопку и вызывает обработчик', async () => {
    const onRetry = vi.fn()
    renderWithProviders(<ErrorState error={new ApiError('network', 0)} onRetry={onRetry} />)
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('Sheet', () => {
  it('закрытый лист не рендерится', () => {
    renderWithProviders(
      <Sheet open={false} onClose={vi.fn()} title="Отозвать?">
        тело
      </Sheet>,
    )
    expect(screen.queryByText('тело')).toBeNull()
  })

  it('Escape закрывает лист', async () => {
    const onClose = vi.fn()
    renderWithProviders(
      <Sheet open onClose={onClose} title="Отозвать?">
        тело
      </Sheet>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('открытый лист — модальный диалог', () => {
    renderWithProviders(
      <Sheet open onClose={vi.fn()} title="Отозвать?">
        тело
      </Sheet>,
    )
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })
})
```

- [ ] **Шаг 3: Убедиться, что тесты падают**

Run: `npm test -- src/ui/ui.test.tsx`
Expected: FAIL, модули не найдены.

- [ ] **Шаг 4: Реализовать `Button`**

`src/ui/Button.tsx`:

```tsx
import type { ReactNode } from 'react'
import { haptic } from '../telegram/haptics'

type Variant = 'primary' | 'secondary' | 'destructive'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-tg-button text-tg-button-text',
  secondary: 'bg-tg-secondary-bg text-tg-text',
  destructive: 'bg-tg-secondary-bg text-tg-destructive',
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  loading = false,
  disabled = false,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  variant?: Variant
  loading?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  const inactive = disabled || loading

  return (
    <button
      type={type}
      disabled={inactive}
      aria-busy={loading || undefined}
      onClick={() => {
        if (inactive) return
        haptic.impact('light')
        onClick?.()
      }}
      className={`w-full rounded-xl px-4 py-3.5 text-base font-medium transition-opacity active:opacity-70 disabled:opacity-50 ${VARIANTS[variant]}`}
    >
      {children}
    </button>
  )
}
```

- [ ] **Шаг 5: Реализовать `Section`, `Cell`, `Badge`, `ProgressBar`, `Skeleton`**

`src/ui/Section.tsx`:

```tsx
import type { ReactNode } from 'react'

export function Section({
  title,
  footer,
  children,
}: {
  title?: string
  footer?: string
  children: ReactNode
}) {
  return (
    <section className="mb-6">
      {title && (
        <h2 className="mb-2 px-4 text-[13px] font-normal uppercase tracking-wide text-tg-hint">
          {title}
        </h2>
      )}
      <div className="overflow-hidden rounded-xl bg-tg-section-bg">{children}</div>
      {footer && <p className="mt-2 px-4 text-[13px] leading-snug text-tg-hint">{footer}</p>}
    </section>
  )
}
```

`src/ui/Cell.tsx`:

```tsx
import type { ReactNode } from 'react'
import { haptic } from '../telegram/haptics'

export function Cell({
  title,
  subtitle,
  right,
  onClick,
  destructive = false,
}: {
  title: ReactNode
  subtitle?: ReactNode
  right?: ReactNode
  onClick?: () => void
  destructive?: boolean
}) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span
          className={`block truncate text-base ${destructive ? 'text-tg-destructive' : 'text-tg-text'}`}
        >
          {title}
        </span>
        {subtitle !== undefined && (
          <span className="mt-0.5 block truncate text-[13px] text-tg-hint">{subtitle}</span>
        )}
      </span>
      {right !== undefined && (
        <span className="shrink-0 text-[15px] text-tg-hint">{right}</span>
      )}
    </>
  )

  const shared =
    'flex w-full items-center gap-3 px-4 py-3 text-left border-b border-tg-separator last:border-b-0'

  // Кликабельная ячейка обязана быть <button>: иначе она недоступна с клавиатуры
  // и невидима для скринридера.
  if (!onClick) return <div className={shared}>{body}</div>

  return (
    <button
      type="button"
      className={`${shared} active:bg-tg-secondary-bg`}
      onClick={() => {
        haptic.selection()
        onClick()
      }}
    >
      {body}
    </button>
  )
}
```

`src/ui/Badge.tsx`:

```tsx
import type { ReactNode } from 'react'

type Tone = 'neutral' | 'success' | 'warning' | 'danger'

const TONES: Record<Tone, string> = {
  neutral: 'bg-tg-secondary-bg text-tg-hint',
  success: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  warning: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  danger: 'bg-red-500/15 text-tg-destructive',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[13px] font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}
```

`src/ui/ProgressBar.tsx`:

```tsx
type Tone = 'normal' | 'warning' | 'danger'

const TONES: Record<Tone, string> = {
  normal: 'bg-tg-button',
  warning: 'bg-amber-500',
  danger: 'bg-red-500',
}

export function ProgressBar({
  percent,
  tone = 'normal',
}: {
  percent: number
  tone?: Tone
}) {
  const value = Math.min(100, Math.max(0, Math.round(percent)))

  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-2 w-full overflow-hidden rounded-full bg-tg-secondary-bg"
    >
      <div
        className={`h-full rounded-full transition-[width] duration-300 ${TONES[tone]}`}
        style={{ width: `${value}%` }}
      />
    </div>
  )
}
```

`src/ui/Skeleton.tsx`:

```tsx
export function Skeleton({ className = 'h-4 w-full' }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-md bg-tg-secondary-bg ${className}`}
    />
  )
}
```

- [ ] **Шаг 6: Реализовать `EmptyState`, `ErrorState`, `Sheet`**

`src/ui/EmptyState.tsx`:

```tsx
import type { ReactNode } from 'react'

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center px-8 py-12 text-center">
      <div className="mb-4 text-5xl" aria-hidden="true">
        {icon}
      </div>
      <h2 className="mb-1 text-lg font-semibold text-tg-text">{title}</h2>
      {body && <p className="mb-6 text-[15px] leading-snug text-tg-hint">{body}</p>}
      {action && <div className="w-full max-w-xs">{action}</div>}
    </div>
  )
}
```

`src/ui/ErrorState.tsx`:

```tsx
import { ApiError, toApiError } from '../api/errors'
import { useT } from '../i18n/useT'
import { Button } from './Button'

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  const { t } = useT()
  const apiError: ApiError = toApiError(error)

  return (
    <div className="flex flex-col items-center px-8 py-12 text-center">
      <div className="mb-4 text-5xl" aria-hidden="true">
        ⚠️
      </div>
      <h2 className="mb-1 text-lg font-semibold text-tg-text">{t('error.title')}</h2>
      <p className="mb-6 text-[15px] leading-snug text-tg-hint">
        {t(apiError.messageKey())}
      </p>
      {/* Повтор предлагается только там, где он может помочь. */}
      {onRetry && apiError.retryable && (
        <div className="w-full max-w-xs">
          <Button variant="secondary" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        </div>
      )}
    </div>
  )
}
```

`src/ui/Sheet.tsx`:

```tsx
import { useEffect, type ReactNode } from 'react'

export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end">
      <button
        type="button"
        aria-label="Закрыть"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-full rounded-t-2xl bg-tg-section-bg p-4 pb-[calc(1rem+var(--safe-bottom))]"
      >
        <h2 className="mb-3 text-center text-lg font-semibold text-tg-text">{title}</h2>
        {children}
      </div>
    </div>
  )
}
```

Ярлык кнопки закрытия — единственная строка вне каталога i18n; вынести её в
`common.close` при первом же проходе по доступности.

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/ui`
Expected: 12 passed.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/ui frontend/tma/src/test
git commit -m "feat(tma): telegram-themed ui primitives and test render helper"
```

---

### Задача 12: Каркас приложения — провайдеры, маршруты, таб-бар

Здесь всё собирается вместе: `main.tsx` получает настоящий `App`, появляются
маршруты и нижняя навигация. После этой задачи приложение впервые запускается
как приложение, а не как набор модулей.

**Files:**
- Create: `frontend/tma/src/app/routes.ts`
- Create: `frontend/tma/src/app/router.tsx`
- Create: `frontend/tma/src/app/Layout.tsx`
- Create: `frontend/tma/src/app/TabBar.tsx`
- Modify: `frontend/tma/src/app/App.tsx` (заменяет заглушку из Задачи 2)
- Modify: `frontend/tma/src/main.tsx`
- Create: `frontend/tma/src/app/router.test.tsx`

**Interfaces:**
- Consumes: `createApiClientAsync`, `createQueryClient`, `I18nProvider`, `ApiProvider`,
  `useBackButton`
- Produces:
  - `<App client>` — принимает готовый `ApiClient` (создаётся в `main.tsx`)
  - `<AppRoutes>` — таблица маршрутов
  - `ROUTES` — константы путей из `app/routes.ts`: `home`, `plans`, `devices`,
    `deviceNew`, `deviceSecret`, `instructions(platform)`. Реэкспортируются из
    `app/router.tsx`, поэтому экраны могут импортировать их оттуда

- [ ] **Шаг 1: Написать падающий тест маршрутизации**

Утверждения намеренно опираются на **таб-бар**, а не на содержимое экранов:
сейчас за маршрутами стоят заглушки, в Задачах 14–19 их заменят настоящие
экраны, и тест, проверяющий их тексты, сломался бы на ровном месте.
`NavLink` из `react-router` проставляет активной ссылке `aria-current="page"` —
это и есть устойчивый признак «мы на этом маршруте».

`src/app/router.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetStore, setLatency } from '../api/mock/store'
import { renderWithProviders } from '../test/renderWithProviders'
import { AppRoutes } from './router'
import { ROUTES } from './routes'

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
})

/** Активная вкладка — единственный признак маршрута, не зависящий от экранов. */
async function activeTab(): Promise<string | null> {
  const active = await waitFor(() => {
    const found = screen
      .getAllByRole('link')
      .find((link) => link.getAttribute('aria-current') === 'page')
    if (!found) throw new Error('нет активной вкладки')
    return found
  })
  return active.textContent
}

describe('маршруты', () => {
  it('корень открывает вкладку подписки', async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.home })
    expect(await activeTab()).toContain('Подписка')
  })

  it('таб-бар ведёт на тарифы', async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.home })
    await userEvent.click(await screen.findByRole('link', { name: /Тарифы/ }))
    expect(await activeTab()).toContain('Тарифы')
  })

  it('неизвестный путь уводит на корень, а не показывает пустоту', async () => {
    renderWithProviders(<AppRoutes />, { route: '/чего-то-нет' })
    expect(await activeTab()).toContain('Подписка')
  })

  it('вложенный экран не показывает таб-бар', async () => {
    renderWithProviders(<AppRoutes />, { route: ROUTES.deviceNew })
    await waitFor(() => expect(screen.getByRole('heading')).toBeVisible())
    expect(screen.queryByRole('link', { name: /Тарифы/ })).toBeNull()
  })
})
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `npm test -- src/app/router.test.tsx`
Expected: FAIL, `Failed to resolve import "./router"`.

- [ ] **Шаг 3: Объявить пути и маршруты**

Пути живут в отдельном модуле `app/routes.ts`. Причина не косметическая:
`router.tsx` импортирует `Layout`, `Layout` — `TabBar`, а `TabBar` нужны пути.
Держи пути в `router.tsx` — получится цикл импортов, который в сборке
проявляется как `ROUTES is undefined` в момент первого рендера.

`src/app/routes.ts`:

```ts
import type { Platform } from '../api/types'

export const ROUTES = {
  home: '/',
  plans: '/plans',
  devices: '/devices',
  deviceNew: '/devices/new',
  deviceSecret: '/devices/secret',
  instructions: (platform: Platform | ':platform' = ':platform') =>
    `/instructions/${platform}`,
} as const
```

`src/app/router.tsx`. Экраны подключаются лениво (`React.lazy`) — Mini App
открывается на мобильной сети, и первый экран не должен ждать загрузки кода
инструкций и QR. `ROUTES` реэкспортируется отсюда, чтобы экраны импортировали
пути из одного привычного места.

```tsx
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { Skeleton } from '../ui/Skeleton'
import { Layout } from './Layout'
import { ROUTES } from './routes'

export { ROUTES }

const SubscriptionScreen = lazy(() => import('../screens/Subscription/SubscriptionScreen'))
const PlansScreen = lazy(() => import('../screens/Plans/PlansScreen'))
const DevicesScreen = lazy(() => import('../screens/Devices/DevicesScreen'))
const DeviceCreateScreen = lazy(() => import('../screens/DeviceCreate/DeviceCreateScreen'))
const DeviceSecretScreen = lazy(() => import('../screens/DeviceSecret/DeviceSecretScreen'))
const InstructionsScreen = lazy(() => import('../screens/Instructions/InstructionsScreen'))

function ScreenFallback() {
  return (
    <div className="space-y-3 p-4">
      <Skeleton className="h-6 w-1/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}

export function AppRoutes() {
  return (
    <Suspense fallback={<ScreenFallback />}>
      <Routes>
        {/* Корневые экраны — с таб-баром */}
        <Route element={<Layout withTabBar />}>
          <Route path={ROUTES.home} element={<SubscriptionScreen />} />
          <Route path={ROUTES.plans} element={<PlansScreen />} />
          <Route path={ROUTES.devices} element={<DevicesScreen />} />
        </Route>

        {/* Вложенные экраны — без таб-бара, с кнопкой «Назад» Telegram */}
        <Route element={<Layout />}>
          <Route path={ROUTES.deviceNew} element={<DeviceCreateScreen />} />
          <Route path={ROUTES.deviceSecret} element={<DeviceSecretScreen />} />
          <Route path={ROUTES.instructions()} element={<InstructionsScreen />} />
        </Route>

        <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
      </Routes>
    </Suspense>
  )
}
```

- [ ] **Шаг 4: Реализовать `Layout` и `TabBar`**

`src/app/Layout.tsx`:

```tsx
import { Outlet } from 'react-router'
import { TabBar } from './TabBar'

export function Layout({ withTabBar = false }: { withTabBar?: boolean }) {
  return (
    <div className="flex min-h-full flex-col bg-tg-secondary-bg">
      <main
        className="flex-1 pt-[var(--safe-top)]"
        // Место под таб-бар и под системную полосу жестов.
        style={{
          paddingBottom: withTabBar
            ? 'calc(4rem + var(--safe-bottom))'
            : 'calc(1rem + var(--safe-bottom))',
        }}
      >
        <Outlet />
      </main>
      {withTabBar && <TabBar />}
    </div>
  )
}
```

`src/app/TabBar.tsx`:

```tsx
import { NavLink } from 'react-router'
import { useT } from '../i18n/useT'
import { haptic } from '../telegram/haptics'
// Импорт из routes.ts, а не из router.tsx — иначе цикл router → Layout → TabBar.
import { ROUTES } from './routes'

const TABS = [
  { to: ROUTES.home, icon: '🔑', labelKey: 'nav.subscription' },
  { to: ROUTES.devices, icon: '📱', labelKey: 'nav.devices' },
  { to: ROUTES.plans, icon: '💳', labelKey: 'nav.plans' },
] as const

export function TabBar() {
  const { t } = useT()

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-tg-separator bg-tg-section-bg pb-[var(--safe-bottom)]">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
          onClick={() => haptic.selection()}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] ${
              isActive ? 'text-tg-button' : 'text-tg-hint'
            }`
          }
        >
          <span className="text-xl" aria-hidden="true">
            {tab.icon}
          </span>
          {t(tab.labelKey)}
        </NavLink>
      ))}
    </nav>
  )
}
```

- [ ] **Шаг 5: Собрать `App` и переписать `main.tsx`**

`src/app/App.tsx` (полностью заменяет заглушку):

```tsx
import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter } from 'react-router'
import { ApiProvider } from '../api/ApiProvider'
import type { ApiClient } from '../api/contract'
import { createQueryClient } from '../api/queryClient'
import { I18nProvider } from '../i18n/I18nProvider'
import { AppRoutes } from './router'

export function App({ client }: { client: ApiClient }) {
  // useState, а не модульная константа: QueryClient должен пережить
  // StrictMode-двойной рендер, но не переживать перемонтирование App.
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <I18nProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </I18nProvider>
      </ApiProvider>
    </QueryClientProvider>
  )
}
```

`src/main.tsx`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createApiClientAsync } from './api'
import { initTelegram } from './telegram/init'
import './index.css'

async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV) {
    await import('./telegram/mockEnv')
  }

  initTelegram()

  const [{ App }, client] = await Promise.all([
    import('./app/App'),
    createApiClientAsync(),
  ])

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App client={client} />
    </StrictMode>,
  )
}

void bootstrap()
```

- [ ] **Шаг 6: Создать заглушки экранов, чтобы каркас собрался**

Каждая заменяется полноценным экраном в Задачах 14–19. Заглушка выводит
заголовок из каталога — именно его проверяет тест маршрутов.

```tsx
// src/screens/Subscription/SubscriptionScreen.tsx
import { useT } from '../../i18n/useT'

export default function SubscriptionScreen() {
  const { t } = useT()
  return <h1 className="p-4 text-2xl font-bold text-tg-text">{t('subscription.title')}</h1>
}
```

Аналогично: `Plans/PlansScreen.tsx` (выводит `t('plans.subtitle')`),
`Devices/DevicesScreen.tsx` (`t('devices.title')`),
`DeviceCreate/DeviceCreateScreen.tsx` (`t('deviceCreate.title')`),
`DeviceSecret/DeviceSecretScreen.tsx` (`t('deviceSecret.title')`),
`Instructions/InstructionsScreen.tsx` (`t('instructions.title')`).

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/app`
Expected: 4 passed.

- [ ] **Шаг 8: Проверить руками**

```bash
npm run dev
```

Открыть `localhost:5173`. Должны работать: три вкладки, переключение между
ними, переход по `/devices/new` без таб-бара. Данных на экранах ещё нет — это
ожидаемо.

- [ ] **Шаг 9: Коммит**

```bash
git add frontend/tma/src
git commit -m "feat(tma): app shell with lazy routes, layout and tab bar"
```

---

### Задача 13: Dev-панель переключения сценариев

Без неё разработка на моках упирается в правку кода ради каждого состояния.
С ней проверка «как выглядит экран при исчерпанном трафике» занимает два тапа,
и её можно показать кому угодно, не поднимая бэкенд.

Панель обязана исчезнуть из production-сборки полностью.

**Files:**
- Create: `frontend/tma/src/app/DevPanel.tsx`
- Modify: `frontend/tma/src/app/App.tsx`
- Create: `frontend/tma/src/app/DevPanel.test.tsx`

**Interfaces:**
- Consumes: `SCENARIOS`, `resetStore`, `setFault`, `setLatency`, `getState`,
  `subscribeStore`, `env.devPanel`, `useQueryClient`
- Produces: `<DevPanel />` — плавающая кнопка и лист с переключателями

- [ ] **Шаг 1: Написать падающий тест**

`src/app/DevPanel.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { getState, resetStore, setLatency } from '../api/mock/store'
import { renderWithProviders } from '../test/renderWithProviders'
import { DevPanel } from './DevPanel'

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
})

describe('DevPanel', () => {
  it('открывается по кнопке', async () => {
    renderWithProviders(<DevPanel />)
    await userEvent.click(screen.getByRole('button', { name: /сценарий/i }))
    expect(screen.getByRole('dialog')).toBeVisible()
  })

  it('переключение сценария меняет состояние стора', async () => {
    renderWithProviders(<DevPanel />)
    await userEvent.click(screen.getByRole('button', { name: /сценарий/i }))
    await userEvent.click(screen.getByRole('button', { name: /Трафик исчерпан/ }))

    await waitFor(() => expect(getState().scenario).toBe('exhausted'))
    expect(getState().subscription?.status).toBe('exhausted')
  })

  it('переключение сбоя пишется в стор', async () => {
    renderWithProviders(<DevPanel />)
    await userEvent.click(screen.getByRole('button', { name: /сценарий/i }))
    await userEvent.selectOptions(screen.getByLabelText('Сбой'), 'network')
    expect(getState().fault).toBe('network')
  })
})
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `npm test -- src/app/DevPanel.test.tsx`
Expected: FAIL, `Failed to resolve import "./DevPanel"`.

- [ ] **Шаг 3: Реализовать панель**

`src/app/DevPanel.tsx`. Тексты панели намеренно **не** в каталогах i18n: это
инструмент разработчика, а не интерфейс продукта, и засорять им каталоги
нельзя.

```tsx
import { useQueryClient } from '@tanstack/react-query'
import { useState, useSyncExternalStore } from 'react'
import {
  getState,
  setFault,
  setLatency,
  subscribeStore,
  resetStore,
  type FaultId,
} from '../api/mock/store'
import { SCENARIOS } from '../api/mock/scenarios'
import { Sheet } from '../ui/Sheet'

const FAULTS: { id: FaultId; label: string }[] = [
  { id: 'none', label: 'нет' },
  { id: 'network', label: 'сеть недоступна' },
  { id: 'internal', label: '500 на сервере' },
  { id: 'rate_limited', label: '429 rate limit' },
  { id: 'node_unavailable', label: '503 нода недоступна' },
]

const LATENCIES = [0, 350, 1500, 4000]

export function DevPanel() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const state = useSyncExternalStore(subscribeStore, getState)

  // Смена сценария меняет данные под кэшем — его надо сбросить целиком.
  const applyScenario = async (id: (typeof SCENARIOS)[number]['id']) => {
    resetStore(id)
    await queryClient.resetQueries()
    setOpen(false)
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-3 top-[calc(0.75rem+var(--safe-top))] z-50 rounded-full bg-black/70 px-3 py-1.5 text-[11px] font-mono text-white"
      >
        сценарий: {state.scenario}
      </button>

      <Sheet open={open} onClose={() => setOpen(false)} title="Мок-окружение">
        <div className="max-h-[60vh] space-y-4 overflow-y-auto">
          <div>
            <p className="mb-2 text-[13px] text-tg-hint">Сценарий</p>
            <div className="overflow-hidden rounded-xl bg-tg-secondary-bg">
              {SCENARIOS.map((scenario) => (
                <button
                  key={scenario.id}
                  type="button"
                  onClick={() => void applyScenario(scenario.id)}
                  className={`flex w-full items-center justify-between border-b border-tg-separator px-4 py-2.5 text-left text-[15px] last:border-b-0 ${
                    state.scenario === scenario.id ? 'text-tg-button' : 'text-tg-text'
                  }`}
                >
                  <span>{scenario.label}</span>
                  <span className="font-mono text-[11px] text-tg-hint">{scenario.id}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            <label className="flex-1 text-[13px] text-tg-hint">
              Сбой
              <select
                value={state.fault}
                onChange={(event) => setFault(event.target.value as FaultId)}
                className="mt-1 w-full rounded-lg bg-tg-secondary-bg px-3 py-2 text-[15px] text-tg-text"
              >
                {FAULTS.map((fault) => (
                  <option key={fault.id} value={fault.id}>
                    {fault.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex-1 text-[13px] text-tg-hint">
              Задержка
              <select
                value={state.latencyMs}
                onChange={(event) => setLatency(Number(event.target.value))}
                className="mt-1 w-full rounded-lg bg-tg-secondary-bg px-3 py-2 text-[15px] text-tg-text"
              >
                {LATENCIES.map((ms) => (
                  <option key={ms} value={ms}>
                    {ms} мс
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </Sheet>
    </>
  )
}
```

- [ ] **Шаг 4: Подключить панель под флагом**

В `src/app/App.tsx` добавить ленивый импорт и условный рендер:

```tsx
import { lazy, Suspense, useState } from 'react'
import { env } from '../env'

// Панель существует только в dev-сборке: в production ветка вырезается
// сборщиком вместе с модулем.
const DevPanel = env.devPanel
  ? lazy(() => import('./DevPanel').then((m) => ({ default: m.DevPanel })))
  : null
```

и внутри `<BrowserRouter>`, после `<AppRoutes />`:

```tsx
{DevPanel && (
  <Suspense fallback={null}>
    <DevPanel />
  </Suspense>
)}
```

- [ ] **Шаг 5: Убедиться, что тесты проходят**

Run: `npm test -- src/app`
Expected: 7 passed.

- [ ] **Шаг 6: Проверить, что в production панели нет**

```bash
VITE_DEV_PANEL=false npm run build
grep -r "Мок-окружение" dist/ && echo "НАРУШЕНИЕ: панель попала в бандл" || echo OK
```

Expected: `OK`.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma/src/app
git commit -m "feat(tma): dev-only scenario switcher panel"
```

---

# Фаза 3. Экраны

Задачи 14–19 независимы друг от друга: каждая опирается только на Фазы 0–2.
Их можно вести параллельно.

### Задача 14: Экран тарифов — каталог, trial, покупка

Первый экран, который видит клиент без подписки. Он же решает две отдельные
задачи: активация пробного периода (без оплаты, локально) и запуск покупки
(уход на внешнюю checkout-страницу провайдера).

**Files:**
- Create: `frontend/tma/src/telegram/links.ts`
- Create: `frontend/tma/src/screens/Plans/PlanCard.tsx`
- Create: `frontend/tma/src/screens/Plans/TrialCard.tsx`
- Create: `frontend/tma/src/screens/Plans/useBuyPlan.ts`
- Create: `frontend/tma/src/screens/Plans/trialPreview.ts`
- Modify: `frontend/tma/src/screens/Plans/PlansScreen.tsx` (заменяет заглушку)
- Create: `frontend/tma/src/screens/Plans/PlansScreen.test.tsx`

**Interfaces:**
- Consumes: `usePlans`, `useMe`, `useSubscription`, `useStartTrial`,
  `useCreateCheckout`, `formatMoney`, `formatBytes`, `Section`, `Button`,
  `ErrorState`, `Skeleton`, `useT`
- Produces:
  - `openExternal(url: string): void`, `closeApp(): void` — из `telegram/links.ts`
  - `useBuyPlan(): { buy(planCode: string): void; state: 'idle'|'opening'|'opened'|'failed'; reset(): void }`
  - `<PlanCard plan current? onBuy busy?>`, `<TrialCard plan available onStart busy?>`

- [ ] **Шаг 1: Написать падающие тесты экрана**

`src/screens/Plans/PlansScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockClient } from '../../api/mock/client'
import { resetStore, setFault, setLatency } from '../../api/mock/store'
import { renderWithProviders } from '../../test/renderWithProviders'
import PlansScreen from './PlansScreen'

const openExternal = vi.hoisted(() => vi.fn())
vi.mock('../../telegram/links', () => ({ openExternal, closeApp: vi.fn() }))

beforeEach(() => {
  sessionStorage.clear()
  resetStore('new_user')
  setLatency(0)
  setFault('none')
  openExternal.mockClear()
})

function show() {
  return renderWithProviders(<PlansScreen />, { client: createMockClient() })
}

describe('PlansScreen', () => {
  it('показывает скелет во время загрузки', () => {
    setLatency(50)
    const { container } = show()
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('выводит все тарифы с ценой, сроком и лимитом устройств', async () => {
    show()
    await waitFor(() => expect(screen.getByText('Месяц')).toBeVisible())
    expect(screen.getByText('Полгода')).toBeVisible()
    expect(screen.getByText('Год')).toBeVisible()
    expect(screen.getByRole('button', { name: /299 ₽/ })).toBeVisible()
  })

  it('безлимитный тариф подписан словами, а не «null ГБ»', async () => {
    show()
    await waitFor(() => expect(screen.getAllByText('Безлимитный трафик').length).toBe(2))
  })

  it('новому клиенту предлагает пробный период', async () => {
    show()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Активировать пробный период' })).toBeVisible(),
    )
  })

  it('активация trial создаёт подписку и убирает предложение', async () => {
    show()
    const start = await screen.findByRole('button', {
      name: 'Активировать пробный период',
    })
    await userEvent.click(start)

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Активировать пробный период' }),
      ).toBeNull(),
    )
  })

  it('израсходованный trial показан как использованный и не кликается', async () => {
    resetStore('trial_used')
    show()
    await waitFor(() => expect(screen.getByText('Пробный период уже использован')).toBeVisible())
    expect(
      screen.queryByRole('button', { name: 'Активировать пробный период' }),
    ).toBeNull()
  })

  it('покупка открывает внешнюю ссылку провайдера', async () => {
    resetStore('trial_used')
    show()
    const buy = await screen.findByRole('button', { name: /299 ₽/ })
    await userEvent.click(buy)

    await waitFor(() => expect(openExternal).toHaveBeenCalledOnce())
    expect(openExternal.mock.calls[0][0]).toContain('tribute.tg/checkout/month_1')
  })

  it('после ухода на оплату показывается подсказка о возврате', async () => {
    resetStore('trial_used')
    show()
    await userEvent.click(await screen.findByRole('button', { name: /299 ₽/ }))
    await waitFor(() =>
      expect(screen.getByText(/бот пришлёт сообщение/)).toBeVisible(),
    )
  })

  it('сбой создания checkout показывает ошибку, а не молча ничего', async () => {
    resetStore('trial_used')
    show()
    await screen.findByRole('button', { name: /299 ₽/ })
    setFault('internal')
    await userEvent.click(screen.getByRole('button', { name: /299 ₽/ }))

    await waitFor(() =>
      expect(screen.getByText('Не удалось открыть оплату. Попробуйте ещё раз.')).toBeVisible(),
    )
    expect(openExternal).not.toHaveBeenCalled()
  })

  it('текущий тариф помечен и не предлагается к покупке повторно', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('Текущий тариф')).toBeVisible())
  })

  it('ошибка загрузки каталога даёт экран ошибки с повтором', async () => {
    setFault('network')
    show()
    await waitFor(() => expect(screen.getByText('Что-то пошло не так')).toBeVisible())
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeVisible()
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/screens/Plans`
Expected: FAIL — заглушка экрана не содержит ничего из ожидаемого.

- [ ] **Шаг 3: Реализовать обёртки над ссылками Telegram**

`src/telegram/links.ts`:

```ts
import { miniApp, openLink, openTelegramLink } from '@telegram-apps/sdk-react'

/** Внешняя ссылка: checkout платёжного провайдера, магазин приложений. */
export function openExternal(url: string): void {
  if (openLink.isAvailable()) {
    openLink(url, { tryInstantView: false })
    return
  }
  // Браузер вне Telegram: noopener обязателен — иначе новая вкладка
  // получает доступ к window.opener исходной страницы.
  window.open(url, '_blank', 'noopener,noreferrer')
}

/** Ссылка t.me — открывается внутри Telegram, без выхода в браузер. */
export function openInTelegram(url: string): void {
  if (openTelegramLink.isAvailable()) {
    openTelegramLink(url)
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function closeApp(): void {
  if (miniApp.close.isAvailable()) miniApp.close()
}
```

- [ ] **Шаг 4: Реализовать хук покупки**

`src/screens/Plans/useBuyPlan.ts`:

```ts
import { useCallback, useState } from 'react'
import { useCreateCheckout } from '../../api/hooks'
import { haptic } from '../../telegram/haptics'
import { openExternal } from '../../telegram/links'

export type BuyState = 'idle' | 'opening' | 'opened' | 'failed'

export function useBuyPlan(): {
  buy: (planCode: string) => void
  state: BuyState
  reset: () => void
} {
  const [state, setState] = useState<BuyState>('idle')
  const checkout = useCreateCheckout()

  const buy = useCallback(
    (planCode: string) => {
      setState('opening')
      checkout.mutate(planCode, {
        onSuccess: ({ checkout_url }) => {
          // Приложение не закрываем автоматически: Telegram открывает
          // checkout поверх Mini App, и резкое закрытие выглядит как сбой.
          // Клиент закроет сам либо вернётся по уведомлению бота.
          openExternal(checkout_url)
          haptic.notification('success')
          setState('opened')
        },
        onError: () => {
          haptic.notification('error')
          setState('failed')
        },
      })
    },
    [checkout],
  )

  const reset = useCallback(() => setState('idle'), [])

  return { buy, state, reset }
}
```

- [ ] **Шаг 5: Реализовать карточки**

`src/screens/Plans/PlanCard.tsx`:

```tsx
import type { Plan } from '../../api/types'
import { useT } from '../../i18n/useT'
import { formatBytes, formatMoney } from '../../lib/format'
import { Badge } from '../../ui/Badge'
import { Button } from '../../ui/Button'

export function PlanCard({
  plan,
  current = false,
  busy = false,
  onBuy,
}: {
  plan: Plan
  current?: boolean
  busy?: boolean
  onBuy: (planCode: string) => void
}) {
  const { t, tPlural, lang } = useT()

  const traffic =
    plan.traffic_limit_bytes === null
      ? t('plans.unlimitedTraffic')
      : t('plans.trafficPerMonth', { amount: formatBytes(plan.traffic_limit_bytes, lang) })

  return (
    <div className="mb-3 rounded-xl bg-tg-section-bg p-4">
      <div className="mb-1 flex items-start justify-between gap-3">
        <h3 className="text-lg font-semibold text-tg-text">{plan.name}</h3>
        {current && <Badge tone="success">{t('plans.current')}</Badge>}
      </div>

      <p className="mb-3 text-[15px] leading-snug text-tg-hint">{plan.description}</p>

      <ul className="mb-4 space-y-1 text-[15px] text-tg-text">
        <li>· {tPlural('unit.day', plan.duration_days)}</li>
        <li>· {tPlural('unit.device', plan.device_limit)}</li>
        <li>· {traffic}</li>
      </ul>

      {!current && (
        <Button loading={busy} onClick={() => onBuy(plan.code)}>
          {t('plans.buy', { price: formatMoney(plan.price_amount, plan.currency, lang) })}
        </Button>
      )}
    </div>
  )
}
```

`src/screens/Plans/TrialCard.tsx`:

```tsx
import type { Plan } from '../../api/types'
import { useT } from '../../i18n/useT'
import { formatBytes } from '../../lib/format'
import { Button } from '../../ui/Button'

export function TrialCard({
  plan,
  available,
  busy,
  onStart,
}: {
  plan: Plan
  available: boolean
  busy: boolean
  onStart: () => void
}) {
  const { t, tPlural, lang } = useT()

  return (
    <div className="mb-4 rounded-xl border border-tg-button/40 bg-tg-section-bg p-4">
      <h3 className="mb-1 text-lg font-semibold text-tg-text">{t('plans.trialTitle')}</h3>
      <p className="mb-4 text-[15px] leading-snug text-tg-hint">
        {t('plans.trialBody', {
          days: tPlural('unit.day', plan.duration_days),
          traffic:
            plan.traffic_limit_bytes === null
              ? t('plans.unlimitedTraffic')
              : formatBytes(plan.traffic_limit_bytes, lang),
        })}
      </p>

      {available ? (
        <Button loading={busy} onClick={onStart}>
          {t('plans.trialStart')}
        </Button>
      ) : (
        <p className="text-[15px] text-tg-hint">{t('plans.trialUsed')}</p>
      )}
    </div>
  )
}
```

- [ ] **Шаг 6: Реализовать экран**

`src/screens/Plans/PlansScreen.tsx`:

```tsx
import { useMe, usePlans, useStartTrial, useSubscription } from '../../api/hooks'
import { TRIAL_PREVIEW } from './trialPreview'
import { useT } from '../../i18n/useT'
import { isLive } from '../../lib/subscription'
import { ErrorState } from '../../ui/ErrorState'
import { Skeleton } from '../../ui/Skeleton'
import { PlanCard } from './PlanCard'
import { TrialCard } from './TrialCard'
import { useBuyPlan } from './useBuyPlan'

export default function PlansScreen() {
  const { t } = useT()
  const plans = usePlans()
  const me = useMe()
  const subscription = useSubscription()
  const startTrial = useStartTrial()
  const { buy, state: buyState } = useBuyPlan()

  if (plans.isPending || me.isPending || subscription.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-7 w-1/3" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    )
  }

  if (plans.isError) {
    return <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
  }

  const activePlanCode = isLive(subscription.data ?? null)
    ? subscription.data!.plan.code
    : null

  // Пробный период предлагается только тому, у кого нет действующей подписки:
  // предлагать trial поверх оплаченного тарифа бессмысленно.
  const showTrial = !isLive(subscription.data ?? null)

  return (
    <div className="p-4">
      <h1 className="mb-1 text-2xl font-bold text-tg-text">{t('plans.title')}</h1>
      <p className="mb-5 text-[15px] text-tg-hint">{t('plans.subtitle')}</p>

      {showTrial && (
        <TrialCard
          plan={TRIAL_PREVIEW}
          available={me.data!.trial_available}
          busy={startTrial.isPending}
          onStart={() => startTrial.mutate()}
        />
      )}

      {plans.data!.length === 0 && (
        <p className="py-8 text-center text-[15px] text-tg-hint">{t('plans.empty')}</p>
      )}

      {plans.data!.map((plan) => (
        <PlanCard
          key={plan.code}
          plan={plan}
          current={plan.code === activePlanCode}
          busy={buyState === 'opening'}
          onBuy={buy}
        />
      ))}

      {buyState === 'opened' && (
        <p className="mt-2 rounded-xl bg-tg-section-bg p-4 text-[15px] leading-snug text-tg-hint">
          {t('checkout.hint')}
        </p>
      )}

      {buyState === 'failed' && (
        <p className="mt-2 rounded-xl bg-tg-section-bg p-4 text-[15px] text-tg-destructive">
          {t('checkout.failed')}
        </p>
      )}

      {startTrial.isError && (
        <p className="mt-2 rounded-xl bg-tg-section-bg p-4 text-[15px] text-tg-destructive">
          {t(startTrial.error.messageKey())}
        </p>
      )}
    </div>
  )
}
```

`src/screens/Plans/trialPreview.ts` — параметры trial показываются до его
активации, а API их отдельно не отдаёт (скрытый тариф в каталог не попадает):

```ts
import type { Plan } from '../../api/types'

/**
 * Витрина пробного периода. Значения дублируют settings.trial_days и
 * settings.trial_traffic_bytes на бэкенде. Когда появится
 * GET /tma/trial-preview — заменить на данные ответа.
 */
export const TRIAL_PREVIEW: Plan = {
  code: 'trial',
  name: 'Пробный период',
  description: '',
  duration_days: 3,
  device_limit: 1,
  traffic_limit_bytes: 5 * 1024 ** 3,
  speed_limit_kbps: null,
  price_amount: 0,
  currency: 'RUB',
  is_trial: true,
  sort_order: 0,
}
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/screens/Plans`
Expected: 12 passed.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/screens/Plans frontend/tma/src/telegram/links.ts
git commit -m "feat(tma): plans screen with trial activation and checkout handoff"
```

---

### Задача 15: Экран подписки

Главный экран. Отвечает на три вопроса, ради которых клиент открывает
приложение: работает ли VPN, до какого числа и сколько осталось трафика.

Отдельного внимания требует `cancelled`: подписка с выключенным автопродлением
работает до `expires_at`, и показывать её как отключённую — ошибка, стоящая
возвратов.

**Files:**
- Modify: `frontend/tma/src/screens/Subscription/SubscriptionScreen.tsx`
- Create: `frontend/tma/src/screens/Subscription/StatusHeader.tsx`
- Create: `frontend/tma/src/screens/Subscription/TrafficCard.tsx`
- Create: `frontend/tma/src/screens/Subscription/SubscriptionScreen.test.tsx`

**Interfaces:**
- Consumes: `useSubscription`, `useDevices`, `isLive`, `daysLeft`,
  `trafficPercent`, `statusMessageKey`, `formatBytes`, `formatDate`,
  `Section`, `Cell`, `Badge`, `ProgressBar`, `EmptyState`, `ErrorState`
- Produces: `<StatusHeader subscription>`, `<TrafficCard subscription>`

- [ ] **Шаг 1: Написать падающие тесты**

`src/screens/Subscription/SubscriptionScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMockClient } from '../../api/mock/client'
import { resetStore, setFault, setLatency } from '../../api/mock/store'
import type { Subscription } from '../../api/types'
import { renderWithProviders } from '../../test/renderWithProviders'
import SubscriptionScreen from './SubscriptionScreen'
import { TrafficCard } from './TrafficCard'

beforeEach(() => {
  sessionStorage.clear()
  setLatency(0)
  setFault('none')
})

function show() {
  return renderWithProviders(<SubscriptionScreen />, { client: createMockClient() })
}

/** Безлимитная подписка: такого сценария в моке нет, собираем вручную. */
function unlimitedSubscription(): Subscription {
  const now = Date.now()
  const plan = {
    code: 'month_6',
    name: 'Полгода',
    description: '',
    duration_days: 180,
    device_limit: 5,
    traffic_limit_bytes: null,
    speed_limit_kbps: null,
    price_amount: 149900,
    currency: 'RUB',
    is_trial: false,
    sort_order: 20,
  }

  return {
    id: 'sub_unlimited',
    plan,
    status: 'active',
    started_at: new Date(now).toISOString(),
    expires_at: new Date(now + 180 * 86_400_000).toISOString(),
    traffic_used_bytes: 91 * 1024 ** 3,
    traffic_limit_bytes: null,
    traffic_period_start: new Date(now).toISOString(),
    device_limit: 5,
    devices_used: 1,
    auto_renew: true,
  }
}

describe('SubscriptionScreen', () => {
  it('без подписки предлагает выбрать тариф', async () => {
    resetStore('new_user')
    show()
    await waitFor(() => expect(screen.getByText('Подписки нет')).toBeVisible())
    expect(screen.getByRole('link', { name: 'Выбрать тариф' })).toBeVisible()
  })

  it('активная подписка показывает статус и дату окончания', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('Активна')).toBeVisible())
    expect(screen.getByText(/Действует до/)).toBeVisible()
  })

  it('показывает потраченный трафик и процент', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText(/34 ГБ из 200 ГБ/)).toBeVisible())
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '17')
  })

  it('безлимит показывается словами и без полосы прогресса', () => {
    // Ни один сценарий мока не даёт безлимитный тариф с подпиской, поэтому
    // карточка проверяется напрямую: это её собственное поведение.
    renderWithProviders(<TrafficCard subscription={unlimitedSubscription()} />)
    expect(screen.getByText('Без ограничений')).toBeVisible()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('cancelled показан как действующая подписка, а не как отключённая', async () => {
    resetStore('cancelled')
    show()
    await waitFor(() =>
      expect(screen.getByText('Активна до конца периода')).toBeVisible(),
    )
    expect(screen.getByText('Автопродление отключено')).toBeVisible()
    // Ключевая проверка: доступ не подан как утраченный
    expect(screen.queryByText('Подписки нет')).toBeNull()
  })

  it('истекающая подписка показывает остаток дней', async () => {
    resetStore('expiring_soon')
    show()
    await waitFor(() => expect(screen.getByText(/осталось 2 дня/)).toBeVisible())
  })

  it('исчерпанный трафик показан красным и с полной полосой', async () => {
    resetStore('exhausted')
    show()
    await waitFor(() => expect(screen.getByText('Трафик исчерпан')).toBeVisible())
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })

  it('истёкшая подписка предлагает возобновить', async () => {
    resetStore('expired')
    show()
    await waitFor(() => expect(screen.getByText('Истекла')).toBeVisible())
    expect(screen.getByRole('link', { name: 'Возобновить' })).toBeVisible()
  })

  it('показывает счётчик устройств', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('Устройства: 2 из 3')).toBeVisible())
  })

  it('ошибка загрузки даёт экран ошибки', async () => {
    resetStore('active')
    setFault('node_unavailable')
    show()
    await waitFor(() =>
      expect(screen.getByText('Сервер временно недоступен. Попробуйте позже.')).toBeVisible(),
    )
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/screens/Subscription`
Expected: FAIL — заглушка выводит только заголовок.

- [ ] **Шаг 3: Реализовать шапку статуса**

`src/screens/Subscription/StatusHeader.tsx`:

```tsx
import type { Subscription } from '../../api/types'
import { useT } from '../../i18n/useT'
import { formatDate } from '../../lib/format'
import { daysLeft, isLive, statusMessageKey } from '../../lib/subscription'
import { Badge } from '../../ui/Badge'

const TONE_BY_STATUS = {
  trial: 'success',
  active: 'success',
  cancelled: 'warning',
  pending_payment: 'warning',
  expired: 'danger',
  exhausted: 'danger',
  blocked: 'danger',
} as const

export function StatusHeader({ subscription }: { subscription: Subscription }) {
  const { t, tPlural, lang } = useT()
  const left = daysLeft(subscription)
  const live = isLive(subscription)

  return (
    <header className="mb-6 rounded-xl bg-tg-section-bg p-5 text-center">
      <div className="mb-3 flex justify-center">
        <Badge tone={TONE_BY_STATUS[subscription.status]}>
          {t(statusMessageKey(subscription))}
        </Badge>
      </div>

      <h1 className="mb-1 text-2xl font-bold text-tg-text">{subscription.plan.name}</h1>

      {subscription.expires_at && (
        <p className="text-[15px] text-tg-hint">
          {live
            ? t('subscription.expiresOn', { date: formatDate(subscription.expires_at, lang) })
            : t('subscription.expiredOn', { date: formatDate(subscription.expires_at, lang) })}
        </p>
      )}

      {/* Предупреждаем о скором окончании, пока ещё можно что-то сделать. */}
      {live && Number.isFinite(left) && left <= 7 && (
        <p className="mt-1 text-[15px] font-medium text-amber-600 dark:text-amber-400">
          {tPlural('unit.dayLeft', left)}
        </p>
      )}

      <p className="mt-3 text-[13px] text-tg-hint">
        {subscription.auto_renew
          ? t('subscription.autoRenewOn')
          : t('subscription.autoRenewOff')}
      </p>
    </header>
  )
}
```

- [ ] **Шаг 4: Реализовать карточку трафика**

`src/screens/Subscription/TrafficCard.tsx`:

```tsx
import type { Subscription } from '../../api/types'
import { useT } from '../../i18n/useT'
import { formatBytes } from '../../lib/format'
import { trafficPercent } from '../../lib/subscription'
import { ProgressBar } from '../../ui/ProgressBar'
import { Section } from '../../ui/Section'

export function TrafficCard({ subscription }: { subscription: Subscription }) {
  const { t, lang } = useT()
  const percent = trafficPercent(subscription)

  return (
    <Section title={t('subscription.traffic')}>
      <div className="p-4">
        {percent === null ? (
          <p className="text-[15px] text-tg-text">{t('subscription.trafficUnlimited')}</p>
        ) : (
          <>
            <p className="mb-2 text-[15px] text-tg-text">
              {t('subscription.trafficUsed', {
                used: formatBytes(subscription.traffic_used_bytes, lang),
                limit: formatBytes(subscription.traffic_limit_bytes!, lang),
              })}
            </p>
            <ProgressBar
              percent={percent}
              tone={percent >= 95 ? 'danger' : percent >= 80 ? 'warning' : 'normal'}
            />
          </>
        )}
      </div>
    </Section>
  )
}
```

- [ ] **Шаг 5: Реализовать экран**

`src/screens/Subscription/SubscriptionScreen.tsx`:

```tsx
import { Link } from 'react-router'
import { useSubscription } from '../../api/hooks'
import { ROUTES } from '../../app/router'
import { useT } from '../../i18n/useT'
import { isLive } from '../../lib/subscription'
import { EmptyState } from '../../ui/EmptyState'
import { ErrorState } from '../../ui/ErrorState'
import { Cell } from '../../ui/Cell'
import { Section } from '../../ui/Section'
import { Skeleton } from '../../ui/Skeleton'
import { StatusHeader } from './StatusHeader'
import { TrafficCard } from './TrafficCard'

/** Кнопка-ссылка: переход внутри приложения не должен выглядеть как <button>. */
function LinkButton({ to, children }: { to: string; children: string }) {
  return (
    <Link
      to={to}
      className="block w-full rounded-xl bg-tg-button px-4 py-3.5 text-center text-base font-medium text-tg-button-text active:opacity-70"
    >
      {children}
    </Link>
  )
}

export default function SubscriptionScreen() {
  const { t } = useT()
  const subscription = useSubscription()

  if (subscription.isPending) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    )
  }

  if (subscription.isError) {
    return (
      <ErrorState error={subscription.error} onRetry={() => void subscription.refetch()} />
    )
  }

  const sub = subscription.data

  if (!sub) {
    return (
      <EmptyState
        icon="🔒"
        title={t('subscription.none')}
        body={t('subscription.noneBody')}
        action={<LinkButton to={ROUTES.plans}>{t('subscription.choosePlan')}</LinkButton>}
      />
    )
  }

  return (
    <div className="p-4">
      <StatusHeader subscription={sub} />
      <TrafficCard subscription={sub} />

      <Section>
        <Cell
          title={t('subscription.devicesUsed', {
            used: sub.devices_used,
            limit: sub.device_limit,
          })}
          right="›"
          onClick={() => {
            window.location.assign(ROUTES.devices)
          }}
        />
      </Section>

      {/* Истекла или исчерпана — единственное осмысленное действие — оплата. */}
      {!isLive(sub) && (
        <LinkButton to={ROUTES.plans}>{t('subscription.renew')}</LinkButton>
      )}

      {isLive(sub) && !sub.auto_renew && (
        <LinkButton to={ROUTES.plans}>{t('subscription.extend')}</LinkButton>
      )}
    </div>
  )
}
```

Переход в устройства через `window.location.assign` — временное решение
Задачи 15: `Cell` принимает `onClick`, а не `to`. В Задаче 16 добавляется
вариант `Cell` со ссылкой, и этот вызов заменяется на `<Link>`.

- [ ] **Шаг 6: Убедиться, что тесты проходят**

Run: `npm test -- src/screens/Subscription`
Expected: 10 passed.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma/src/screens/Subscription
git commit -m "feat(tma): subscription screen with status, traffic and expiry"
```

---

### Задача 16: Экран устройств — список и отзыв

Список выпущенных ключей с их состоянием и потреблением. Отзыв необратим, и
это единственное действие в приложении, требующее подтверждения.

**Files:**
- Modify: `frontend/tma/src/screens/Devices/DevicesScreen.tsx`
- Create: `frontend/tma/src/screens/Devices/DeviceRow.tsx`
- Create: `frontend/tma/src/screens/Devices/RevokeSheet.tsx`
- Create: `frontend/tma/src/screens/Devices/platform.ts`
- Modify: `frontend/tma/src/ui/Cell.tsx` (добавляется проп `to`)
- Create: `frontend/tma/src/screens/Devices/DevicesScreen.test.tsx`

**Interfaces:**
- Consumes: `useDevices`, `useSubscription`, `useRevokeDevice`, `canIssueDevice`,
  `formatBytes`, `formatDate`, `Sheet`, `Button`, `EmptyState`
- Produces:
  - `PLATFORM_ICON: Record<Platform, string>`, `PLATFORM_LABEL: Record<Platform, string>`
  - `<DeviceRow device onRevoke>`, `<RevokeSheet device onConfirm onClose busy>`
  - `<Cell to>` — ячейка-ссылка

- [ ] **Шаг 1: Написать падающие тесты**

`src/screens/Devices/DevicesScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMockClient } from '../../api/mock/client'
import { resetStore, setFault, setLatency } from '../../api/mock/store'
import { renderWithProviders } from '../../test/renderWithProviders'
import DevicesScreen from './DevicesScreen'

beforeEach(() => {
  sessionStorage.clear()
  setLatency(0)
  setFault('none')
})

function show() {
  return renderWithProviders(<DevicesScreen />, { client: createMockClient() })
}

describe('DevicesScreen', () => {
  it('пустой список объясняет, что делать', async () => {
    resetStore('new_user')
    show()
    await waitFor(() => expect(screen.getByText('Устройств пока нет')).toBeVisible())
  })

  it('выводит устройства с платформой и трафиком', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('iPhone Ивана')).toBeVisible())
    expect(screen.getByText('MacBook')).toBeVisible()
    expect(screen.getByText(/12 ГБ/)).toBeVisible()
  })

  it('онлайн-устройство помечено', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('Подключено')).toBeVisible())
  })

  it('устройство без подключений подписано отдельно', async () => {
    resetStore('device_limit')
    show()
    await waitFor(() => expect(screen.getByText('Ни разу не подключалось')).toBeVisible())
  })

  it('кнопка добавления доступна, пока есть свободные слоты', async () => {
    resetStore('active')
    show()
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Добавить устройство' })).toBeVisible(),
    )
  })

  it('при выбранном лимите вместо кнопки — объяснение', async () => {
    resetStore('device_limit')
    show()
    await waitFor(() =>
      expect(screen.getByText('Достигнут лимит устройств тарифа')).toBeVisible(),
    )
    expect(screen.queryByRole('link', { name: 'Добавить устройство' })).toBeNull()
  })

  it('на неактивной подписке добавление недоступно', async () => {
    resetStore('expired')
    show()
    await waitFor(() => expect(screen.getByText('Устройств пока нет')).toBeVisible())
    expect(screen.queryByRole('link', { name: 'Добавить устройство' })).toBeNull()
  })

  it('отзыв требует подтверждения и называет устройство', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('iPhone Ивана')).toBeVisible())
    await userEvent.click(screen.getAllByRole('button', { name: 'Отозвать' })[0])

    expect(screen.getByRole('dialog')).toBeVisible()
    expect(screen.getByText(/«iPhone Ивана» перестанет работать/)).toBeVisible()
  })

  it('отмена в подтверждении не отзывает устройство', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('iPhone Ивана')).toBeVisible())
    await userEvent.click(screen.getAllByRole('button', { name: 'Отозвать' })[0])
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }))

    expect(screen.getByText('iPhone Ивана')).toBeVisible()
  })

  it('подтверждение убирает устройство из списка', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('iPhone Ивана')).toBeVisible())
    await userEvent.click(screen.getAllByRole('button', { name: 'Отозвать' })[0])
    await userEvent.click(
      screen.getByRole('button', { name: 'Отозвать устройство' }),
    )

    await waitFor(() => expect(screen.queryByText('iPhone Ивана')).toBeNull())
    expect(screen.getByText('MacBook')).toBeVisible()
  })

  it('ошибка отзыва показывается, устройство остаётся', async () => {
    resetStore('active')
    show()
    await waitFor(() => expect(screen.getByText('iPhone Ивана')).toBeVisible())
    await userEvent.click(screen.getAllByRole('button', { name: 'Отозвать' })[0])
    setFault('internal')
    await userEvent.click(screen.getByRole('button', { name: 'Отозвать устройство' }))

    await waitFor(() =>
      expect(screen.getByText('Внутренняя ошибка сервера.')).toBeVisible(),
    )
    expect(screen.getByText('iPhone Ивана')).toBeVisible()
  })
})
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `npm test -- src/screens/Devices`
Expected: FAIL — заглушка выводит только заголовок.

- [ ] **Шаг 3: Добавить `Cell` со ссылкой**

В `src/ui/Cell.tsx` добавить проп `to` и ветку рендера:

```tsx
import { Link } from 'react-router'

// …внутри Cell, перед веткой onClick:
if (to) {
  return (
    <Link to={to} className={`${shared} active:bg-tg-secondary-bg`} onClick={() => haptic.selection()}>
      {body}
    </Link>
  )
}
```

Сигнатура пропсов дополняется `to?: string`. После этого в
`SubscriptionScreen.tsx` заменить `onClick={() => window.location.assign(...)}`
на `to={ROUTES.devices}`.

- [ ] **Шаг 4: Реализовать словарь платформ**

`src/screens/Devices/platform.ts`:

```ts
import type { Platform } from '../../api/types'

export const PLATFORM_ICON: Record<Platform, string> = {
  ios: '📱',
  android: '🤖',
  windows: '🪟',
  macos: '💻',
  linux: '🐧',
}

/** Названия ОС — имена собственные, они одинаковы в обеих локалях. */
export const PLATFORM_LABEL: Record<Platform, string> = {
  ios: 'iOS',
  android: 'Android',
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
}

export const PLATFORMS: readonly Platform[] = [
  'ios',
  'android',
  'windows',
  'macos',
  'linux',
]
```

- [ ] **Шаг 5: Реализовать строку устройства и лист подтверждения**

`src/screens/Devices/DeviceRow.tsx`:

```tsx
import type { Device } from '../../api/types'
import { useT } from '../../i18n/useT'
import { formatBytes, formatDate } from '../../lib/format'
import { Badge } from '../../ui/Badge'
import { PLATFORM_ICON, PLATFORM_LABEL } from './platform'

export function DeviceRow({
  device,
  onRevoke,
}: {
  device: Device
  onRevoke: (device: Device) => void
}) {
  const { t, lang } = useT()

  return (
    <div className="border-b border-tg-separator px-4 py-3 last:border-b-0">
      <div className="flex items-start gap-3">
        <span className="text-2xl" aria-hidden="true">
          {PLATFORM_ICON[device.platform]}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-base text-tg-text">{device.name}</span>
            {device.is_online && <Badge tone="success">{t('devices.online')}</Badge>}
          </div>

          <p className="mt-0.5 text-[13px] text-tg-hint">
            {PLATFORM_LABEL[device.platform]} · {formatBytes(device.traffic_used_bytes, lang)}
          </p>

          <p className="text-[13px] text-tg-hint">
            {device.last_seen_at
              ? t('devices.lastSeen', { when: formatDate(device.last_seen_at, lang) })
              : t('devices.neverConnected')}
          </p>
        </div>

        <button
          type="button"
          onClick={() => onRevoke(device)}
          className="shrink-0 text-[15px] text-tg-destructive active:opacity-60"
        >
          {t('devices.revoke')}
        </button>
      </div>
    </div>
  )
}
```

`src/screens/Devices/RevokeSheet.tsx`:

```tsx
import type { Device } from '../../api/types'
import { useT } from '../../i18n/useT'
import { Button } from '../../ui/Button'
import { Sheet } from '../../ui/Sheet'

export function RevokeSheet({
  device,
  busy,
  onConfirm,
  onClose,
}: {
  device: Device | null
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useT()

  return (
    <Sheet open={device !== null} onClose={onClose} title={t('devices.revokeTitle')}>
      {device && (
        <>
          <p className="mb-5 text-center text-[15px] leading-snug text-tg-hint">
            {t('devices.revokeBody', { name: device.name })}
          </p>
          <div className="space-y-2">
            <Button variant="destructive" loading={busy} onClick={onConfirm}>
              {t('devices.revokeConfirm')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel')}
            </Button>
          </div>
        </>
      )}
    </Sheet>
  )
}
```

Подпись кнопки — отдельный ключ, а не склейка двух других: склеенная фраза
разваливается во втором языке. Добавить в оба каталога:
`'devices.revokeConfirm': 'Отозвать устройство'` в `ru.ts` и
`'devices.revokeConfirm': 'Revoke device'` в `en.ts`.

- [ ] **Шаг 6: Реализовать экран**

`src/screens/Devices/DevicesScreen.tsx`:

```tsx
import { useState } from 'react'
import { Link } from 'react-router'
import { useDevices, useRevokeDevice, useSubscription } from '../../api/hooks'
import { ROUTES } from '../../app/router'
import type { Device } from '../../api/types'
import { useT } from '../../i18n/useT'
import { canIssueDevice, isLive } from '../../lib/subscription'
import { EmptyState } from '../../ui/EmptyState'
import { ErrorState } from '../../ui/ErrorState'
import { Section } from '../../ui/Section'
import { Skeleton } from '../../ui/Skeleton'
import { DeviceRow } from './DeviceRow'
import { RevokeSheet } from './RevokeSheet'

export default function DevicesScreen() {
  const { t } = useT()
  const devices = useDevices()
  const subscription = useSubscription()
  const revoke = useRevokeDevice()
  const [pendingRevoke, setPendingRevoke] = useState<Device | null>(null)

  if (devices.isPending || subscription.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-7 w-1/3" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    )
  }

  if (devices.isError) {
    return <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
  }

  const sub = subscription.data ?? null
  const canAdd = canIssueDevice(sub)
  const limitReached = isLive(sub) && !canAdd

  const addButton = canAdd ? (
    <Link
      to={ROUTES.deviceNew}
      className="block w-full rounded-xl bg-tg-button px-4 py-3.5 text-center text-base font-medium text-tg-button-text active:opacity-70"
    >
      {t('devices.add')}
    </Link>
  ) : null

  return (
    <div className="p-4">
      <h1 className="mb-4 text-2xl font-bold text-tg-text">{t('devices.title')}</h1>

      {devices.data!.length === 0 ? (
        <EmptyState
          icon="📱"
          title={t('devices.empty')}
          body={t('devices.emptyBody')}
          action={addButton}
        />
      ) : (
        <>
          <Section>
            {devices.data!.map((device) => (
              <DeviceRow key={device.id} device={device} onRevoke={setPendingRevoke} />
            ))}
          </Section>

          {addButton}
          {limitReached && (
            <p className="mt-2 text-center text-[15px] text-tg-hint">
              {t('devices.limitReached')}
            </p>
          )}
        </>
      )}

      {revoke.isError && (
        <p className="mt-3 rounded-xl bg-tg-section-bg p-4 text-[15px] text-tg-destructive">
          {t(revoke.error.messageKey())}
        </p>
      )}

      <RevokeSheet
        device={pendingRevoke}
        busy={revoke.isPending}
        onClose={() => setPendingRevoke(null)}
        onConfirm={() => {
          if (!pendingRevoke) return
          revoke.mutate(pendingRevoke.id, {
            // Лист закрывается в любом случае: ошибка показывается на экране,
            // иначе клиент остаётся в модалке без объяснения.
            onSettled: () => setPendingRevoke(null),
          })
        }}
      />
    </div>
  )
}
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

Run: `npm test -- src/screens/Devices`
Expected: 11 passed.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma/src/screens/Devices frontend/tma/src/ui/Cell.tsx frontend/tma/src/i18n
git commit -m "feat(tma): devices list with online state and confirmed revocation"
```

---

### Задача 17: Выпуск устройства и одноразовая выдача ключа

Два экрана одной цепочки: выбор ОС и имени → выпуск → показ пароля и ссылки.
Второй экран особенный: он показывает данные, которых больше нигде нет и
которые нельзя восстановить. Отсюда жёсткие требования — секрет не попадает
ни в URL, ни в `history.state`, ни в кэш React Query, ни в `localStorage`, а
экран, открытый без секрета, уводит клиента обратно, а не показывает пустоту.

**Files:**
- Create: `frontend/tma/src/lib/clipboard.ts`
- Create: `frontend/tma/src/ui/QrCode.tsx`
- Create: `frontend/tma/src/ui/CopyField.tsx`
- Create: `frontend/tma/src/screens/DeviceSecret/secretVault.ts`
- Modify: `frontend/tma/src/screens/DeviceCreate/DeviceCreateScreen.tsx`
- Modify: `frontend/tma/src/screens/DeviceSecret/DeviceSecretScreen.tsx`
- Create: `frontend/tma/src/screens/DeviceCreate/DeviceCreateScreen.test.tsx`
- Create: `frontend/tma/src/screens/DeviceSecret/DeviceSecretScreen.test.tsx`

**Interfaces:**
- Consumes: `useCreateDevice`, `useSubscription`, `useBackButton`, `PLATFORMS`,
  `PLATFORM_ICON`, `PLATFORM_LABEL`, `formatCountdown`
- Produces:
  - `copyToClipboard(text: string): Promise<boolean>`
  - `<QrCode value size?>`, `<CopyField label value mono?>`
  - `stashIssued(v: IssuedDevice)`, `peekIssued(): IssuedDevice | null`, `clearIssued()`

- [ ] **Шаг 1: Написать падающие тесты экрана выпуска**

`src/screens/DeviceCreate/DeviceCreateScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockClient } from '../../api/mock/client'
import { resetStore, setFault, setLatency } from '../../api/mock/store'
import { peekIssued } from '../DeviceSecret/secretVault'
import { renderWithProviders } from '../../test/renderWithProviders'
import DeviceCreateScreen from './DeviceCreateScreen'

const navigate = vi.hoisted(() => vi.fn())
vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => navigate }
})

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
  setFault('none')
  navigate.mockClear()
})

function show() {
  return renderWithProviders(<DeviceCreateScreen />, { client: createMockClient() })
}

describe('DeviceCreateScreen', () => {
  it('предлагает все пять платформ', async () => {
    show()
    for (const label of ['iOS', 'Android', 'Windows', 'macOS', 'Linux']) {
      expect(await screen.findByRole('radio', { name: new RegExp(label) })).toBeVisible()
    }
  })

  it('кнопка выпуска заблокирована, пока не выбрана ОС', async () => {
    show()
    expect(await screen.findByRole('button', { name: 'Выпустить ключ' })).toBeDisabled()
  })

  it('после выбора ОС имя подставляется автоматически', async () => {
    show()
    await userEvent.click(await screen.findByRole('radio', { name: /iOS/ }))
    expect(screen.getByLabelText('Название')).toHaveValue('iOS')
  })

  it('пустое имя не даёт выпустить ключ', async () => {
    show()
    await userEvent.click(await screen.findByRole('radio', { name: /iOS/ }))
    await userEvent.clear(screen.getByLabelText('Название'))
    expect(screen.getByRole('button', { name: 'Выпустить ключ' })).toBeDisabled()
  })

  it('успешный выпуск кладёт секрет в хранилище и уводит на экран ключа', async () => {
    show()
    await userEvent.click(await screen.findByRole('radio', { name: /Android/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Выпустить ключ' }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/devices/secret', { replace: true }))
    expect(peekIssued()?.p12_password).toMatch(/^[A-Za-z0-9]{12}$/)
  })

  it('лимит устройств показывается сообщением, а не пустым экраном', async () => {
    resetStore('device_limit')
    show()
    await waitFor(() =>
      expect(screen.getByText('Достигнут лимит устройств тарифа')).toBeVisible(),
    )
    expect(screen.queryByRole('button', { name: 'Выпустить ключ' })).toBeNull()
  })

  it('ошибка выпуска показывается и не уводит с экрана', async () => {
    show()
    await userEvent.click(await screen.findByRole('radio', { name: /iOS/ }))
    setFault('node_unavailable')
    await userEvent.click(screen.getByRole('button', { name: 'Выпустить ключ' }))

    await waitFor(() =>
      expect(screen.getByText('Сервер временно недоступен. Попробуйте позже.')).toBeVisible(),
    )
    expect(navigate).not.toHaveBeenCalled()
  })
})
```

- [ ] **Шаг 2: Написать падающие тесты экрана ключа**

`src/screens/DeviceSecret/DeviceSecretScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IssuedDevice } from '../../api/types'
import { renderWithProviders } from '../../test/renderWithProviders'
import DeviceSecretScreen from './DeviceSecretScreen'
import { clearIssued, stashIssued } from './secretVault'

const navigate = vi.hoisted(() => vi.fn())
vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,QR') },
}))

function issued(over: Partial<IssuedDevice> = {}): IssuedDevice {
  return {
    device: {
      id: 'dev_9',
      name: 'iPhone',
      platform: 'ios',
      issued_at: new Date().toISOString(),
      cert_expires_at: new Date(Date.now() + 397 * 86_400_000).toISOString(),
      last_seen_at: null,
      is_online: false,
      traffic_used_bytes: 0,
    },
    p12_password: 'AbCdEfGhJkLm',
    download_url: 'https://app.example.com/download/abc',
    download_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    ...over,
  }
}

beforeEach(() => {
  navigate.mockClear()
  clearIssued()
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

afterEach(() => {
  clearIssued()
  vi.useRealTimers()
})

describe('DeviceSecretScreen', () => {
  it('без секрета уводит на список устройств, а не показывает пустоту', async () => {
    renderWithProviders(<DeviceSecretScreen />)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/devices', { replace: true }))
  })

  it('показывает пароль и предупреждение о единственном показе', async () => {
    stashIssued(issued())
    renderWithProviders(<DeviceSecretScreen />)
    expect(screen.getByText('AbCdEfGhJkLm')).toBeVisible()
    expect(screen.getByText(/показываются один раз/)).toBeVisible()
  })

  it('пароль копируется в буфер обмена', async () => {
    stashIssued(issued())
    renderWithProviders(<DeviceSecretScreen />)
    await userEvent.click(screen.getAllByRole('button', { name: 'Скопировать' })[0])
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('AbCdEfGhJkLm')
    await waitFor(() => expect(screen.getByText('Скопировано')).toBeVisible())
  })

  it('рисует QR со ссылкой на скачивание', async () => {
    stashIssued(issued())
    renderWithProviders(<DeviceSecretScreen />)
    await waitFor(() =>
      expect(screen.getByRole('img', { name: /QR/i })).toHaveAttribute(
        'src',
        'data:image/png;base64,QR',
      ),
    )
  })

  it('показывает обратный отсчёт до истечения ссылки', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    stashIssued(issued({ download_expires_at: new Date(Date.now() + 61_000).toISOString() }))
    renderWithProviders(<DeviceSecretScreen />)
    expect(screen.getByText(/01:0[01]/)).toBeVisible()
  })

  it('по истечении ссылки предлагает выпустить новое устройство', async () => {
    stashIssued(issued({ download_expires_at: new Date(Date.now() - 1000).toISOString() }))
    renderWithProviders(<DeviceSecretScreen />)
    expect(screen.getByText('Ссылка истекла. Выпустите новое устройство.')).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Скачать ключ' })).toBeNull()
  })

  it('секрет не попадает ни в один URL', () => {
    stashIssued(issued())
    renderWithProviders(<DeviceSecretScreen />)
    expect(window.location.href).not.toContain('AbCdEfGhJkLm')
    expect(navigate).not.toHaveBeenCalledWith(expect.stringContaining('AbCdEfGhJkLm'))
  })

  it('уход с экрана стирает секрет из памяти', async () => {
    stashIssued(issued())
    const { unmount } = renderWithProviders(<DeviceSecretScreen />)
    unmount()
    const { peekIssued } = await import('./secretVault')
    expect(peekIssued()).toBeNull()
  })
})
```

- [ ] **Шаг 3: Убедиться, что оба набора падают**

Run: `npm test -- src/screens/DeviceCreate src/screens/DeviceSecret`
Expected: FAIL — заглушки и отсутствующие модули.

- [ ] **Шаг 4: Реализовать буфер обмена, QR и поле с копированием**

`src/lib/clipboard.ts`:

```ts
/**
 * Возвращает false вместо исключения: копирование — удобство, а не
 * обязательное условие, и его отказ не должен ломать экран.
 * В Telegram на iOS Clipboard API доступен только по жесту пользователя.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
```

`src/ui/QrCode.tsx`:

```tsx
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'

export function QrCode({
  value,
  size = 220,
  label,
}: {
  value: string
  size?: number
  label: string
}) {
  const [dataUrl, setDataUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    void QRCode.toDataURL(value, {
      width: size,
      margin: 1,
      errorCorrectionLevel: 'M',
      // Фиксированные цвета: QR обязан оставаться контрастным
      // независимо от темы клиента, иначе камера его не прочитает.
      color: { dark: '#000000', light: '#ffffff' },
    }).then((url) => {
      if (!cancelled) setDataUrl(url)
    })

    return () => {
      cancelled = true
    }
  }, [value, size])

  if (!dataUrl) {
    return (
      <div
        className="animate-pulse rounded-lg bg-tg-secondary-bg"
        style={{ width: size, height: size }}
        aria-hidden="true"
      />
    )
  }

  return (
    <img
      src={dataUrl}
      alt={label}
      width={size}
      height={size}
      className="rounded-lg bg-white p-2"
    />
  )
}
```

`src/ui/CopyField.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useT } from '../i18n/useT'
import { copyToClipboard } from '../lib/clipboard'
import { haptic } from '../telegram/haptics'

export function CopyField({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  const { t } = useT()
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(timer)
  }, [copied])

  return (
    <div className="rounded-xl bg-tg-section-bg p-4">
      <p className="mb-1 text-[13px] text-tg-hint">{label}</p>
      <div className="flex items-center gap-3">
        <span
          className={`min-w-0 flex-1 break-all text-base text-tg-text ${mono ? 'font-mono' : ''}`}
        >
          {value}
        </span>
        <button
          type="button"
          className="shrink-0 text-[15px] text-tg-link active:opacity-60"
          onClick={() => {
            void copyToClipboard(value).then((ok) => {
              if (!ok) return
              haptic.notification('success')
              setCopied(true)
            })
          }}
        >
          {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Шаг 5: Реализовать хранилище секрета**

`src/screens/DeviceSecret/secretVault.ts`:

```ts
import type { IssuedDevice } from '../../api/types'

/**
 * Пароль от .p12 и одноразовая ссылка живут только в памяти модуля.
 *
 * Почему не location.state роутера: history.state сериализуется браузером и
 * переживает перезагрузку страницы. Почему не кэш React Query: он логируется
 * девтулзами и переживает навигацию. Почему не URL: адрес попадает в историю
 * и в логи прокси.
 *
 * peek() намеренно не стирает значение: React в StrictMode рендерит компонент
 * дважды, и стирающее чтение потеряло бы секрет на первом же рендере.
 * Стирание — явное, в эффекте размонтирования экрана.
 */
let held: IssuedDevice | null = null

export function stashIssued(value: IssuedDevice): void {
  held = value
}

export function peekIssued(): IssuedDevice | null {
  return held
}

export function clearIssued(): void {
  held = null
}
```

- [ ] **Шаг 6: Реализовать экран выпуска**

`src/screens/DeviceCreate/DeviceCreateScreen.tsx`:

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useCreateDevice, useSubscription } from '../../api/hooks'
import type { Platform } from '../../api/types'
import { ROUTES } from '../../app/router'
import { useT } from '../../i18n/useT'
import { canIssueDevice } from '../../lib/subscription'
import { useBackButton } from '../../telegram/backButton'
import { Button } from '../../ui/Button'
import { ErrorState } from '../../ui/ErrorState'
import { Skeleton } from '../../ui/Skeleton'
import { PLATFORM_ICON, PLATFORM_LABEL, PLATFORMS } from '../Devices/platform'
import { stashIssued } from '../DeviceSecret/secretVault'

export default function DeviceCreateScreen() {
  const { t } = useT()
  const navigate = useNavigate()
  useBackButton(ROUTES.devices)

  const subscription = useSubscription()
  const createDevice = useCreateDevice()
  const [platform, setPlatform] = useState<Platform | null>(null)
  const [name, setName] = useState('')

  if (subscription.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-7 w-1/2" />
        <Skeleton className="h-56 w-full rounded-xl" />
      </div>
    )
  }

  if (subscription.isError) {
    return (
      <ErrorState error={subscription.error} onRetry={() => void subscription.refetch()} />
    )
  }

  const allowed = canIssueDevice(subscription.data ?? null)

  const submit = () => {
    if (!platform || !name.trim()) return
    createDevice.mutate(
      { name: name.trim(), platform },
      {
        onSuccess: (issued) => {
          // Секрет уходит в память модуля, а не в URL и не в state роутера.
          stashIssued(issued)
          // replace: возврат «назад» не должен вести на форму выпуска.
          void navigate(ROUTES.deviceSecret, { replace: true })
        },
      },
    )
  }

  return (
    <div className="p-4">
      <h1 className="mb-4 text-2xl font-bold text-tg-text">{t('deviceCreate.title')}</h1>

      {!allowed ? (
        <p className="rounded-xl bg-tg-section-bg p-4 text-center text-[15px] text-tg-hint">
          {t('devices.limitReached')}
        </p>
      ) : (
        <>
          <fieldset className="mb-5">
            <legend className="mb-2 text-[13px] text-tg-hint">
              {t('deviceCreate.pickPlatform')}
            </legend>
            <div className="overflow-hidden rounded-xl bg-tg-section-bg">
              {PLATFORMS.map((value) => (
                <label
                  key={value}
                  className="flex cursor-pointer items-center gap-3 border-b border-tg-separator px-4 py-3 last:border-b-0"
                >
                  <input
                    type="radio"
                    name="platform"
                    value={value}
                    checked={platform === value}
                    onChange={() => {
                      setPlatform(value)
                      // Имя подставляем, только пока клиент его не трогал.
                      if (!name || PLATFORMS.some((p) => PLATFORM_LABEL[p] === name)) {
                        setName(PLATFORM_LABEL[value])
                      }
                    }}
                    className="accent-tg-button"
                  />
                  <span className="text-xl" aria-hidden="true">
                    {PLATFORM_ICON[value]}
                  </span>
                  <span className="text-base text-tg-text">{PLATFORM_LABEL[value]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="mb-5 block">
            <span className="mb-1 block text-[13px] text-tg-hint">
              {t('deviceCreate.name')}
            </span>
            <input
              type="text"
              value={name}
              maxLength={40}
              placeholder={t('deviceCreate.namePlaceholder')}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-xl bg-tg-section-bg px-4 py-3 text-base text-tg-text outline-none"
            />
          </label>

          <Button
            loading={createDevice.isPending}
            disabled={!platform || name.trim().length === 0}
            onClick={submit}
          >
            {createDevice.isPending ? t('deviceCreate.issuing') : t('deviceCreate.submit')}
          </Button>

          {createDevice.isError && (
            <p className="mt-3 rounded-xl bg-tg-section-bg p-4 text-[15px] text-tg-destructive">
              {t(createDevice.error.messageKey())}
            </p>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Шаг 7: Реализовать экран выдачи ключа**

`src/screens/DeviceSecret/DeviceSecretScreen.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ROUTES } from '../../app/router'
import { useT } from '../../i18n/useT'
import { formatCountdown } from '../../lib/format'
import { useBackButton } from '../../telegram/backButton'
import { CopyField } from '../../ui/CopyField'
import { QrCode } from '../../ui/QrCode'
import { clearIssued, peekIssued } from './secretVault'

export default function DeviceSecretScreen() {
  const { t } = useT()
  const navigate = useNavigate()
  useBackButton(ROUTES.devices)

  const [issued] = useState(peekIssued)
  const [msLeft, setMsLeft] = useState(() =>
    issued ? Date.parse(issued.download_expires_at) - Date.now() : 0,
  )

  // Экран открыт напрямую (перезагрузка, вставленная ссылка) — секрета нет.
  useEffect(() => {
    if (!issued) void navigate(ROUTES.devices, { replace: true })
  }, [issued, navigate])

  // Секрет живёт ровно столько, сколько открыт этот экран.
  useEffect(() => clearIssued, [])

  useEffect(() => {
    if (!issued) return
    const expiresAt = Date.parse(issued.download_expires_at)
    const timer = setInterval(() => setMsLeft(expiresAt - Date.now()), 1000)
    return () => clearInterval(timer)
  }, [issued])

  if (!issued) return null

  const expired = msLeft <= 0

  return (
    <div className="p-4">
      <h1 className="mb-2 text-2xl font-bold text-tg-text">{t('deviceSecret.title')}</h1>

      <p className="mb-5 rounded-xl bg-amber-500/10 p-4 text-[15px] leading-snug text-amber-700 dark:text-amber-400">
        {t('deviceSecret.warning')}
      </p>

      <div className="mb-4">
        <CopyField label={t('deviceSecret.password')} value={issued.p12_password} mono />
      </div>

      {expired ? (
        <p className="rounded-xl bg-tg-section-bg p-4 text-center text-[15px] text-tg-destructive">
          {t('deviceSecret.expired')}
        </p>
      ) : (
        <>
          {/* Ссылка одноразовая: открывается напрямую, без предзагрузки. */}
          <a
            href={issued.download_url}
            className="block w-full rounded-xl bg-tg-button px-4 py-3.5 text-center text-base font-medium text-tg-button-text active:opacity-70"
          >
            {t('deviceSecret.download')}
          </a>

          <p className="mt-2 text-center text-[13px] text-tg-hint">
            {t('deviceSecret.expiresIn', { time: formatCountdown(msLeft) })}
          </p>

          <div className="mt-6 flex flex-col items-center">
            <QrCode value={issued.download_url} label="QR" />
            <p className="mt-2 text-center text-[13px] text-tg-hint">
              {t('deviceSecret.qrHint')}
            </p>
          </div>
        </>
      )}

      <Link
        to={ROUTES.instructions(issued.device.platform)}
        className="mt-6 block w-full rounded-xl bg-tg-secondary-bg px-4 py-3.5 text-center text-base font-medium text-tg-text active:opacity-70"
      >
        {t('deviceSecret.next')}
      </Link>
    </div>
  )
}
```

- [ ] **Шаг 8: Убедиться, что тесты проходят**

Run: `npm test -- src/screens/DeviceCreate src/screens/DeviceSecret`
Expected: 15 passed.

- [ ] **Шаг 9: Проверить руками весь путь**

```bash
npm run dev
```

Сценарий `active` → вкладка «Устройства» → «Добавить устройство» → выбрать
iOS → «Выпустить ключ». Проверить: пароль виден, обратный отсчёт идёт, QR
нарисован, адресная строка не содержит пароля, «Назад» ведёт в список, а
повторное открытие `/devices/secret` перекидывает в список.

- [ ] **Шаг 10: Коммит**

```bash
git add frontend/tma/src
git commit -m "feat(tma): device issuance flow with one-time secret delivery"
```

---

### Задача 18: Экран инструкций под операционную систему

Клиент получил `.p12` — дальше ему нужно объяснить, что с ним делать. Тексты
шагов живут в i18n-каталогах (решение №2 из таблицы допущений), параметры
подключения — адрес шлюза с камуфляж-токеном — приходят из API.

**Files:**
- Create: `frontend/tma/src/screens/Instructions/steps.ts`
- Modify: `frontend/tma/src/screens/Instructions/InstructionsScreen.tsx`
- Modify: `frontend/tma/src/i18n/ru.ts`, `frontend/tma/src/i18n/en.ts`
- Create: `frontend/tma/src/screens/Instructions/InstructionsScreen.test.tsx`

**Interfaces:**
- Consumes: `useConnection`, `useParams`, `useBackButton`, `CopyField`,
  `openExternal`, `PLATFORM_LABEL`
- Produces: `STORE_LINKS: Record<Platform, string | null>`,
  `STEP_KEYS: Record<Platform, MessageKey[]>`

- [ ] **Шаг 1: Дописать ключи инструкций в оба каталога**

Двадцать ключей: пять платформ по четыре шага. В `ru.ts`:

```ts
  'instructions.ios.1': 'Установите Cisco Secure Client из App Store',
  'instructions.ios.2':
    'Откройте скачанный файл ключа и введите пароль — iOS предложит установить профиль',
  'instructions.ios.3':
    'Настройки → Основные → VPN и управление устройством → установите профиль',
  'instructions.ios.4':
    'Откройте Cisco Secure Client, добавьте подключение с адресом сервера и включите VPN',

  'instructions.android.1': 'Установите Cisco Secure Client из Google Play',
  'instructions.android.2':
    'В приложении откройте меню → Управление сертификатами → Импорт из файла',
  'instructions.android.3': 'Выберите скачанный файл ключа и введите пароль',
  'instructions.android.4':
    'Добавьте подключение с адресом сервера, выберите импортированный сертификат и включите VPN',

  'instructions.windows.1': 'Установите OpenConnect GUI с официального сайта',
  'instructions.windows.2':
    'Дважды щёлкните по скачанному файлу ключа и введите пароль — Windows положит сертификат в личное хранилище',
  'instructions.windows.3':
    'В OpenConnect GUI создайте профиль, укажите адрес сервера и выберите сертификат из хранилища',
  'instructions.windows.4': 'Нажмите «Подключиться» — соединение установится за пару секунд',

  'instructions.macos.1': 'Установите OpenConnect GUI или Cisco Secure Client',
  'instructions.macos.2':
    'Откройте скачанный файл ключа двойным щелчком и введите пароль — сертификат попадёт в Связку ключей',
  'instructions.macos.3':
    'Создайте профиль с адресом сервера и выберите импортированный сертификат',
  'instructions.macos.4': 'Подключитесь и разрешите системе добавить VPN-конфигурацию',

  'instructions.linux.1':
    'Установите пакет openconnect: apt install openconnect или dnf install openconnect',
  'instructions.linux.2':
    'Распакуйте ключ: openssl pkcs12 -in key.p12 -out key.pem -nodes (спросит пароль)',
  'instructions.linux.3':
    'Подключитесь: sudo openconnect --certificate=key.pem <адрес сервера>',
  'instructions.linux.4':
    'Для постоянного подключения добавьте профиль в NetworkManager: nmcli connection add type vpn',
```

И симметрично в `en.ts`:

```ts
  'instructions.ios.1': 'Install Cisco Secure Client from the App Store',
  'instructions.ios.2':
    'Open the downloaded key file and enter the password — iOS will offer to install a profile',
  'instructions.ios.3':
    'Settings → General → VPN & Device Management → install the profile',
  'instructions.ios.4':
    'Open Cisco Secure Client, add a connection with the server address and turn the VPN on',

  'instructions.android.1': 'Install Cisco Secure Client from Google Play',
  'instructions.android.2':
    'In the app open Menu → Manage certificates → Import from file',
  'instructions.android.3': 'Pick the downloaded key file and enter the password',
  'instructions.android.4':
    'Add a connection with the server address, select the imported certificate and turn the VPN on',

  'instructions.windows.1': 'Install OpenConnect GUI from the official site',
  'instructions.windows.2':
    'Double-click the downloaded key file and enter the password — Windows stores the certificate in your personal store',
  'instructions.windows.3':
    'In OpenConnect GUI create a profile, enter the server address and pick the certificate from the store',
  'instructions.windows.4': 'Press Connect — the tunnel comes up in a couple of seconds',

  'instructions.macos.1': 'Install OpenConnect GUI or Cisco Secure Client',
  'instructions.macos.2':
    'Double-click the downloaded key file and enter the password — the certificate goes into Keychain',
  'instructions.macos.3':
    'Create a profile with the server address and select the imported certificate',
  'instructions.macos.4': 'Connect and allow the system to add the VPN configuration',

  'instructions.linux.1':
    'Install the openconnect package: apt install openconnect or dnf install openconnect',
  'instructions.linux.2':
    'Unpack the key: openssl pkcs12 -in key.p12 -out key.pem -nodes (it asks for the password)',
  'instructions.linux.3':
    'Connect: sudo openconnect --certificate=key.pem <server address>',
  'instructions.linux.4':
    'For a persistent connection add a NetworkManager profile: nmcli connection add type vpn',
```

Тексты придётся уточнить после проверки на реальных устройствах в Задаче 21 —
особенно шаги для iOS: установка профиля там самая хрупкая часть пути клиента
(открытый вопрос №3 спецификации).

- [ ] **Шаг 2: Написать падающий тест**

`src/screens/Instructions/InstructionsScreen.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockClient } from '../../api/mock/client'
import { resetStore, setLatency } from '../../api/mock/store'
import { renderWithProviders } from '../../test/renderWithProviders'
import InstructionsScreen from './InstructionsScreen'

const openExternal = vi.hoisted(() => vi.fn())
vi.mock('../../telegram/links', () => ({ openExternal, closeApp: vi.fn(), openInTelegram: vi.fn() }))

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useParams: () => ({ platform: 'ios' }) }
})

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
  openExternal.mockClear()
})

function show() {
  return renderWithProviders(<InstructionsScreen />, { client: createMockClient() })
}

describe('InstructionsScreen', () => {
  it('показывает название ОС и пронумерованные шаги', async () => {
    show()
    await waitFor(() => expect(screen.getByText(/iOS/)).toBeVisible())
    expect(screen.getByText('Шаг 1')).toBeVisible()
    expect(screen.getByText('Шаг 4')).toBeVisible()
  })

  it('показывает адрес шлюза с камуфляж-токеном и даёт его скопировать', async () => {
    show()
    await waitFor(() =>
      expect(screen.getByText('https://vpn.example.com/f4a91c7b')).toBeVisible(),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Скопировать' }))
    await waitFor(() => expect(screen.getByText('Скопировано')).toBeVisible())
  })

  it('ссылка на магазин приложений открывается снаружи', async () => {
    show()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Открыть в магазине приложений' }),
    )
    expect(openExternal).toHaveBeenCalledOnce()
    expect(openExternal.mock.calls[0][0]).toContain('apps.apple.com')
  })
})
```

- [ ] **Шаг 3: Убедиться, что тест падает**

Run: `npm test -- src/screens/Instructions`
Expected: FAIL — заглушка выводит только заголовок.

- [ ] **Шаг 4: Описать шаги и ссылки**

`src/screens/Instructions/steps.ts`:

```ts
import type { Platform } from '../../api/types'
import type { MessageKey } from '../../i18n/ru'

/** Ссылки на штатные клиенты. null — клиент ставится пакетным менеджером. */
export const STORE_LINKS: Record<Platform, string | null> = {
  ios: 'https://apps.apple.com/app/cisco-secure-client/id1135064690',
  android: 'https://play.google.com/store/apps/details?id=com.cisco.anyconnect.vpn.android.avf',
  windows: 'https://openconnect.github.io/openconnect-gui/',
  macos: 'https://openconnect.github.io/openconnect-gui/',
  linux: null,
}

const STEPS_PER_PLATFORM = 4

export const STEP_KEYS: Record<Platform, MessageKey[]> = {
  ios: buildKeys('ios'),
  android: buildKeys('android'),
  windows: buildKeys('windows'),
  macos: buildKeys('macos'),
  linux: buildKeys('linux'),
}

function buildKeys(platform: Platform): MessageKey[] {
  return Array.from(
    { length: STEPS_PER_PLATFORM },
    (_, index) => `instructions.${platform}.${index + 1}` as MessageKey,
  )
}

export function isPlatform(value: string | undefined): value is Platform {
  return (
    value === 'ios' ||
    value === 'android' ||
    value === 'windows' ||
    value === 'macos' ||
    value === 'linux'
  )
}
```

- [ ] **Шаг 5: Реализовать экран**

`src/screens/Instructions/InstructionsScreen.tsx`:

```tsx
import { Navigate, useParams } from 'react-router'
import { useConnection } from '../../api/hooks'
import { ROUTES } from '../../app/router'
import { useT } from '../../i18n/useT'
import { useBackButton } from '../../telegram/backButton'
import { openExternal } from '../../telegram/links'
import { Button } from '../../ui/Button'
import { CopyField } from '../../ui/CopyField'
import { ErrorState } from '../../ui/ErrorState'
import { Skeleton } from '../../ui/Skeleton'
import { PLATFORM_ICON, PLATFORM_LABEL } from '../Devices/platform'
import { isPlatform, STEP_KEYS, STORE_LINKS } from './steps'

export default function InstructionsScreen() {
  const { t } = useT()
  const { platform } = useParams()
  useBackButton(ROUTES.devices)

  const connection = useConnection()

  // Путь пришёл руками или из старой ссылки — не показываем сломанный экран.
  if (!isPlatform(platform)) return <Navigate to={ROUTES.devices} replace />

  if (connection.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-7 w-1/2" />
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    )
  }

  if (connection.isError) {
    return <ErrorState error={connection.error} onRetry={() => void connection.refetch()} />
  }

  const storeLink = STORE_LINKS[platform]

  return (
    <div className="p-4">
      <h1 className="mb-1 text-2xl font-bold text-tg-text">
        {PLATFORM_ICON[platform]} {t('instructions.title')} · {PLATFORM_LABEL[platform]}
      </h1>

      <div className="my-5">
        <CopyField
          label={t('instructions.server')}
          value={connection.data!.gateway_url}
          mono
        />
      </div>

      <ol className="mb-6 space-y-4">
        {STEP_KEYS[platform].map((key, index) => (
          <li key={key} className="rounded-xl bg-tg-section-bg p-4">
            <p className="mb-1 text-[13px] font-medium uppercase tracking-wide text-tg-hint">
              {t('instructions.step', { n: index + 1 })}
            </p>
            <p className="text-[15px] leading-snug text-tg-text">{t(key)}</p>
          </li>
        ))}
      </ol>

      {storeLink && (
        <Button variant="secondary" onClick={() => openExternal(storeLink)}>
          {t('instructions.openStore')}
        </Button>
      )}
    </div>
  )
}
```

- [ ] **Шаг 6: Убедиться, что тесты проходят**

Run: `npm test -- src/screens/Instructions`
Expected: 3 passed.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma/src/screens/Instructions frontend/tma/src/i18n
git commit -m "feat(tma): per-platform setup instructions with gateway address"
```

---

### Задача 19: Глобальные состояния — граница ошибок, блокировка, запуск вне Telegram

Три ситуации, которые ломают приложение целиком и потому не решаются на уровне
экрана: исключение в рендере, заблокированный клиент и запуск вне Telegram
(без `initData` любой запрос обречён).

**Files:**
- Create: `frontend/tma/src/app/ErrorBoundary.tsx`
- Create: `frontend/tma/src/app/Gate.tsx`
- Modify: `frontend/tma/src/app/App.tsx`
- Modify: `frontend/tma/src/api/hooks.ts` (`useMe` получает `enabled`)
- Modify: `frontend/tma/src/i18n/ru.ts`, `frontend/tma/src/i18n/en.ts`
- Create: `frontend/tma/src/app/Gate.test.tsx`

**Interfaces:**
- Consumes: `useMe`, `env`, `getInitDataRaw`, `ErrorState`, `EmptyState`
- Produces: `<ErrorBoundary>`, `<Gate>` — обёртка, пропускающая дальше только
  работоспособное состояние

- [ ] **Шаг 1: Дописать ключи в каталоги**

```ts
  'gate.outsideTelegram': 'Откройте приложение из Telegram',
  'gate.outsideTelegramBody':
    'Мини-приложение работает только внутри Telegram — вернитесь в чат с ботом.',
  'gate.blocked': 'Доступ приостановлен',
  'gate.blockedBody': 'Обратитесь в поддержку, чтобы разобраться с блокировкой.',
  'gate.crashed': 'Приложение не смогло продолжить',
  'gate.reload': 'Перезапустить',
```

Английские соответствия — в `en.ts`.

- [ ] **Шаг 2: Написать падающий тест**

`src/app/Gate.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockClient } from '../api/mock/client'
import { resetStore, setFault, setLatency } from '../api/mock/store'
import { renderWithProviders } from '../test/renderWithProviders'
import { ErrorBoundary } from './ErrorBoundary'
import { Gate } from './Gate'

const getInitDataRaw = vi.hoisted(() => vi.fn<() => string | undefined>())
vi.mock('../telegram/auth', async () => {
  const actual = await vi.importActual<typeof import('../telegram/auth')>('../telegram/auth')
  return { ...actual, getInitDataRaw }
})

beforeEach(() => {
  sessionStorage.clear()
  resetStore('active')
  setLatency(0)
  setFault('none')
  getInitDataRaw.mockReturnValue('user=%7B%7D&hash=a')
})

function show() {
  return renderWithProviders(
    <Gate>
      <p>содержимое</p>
    </Gate>,
    { client: createMockClient() },
  )
}

describe('Gate', () => {
  it('пропускает работоспособное состояние', async () => {
    show()
    await waitFor(() => expect(screen.getByText('содержимое')).toBeVisible())
  })

  it('без initData объясняет, что делать, и не ходит в API', async () => {
    getInitDataRaw.mockReturnValue(undefined)
    show()
    await waitFor(() =>
      expect(screen.getByText('Откройте приложение из Telegram')).toBeVisible(),
    )
    expect(screen.queryByText('содержимое')).toBeNull()
  })

  it('заблокированному клиенту показывает объяснение вместо приложения', async () => {
    resetStore('blocked')
    show()
    await waitFor(() => expect(screen.getByText('Доступ приостановлен')).toBeVisible())
    expect(screen.queryByText('содержимое')).toBeNull()
  })

  it('истёкшая initData показывается отдельным сообщением', async () => {
    setFault('internal')
    show()
    await waitFor(() => expect(screen.getByText('Что-то пошло не так')).toBeVisible())
  })
})

describe('ErrorBoundary', () => {
  function Boom(): never {
    throw new Error('рендер упал')
  }

  it('перехватывает исключение рендера и предлагает перезапуск', async () => {
    // React печатает пойманную ошибку в консоль — глушим, чтобы вывод тестов был читаемым.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    renderWithProviders(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Приложение не смогло продолжить')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Перезапустить' })).toBeVisible()
    spy.mockRestore()
  })
})
```

- [ ] **Шаг 3: Убедиться, что тест падает**

Run: `npm test -- src/app/Gate.test.tsx`
Expected: FAIL, модули не найдены.

- [ ] **Шаг 4: Реализовать границу ошибок**

`src/app/ErrorBoundary.tsx`. Классовый компонент — единственный способ
перехватить исключение рендера в React; хуковой альтернативы нет.

```tsx
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useT } from '../i18n/useT'

function Crashed() {
  const { t } = useT()
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-8 py-12 text-center">
      <div className="mb-4 text-5xl" aria-hidden="true">
        💥
      </div>
      <h1 className="mb-4 text-lg font-semibold text-tg-text">{t('gate.crashed')}</h1>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="w-full max-w-xs rounded-xl bg-tg-button px-4 py-3.5 text-base font-medium text-tg-button-text"
      >
        {t('gate.reload')}
      </button>
    </div>
  )
}

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false }

  static getDerivedStateFromError(): { crashed: boolean } {
    return { crashed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Отправки телеметрии нет: в этап 1 логи собираются только на бэкенде.
    console.error('[tma] непойманная ошибка рендера', error, info.componentStack)
  }

  render(): ReactNode {
    return this.state.crashed ? <Crashed /> : this.props.children
  }
}
```

- [ ] **Шаг 5: Разрешить `useMe` не запускаться**

В `src/api/hooks.ts` заменить сигнатуру:

```ts
export function useMe(options: { enabled?: boolean } = {}): UseQueryResult<Me, ApiError> {
  const api = useApi()
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.getMe(),
    enabled: options.enabled ?? true,
  })
}
```

Остальные вызовы `useMe()` (в `PlansScreen`) продолжают работать без изменений.

Учесть при этом: у отключённого запроса `isPending` остаётся `true` навсегда,
поэтому в `Gate` проверка `hasInitData` идёт **до** проверки `me.isPending` —
иначе экран навсегда застрянет на скелете.

- [ ] **Шаг 6: Реализовать `Gate`**

`src/app/Gate.tsx`:

```tsx
import type { ReactNode } from 'react'
import { useMe } from '../api/hooks'
import { useT } from '../i18n/useT'
import { getInitDataRaw } from '../telegram/auth'
import { EmptyState } from '../ui/EmptyState'
import { ErrorState } from '../ui/ErrorState'
import { Skeleton } from '../ui/Skeleton'

export function Gate({ children }: { children: ReactNode }) {
  const { t } = useT()
  const hasInitData = getInitDataRaw() !== undefined
  // enabled:false — без initData запрос гарантированно получит 401,
  // и отправлять его означает только шуметь в логах бэкенда.
  const me = useMe({ enabled: hasInitData })

  if (!hasInitData) {
    return (
      <EmptyState
        icon="✈️"
        title={t('gate.outsideTelegram')}
        body={t('gate.outsideTelegramBody')}
      />
    )
  }

  if (me.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-7 w-1/3" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    )
  }

  if (me.isError) {
    return <ErrorState error={me.error} onRetry={() => void me.refetch()} />
  }

  if (me.data.is_blocked) {
    return <EmptyState icon="⛔️" title={t('gate.blocked')} body={t('gate.blockedBody')} />
  }

  return <>{children}</>
}
```

- [ ] **Шаг 7: Подключить в `App`**

В `src/app/App.tsx` обернуть содержимое:

```tsx
<I18nProvider>
  <ErrorBoundary>
    <BrowserRouter>
      <Gate>
        <AppRoutes />
      </Gate>
      {DevPanel && (
        <Suspense fallback={null}>
          <DevPanel />
        </Suspense>
      )}
    </BrowserRouter>
  </ErrorBoundary>
</I18nProvider>
```

`DevPanel` остаётся снаружи `Gate`: переключать сценарии нужно в том числе
тогда, когда `Gate` не пускает дальше.

- [ ] **Шаг 8: Убедиться, что тесты проходят**

Run: `npm test`
Expected: весь набор зелёный.

- [ ] **Шаг 9: Коммит**

```bash
git add frontend/tma/src
git commit -m "feat(tma): error boundary and access gate for blocked/no-initData states"
```

---

# Фаза 4. Переключение на реальный бэкенд

Задачи 20–21 выполняются, когда `api-public` отдаёт `/tma/*`. До этого момента
приложение полностью функционально на моках, и Фаза 4 не блокирует ничего из
Фаз 0–3.

### Задача 20: Сверка контракта и включение HTTP-режима

Момент истины: контракт, написанный руками в Задаче 4, встречается с реальной
OpenAPI-схемой. Расхождения будут — вопрос только в их числе. Порядок действий
устроен так, чтобы каждое расхождение всплыло как ошибка компиляции или
падающий тест, а не как белый экран в проде.

**Files:**
- Create: `frontend/tma/src/api/generated.d.ts` (не коммитится)
- Modify: `frontend/tma/package.json`
- Modify: `frontend/tma/src/api/types.ts`
- Modify: `frontend/tma/src/api/http.ts` (по итогам сверки)
- Create: `frontend/tma/src/api/types.contract.test-d.ts`
- Modify: `frontend/tma/.env.example`
- Modify: `frontend/tma/.gitignore` (добавляется `src/api/generated.d.ts`)

**Interfaces:**
- Consumes: OpenAPI-схема с `http://localhost:8000/openapi.json`
- Produces: команда `npm run api:types`; тест соответствия ручных типов
  сгенерированным

- [ ] **Шаг 1: Добавить генерацию типов**

```bash
cd frontend/tma
npm i -DE openapi-typescript@7.4.4
npm pkg set scripts.api:types="openapi-typescript http://localhost:8000/openapi.json -o src/api/generated.d.ts"
echo "src/api/generated.d.ts" >> .gitignore
```

Файл намеренно не коммитится: закоммиченный, он незаметно разъезжается с
бэкендом, и тогда компилятор проверяет вчерашний контракт.

- [ ] **Шаг 2: Сгенерировать типы**

```bash
cd backend && uvicorn ocmanager.apps.public_api:app --port 8000 &
cd ../frontend/tma && npm run api:types
```

- [ ] **Шаг 3: Написать тест соответствия типов**

`src/api/types.contract.test-d.ts` — проверка на уровне типов, без выполнения.
Каждое несоответствие ручного DTO сгенерированному становится ошибкой `tsc`.

```ts
import type { components } from './generated'
import type { Device, Me, Plan, Subscription } from './types'

type Generated<K extends keyof components['schemas']> = components['schemas'][K]

/** Компилируется, только если T и U взаимно присваиваемы. */
type AssertSame<T, U> = [T] extends [U] ? ([U] extends [T] ? true : never) : never

// Каждая строка ломает сборку, если бэкенд изменил форму ответа.
export const planMatches: AssertSame<Plan, Generated<'PlanOut'>> = true
export const meMatches: AssertSame<Me, Generated<'MeOut'>> = true
export const deviceMatches: AssertSame<Device, Generated<'DeviceOut'>> = true
export const subscriptionMatches: AssertSame<Subscription, Generated<'SubscriptionOut'>> = true
```

Имена схем (`PlanOut`, `MeOut`, …) берутся из сгенерированного файла: FastAPI
называет их по классам Pydantic. Если имена другие — подставить фактические.

- [ ] **Шаг 4: Прогнать проверку типов и устранить расхождения**

Run: `npm run typecheck`

Каждая ошибка — реальное расхождение контракта. Разбирать так:

| Что показал компилятор | Что делать |
|---|---|
| Поле есть в схеме, нет в `types.ts` | добавить в `types.ts`; если оно нужно UI — использовать, если нет — добавить и не использовать |
| Поле есть в `types.ts`, нет в схеме | удалить из `types.ts` и из всех мест использования; в моке — тоже |
| Тип отличается (`number` против `string`) | привести `types.ts` к схеме, поправить форматтеры |
| `null` против отсутствия поля | привести `types.ts` к схеме; проверить, что UI не падает на `undefined` |
| Другая форма конверта ответа | поправить только `http.ts` — мок и экраны не трогать |

Мок обновляется вслед за `types.ts`: его фикстуры обязаны остаться валидными
по новым типам, иначе `npm run typecheck` не пройдёт.

- [ ] **Шаг 5: Запустить контрактный набор против живого бэкенда**

`src/api/contract.http.test.ts` — запускается только когда бэкенд поднят:

```ts
import { describe } from 'vitest'
import { runContractSuite } from '../test/contract.suite'
import { createHttpClient } from './http'

const BASE_URL = process.env.TMA_E2E_BASE_URL

// Без переменной окружения набор пропускается: обычный npm test не должен
// зависеть от поднятого бэкенда.
if (BASE_URL) {
  runContractSuite('http', async () =>
    createHttpClient({
      baseUrl: BASE_URL,
      getInitDataRaw: () => process.env.TMA_E2E_INIT_DATA,
    }),
  )
} else {
  describe.skip('контракт ApiClient: http (нужен TMA_E2E_BASE_URL)', () => {})
}
```

Запуск:

```bash
TMA_E2E_BASE_URL=http://localhost:8000/api \
TMA_E2E_INIT_DATA="$(cat /tmp/dev-initdata.txt)" \
npm test -- src/api/contract.http.test.ts
```

Строка `initData` берётся из dev-мока (Задача 2) — бэкенд принимает её при
`TMA_ALLOW_DEV_INITDATA=true`.

Expected: те же 7 тестов, что проходили на моке, проходят на HTTP.

- [ ] **Шаг 6: Включить HTTP-режим локально и пройти сценарии руками**

```bash
VITE_API_MODE=http npm run dev
```

Пройти по порядку и отметить каждый пункт:

- [ ] тарифы загружаются, цены и сроки совпадают с админкой
- [ ] активация trial создаёт подписку, повторная попытка даёт понятную ошибку
- [ ] экран подписки показывает верные срок и трафик
- [ ] выпуск устройства даёт рабочую ссылку на `.p12` и пароль
- [ ] скачанный `.p12` открывается с показанным паролем
- [ ] повторное открытие одноразовой ссылки даёт отказ
- [ ] отзыв устройства убирает его из списка
- [ ] по истечении 15 минут ссылка перестаёт работать
- [ ] покупка открывает checkout-страницу провайдера
- [ ] `VITE_API_MODE=mock npm run dev` по-прежнему работает без бэкенда

- [ ] **Шаг 7: Переключить дефолт**

`.env.development` меняется на `VITE_API_MODE=http`, `.env.example`
комментируется соответственно. Мок остаётся доступным по
`VITE_API_MODE=mock` — он не удаляется: на нём гоняются все тесты
и работает разработка при недоступном бэкенде.

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/tma
git commit -m "feat(tma): reconcile contract with backend openapi and enable http mode"
```

---

### Задача 21: Production-сборка и развёртывание

Последняя задача: убедиться, что в бой уходит то, что задумано, и что оно
открывается в настоящем Telegram.

**Files:**
- Create: `frontend/tma/src/build.test.ts`
- Modify: `deploy/caddy/Caddyfile`
- Modify: `deploy/docker-compose.tma.yml`
- Create: `frontend/tma/.env.production`

**Interfaces:**
- Consumes: результат `npm run build`
- Produces: проверенная production-сборка в `frontend/tma/dist`

- [ ] **Шаг 1: Написать тест содержимого бандла**

`src/build.test.ts` — читает собранный `dist` и проверяет, что моков там нет.
Единственный тест в проекте, требующий предварительной сборки.

```ts
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const DIST = join(import.meta.dirname, '..', 'dist')

function bundleText(): string {
  const assets = join(DIST, 'assets')
  return readdirSync(assets)
    .filter((file) => file.endsWith('.js'))
    .map((file) => readFileSync(join(assets, file), 'utf8'))
    .join('\n')
}

describe.skipIf(!existsSync(DIST))('production-сборка', () => {
  it('не содержит поддельную initData', () => {
    expect(bundleText()).not.toContain('dev-mock-hash')
  })

  it('не содержит мок-клиента и его сценариев', () => {
    const text = bundleText()
    expect(text).not.toContain('окружение Telegram замокано')
    expect(text).not.toContain('Активный пробный период')
  })

  it('не содержит dev-панели', () => {
    expect(bundleText()).not.toContain('Мок-окружение')
  })

  it('index.html не выставляет X-Frame-Options через meta', () => {
    const html = readFileSync(join(DIST, 'index.html'), 'utf8')
    expect(html.toLowerCase()).not.toContain('x-frame-options')
  })
})
```

- [ ] **Шаг 2: Собрать и убедиться, что тест проходит**

```bash
cd frontend/tma
cat > .env.production <<'EOF'
VITE_API_MODE=http
VITE_API_BASE_URL=/api
VITE_DEV_PANEL=false
EOF
npm run build
npm test -- src/build.test.ts
```

Expected: 4 passed. Если тест падает — мок протёк в бандл; искать статический
`import` вместо динамического под `import.meta.env.DEV`.

- [ ] **Шаг 3: Проверить размер бандла**

```bash
du -sh dist/assets/*.js | sort -h
```

Ориентир: главный чанк до 250 КБ без сжатия. Превышение почти всегда означает,
что ленивый импорт экрана превратился в статический — проверить `router.tsx`.

- [ ] **Шаг 4: Убедиться в корректности Caddyfile**

`deploy/caddy/Caddyfile` — три вещи, каждая из которых ломает TMA:

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
		try_files {path} /index.html
		file_server
	}

	header {
		Referrer-Policy strict-origin-when-cross-origin
		X-Content-Type-Options nosniff
		-X-Frame-Options
	}
}
```

- `try_files {path} /index.html` — без него любой маршрут кроме `/` даёт 404,
  а Telegram открывает Mini App с собственными query-параметрами.
- `-X-Frame-Options` — явное удаление заголовка. Его наличие даёт белый экран
  в веб-клиенте Telegram без единой ошибки в консоли.
- `/api/*` проксируется на `api-public`, а не раздаётся как статика.

- [ ] **Шаг 5: Проверить в настоящем Telegram через туннель**

```bash
npm run dev &
cloudflared tunnel --url http://localhost:5173
```

Полученный адрес вписать в BotFather (`/myapps` → приложение →
Edit Web App URL), открыть бота и проверить:

- [ ] приложение открывается на весь экран, а не половиной
- [ ] цвета совпадают с темой клиента; переключение темы Telegram меняет их
- [ ] нативная кнопка «Назад» появляется на вложенных экранах и работает
- [ ] хаптика срабатывает на кнопках
- [ ] в тёмной теме читаемы все тексты, включая бейджи и предупреждения
- [ ] `.p12` скачивается и открывается на реальном iPhone (открытый вопрос №3
      спецификации — проверяется именно здесь)

После проверки вернуть в BotFather боевой URL: адрес туннеля живёт только
пока запущена команда.

- [ ] **Шаг 6: Развернуть**

```bash
cd frontend && npm ci && npm run build -w tma
cd ../deploy && docker compose -f docker-compose.tma.yml up -d --build
curl -I https://app.example.com
curl -s https://app.example.com/api/health
```

Expected: `200` с валидным TLS и `{"status":"ok"}`.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/tma deploy
git commit -m "chore(tma): production build guards and deployment configuration"
```

---

## Чек-лист переключения «моки → реальность»

Сводка того, что физически меняется. Всё остальное приложение не трогается —
это и есть проверка, что шов проведён правильно.

| Что | Где | Задача |
|---|---|---|
| `VITE_API_MODE=mock` → `http` | `.env.development`, `.env.production` | 20, 21 |
| Ручные DTO сверяются со сгенерированными | `src/api/types.ts` | 20 |
| Форма конвертов ответов | `src/api/http.ts` | 20 |
| Коды ошибок бэкенда | `src/api/errors.ts` | 20 |
| Витрина trial из настроек инсталляции | `src/screens/Plans/trialPreview.ts` | 20 |
| Dev-панель выключается | `VITE_DEV_PANEL=false` | 21 |

**Что не меняется:** ни один компонент в `ui/`, ни один экран в `screens/`,
ни один хук в `api/hooks.ts`, ни один тест кроме контрактного. Если при
переключении пришлось править экран — значит, деталь мока протекла через шов,
и чинить надо шов, а не экран.

---

## Определение готовности

**Фаза 0 готова, когда:** `npm test`, `npm run typecheck`, `npm run lint` и
`npm run build` проходят; `localhost:5173` открывается с применённой темой
Telegram; пропущенный перевод ломает компиляцию.

**Фаза 1 готова, когда:** контрактный набор проходит на моке; мок отвечает
ошибками на превышение лимита устройств, повторный trial и выпуск на
неактивной подписке; HTTP-клиент покрыт тестами с подменённым `fetch`.

**Фаза 2 готова, когда:** три вкладки переключаются, вложенные экраны без
таб-бара, dev-панель меняет сценарий и сбрасывает кэш, в production-сборке
панели нет.

**Фаза 3 готова, когда:** каждый из одиннадцати сценариев мока даёт
осмысленный экран без пустых мест и без `undefined` в интерфейсе; проверено
переключением в dev-панели по всему списку.

**Фаза 4 готова, когда:** контрактный набор проходит против живого бэкенда;
ручной прогон покупки, выпуска и отзыва выполнен на реальном сервере;
`.p12` установлен на реальном iPhone и VPN подключается.

---

## Покрытие требований спецификации

| Требование | Источник | Где закрыто |
|---|---|---|
| TMA: тарифы, покупка, устройства | дизайн §14, прил. A | Задачи 14, 16, 17 |
| Инструкция под ОС + QR + deep-link | дизайн §7.3 п.8, прил. A | Задачи 17, 18 |
| Страница самообслуживания: трафик, срок | прил. A | Задача 15 |
| Trial: один на `telegram_id`, одно устройство | дизайн §7.3 | Задачи 14 (UI), 5–6 (правило в моке) |
| Одноразовая ссылка TTL 15 минут, пароль один раз | дизайн §7.3 п.8, §11 | Задача 17 |
| `cancelled` не отключает доступ | дизайн §6 | Задачи 9 (`isLive`), 15 (тест) |
| Жёсткое отключение по истечении | дизайн §3 | Задачи 9, 15, 16 |
| Лимит устройств тарифа | дизайн §5 | Задачи 6, 16, 17 |
| i18n ru/en с первого дня | дизайн §10 | Задача 3 |
| Валидация `initData`, схема `tma` в заголовке | руководство B5 | Задачи 2, 7 |
| Разработка в браузере на моке | руководство B1, B3 | Задачи 2, 5, 6, 13 |
| `allowedHosts` для туннеля | руководство B2, B10 | Задача 1 |
| Порядок работы 1–7 | руководство B9 | Задачи 8, 14, 15, 16, 17, 14 |
| Точные версии зависимостей | руководство B2 | Задача 1 |
| Нет `X-Frame-Options`, есть SPA-фоллбэк | руководство A3, B10 | Задача 21 |
| Rate-limit на выдаче устройств и trial | дизайн §11 | Задачи 6 (`rate_limited`), 11 (`ErrorState`) |

**Сознательно вне области этого плана:** админ-панель (`frontend/admin`),
Telegram Stars и криптоплатежи (этап 2), графики потребления (этап 2), выбор
локации ноды (этап 4), `packages/api-types` и `packages/ui` из целевой
раскладки — общие пакеты монорепо имеет смысл выделять, когда появится второе
приложение, то есть вместе с админкой.
