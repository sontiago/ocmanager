# ocmanager · Telegram Mini App

Клиентское приложение внутри Telegram: тарифы и оплата, подписка, выдача ключей устройствам, инструкции по
подключению, рефералы и промокоды. Работает поверх публичного API (`/api/tma/*`).

> Общая картина: [docs/architecture.md](../../docs/architecture.md). Детали: [docs/tma/architecture.md](../../docs/tma/architecture.md).

## Стек

| Область | Что используется |
|---|---|
| UI | React 19, TypeScript 6, Tailwind CSS 4, свои компоненты в стиле Telegram |
| Сборка | Vite 8, статика отдаётся Caddy |
| Telegram | `@telegram-apps/sdk` и `sdk-react` (initData, тема, кнопка «назад», haptics) |
| Данные | TanStack Query 5; два клиента API с одним контрактом: `mock` и `http` |
| Роутинг | React Router 7 |
| Прочее | `qrcode` (QR ссылки на ключ) |
| Тесты | Vitest, Testing Library, jsdom, проверка типов контракта; линтер oxlint |

## Режимы

| `VITE_API_MODE` | Что это |
|---|---|
| `mock` (по умолчанию в dev) | всё работает без бэкенда: сценарии, ошибки, задержки; панель разработчика `VITE_DEV_PANEL=true` |
| `http` (прод) | реальные запросы на `/api`, авторизация initData |

## Запуск для разработки

```bash
cd frontend/tma && npm ci && npm run dev     # мок-режим, бэкенд не нужен
```

С реальным бэкендом: `VITE_API_MODE=http`, запущенный `api-public` (`make api-public`) и
`OCM_TMA_ALLOW_DEV_INITDATA=true` на бэкенде.

## Проверки

```bash
npm run typecheck && npm run lint && npm test && npm run build
```

## Структура

```
src/
  api/        contract.ts (интерфейс), mock/ и http.ts (реализации), hooks.ts (TanStack Query), generated.d.ts
  app/        App, router, Gate (проверка Telegram и /me), Layout, TabBar, DevPanel
  screens/    Subscription, Plans, Checkout, Devices, DeviceCreate, DeviceSecret, Instructions, Friends, Account …
  telegram/   initData, тема, кнопка «назад», ссылки, mockEnv
  ui/         компоненты интерфейса
  i18n/       ru.ts, en.ts (язык берётся из Telegram: ru → ru, остальное → en)
```
