# ocmanager · веб-админка

SPA для владельца сервиса: клиенты, подписки, платежи, статистика, нода, настройки. Работает поверх админ-API
(`/admin/*`).

> Общая картина: [docs/architecture.md](../../docs/architecture.md). Детали: [docs/admin/architecture.md](../../docs/admin/architecture.md).

## Стек

| Область | Что используется |
|---|---|
| UI | React 19, TypeScript 6, Tailwind CSS 4 (стиль AdminLTE) |
| Сборка | Vite 8 |
| Данные | TanStack Query 5, собственный fetch-клиент (CSRF, разбор ошибок) |
| Роутинг | React Router 7 |
| Графики | Recharts |
| Типы API | `openapi-typescript`: `src/api/generated.d.ts` генерируется из кода бэкенда |
| Тесты | Vitest, Testing Library, jsdom; линтер oxlint |

В проде статику отдаёт сам `api-admin` на `/`: cookie-сессия и CSRF работают на одном origin, CORS не нужен.
Доступ только через SSH-туннель.

## Запуск для разработки

```bash
cd backend && make dev-up && make migrate && uv run ocmanager admin create owner && make api-admin
cd frontend/admin && npm ci && npm run dev     # http://localhost:5173, /admin проксируется на 127.0.0.1:8080
```

## Проверки

```bash
npm run typecheck && npm run lint && npm test && npm run build
```

## Типы API

`src/api/generated.d.ts` закоммичен и перегенерируется из кода бэкенда без запущенного сервера:

```bash
npm run api:types:offline   # то же, что make admin-types в backend/
npm run api:check           # типы не отстали от бэкенда (то же делает CI)
```

## Структура

```
src/
  api/        client.ts (fetch, CSRF), session.tsx (вход, /auth/me), hooks/ (запросы по разделам)
  app/        App.tsx, routes.tsx (таблица маршрутов), RequireAuth.tsx
  pages/      по странице на раздел (Overview, Clients, Stats, Plans, Settings, Node …)
  ui/         общие компоненты: AppShell, DataTable, Card, Modal, графики
  lib/        форматирование, фильтры в URL, SSE-хук, формы
  i18n/       ru.json, en.json (тест следит, чтобы наборы ключей совпадали)
```
