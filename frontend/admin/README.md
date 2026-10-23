# Веб-админка ocmanager

React + Vite + Tailwind поверх админ-API (`/admin/*`). Спека: `docs/superpowers/specs/2026-10-23-admin-web-design.md`.

В проде собранную статику отдаёт сам `api-admin` на `/` (образ бэкенда собирает её отдельной стадией),
поэтому cookie-сессия и CSRF работают на одном origin, без CORS. Доступ — только через SSH-туннель.

## Запуск для разработки

Из `backend/`:

```bash
make dev-up && make migrate
uv run ocmanager admin create      # первый админ
make api-admin                     # 127.0.0.1:8080
```

Из `frontend/admin/`:

```bash
npm install
npm run dev                        # Vite проксирует /admin на 127.0.0.1:8080
```

## Проверки

```bash
npm run typecheck && npm run lint && npm test && npm run build
```

## Типы API

`src/api/generated.d.ts` сгенерирован из OpenAPI и закоммичен (в CI живого бэкенда нет). После правок
API обновите его при запущенном `make api-admin`:

```bash
npm run api:types
```

## Устройство

- `src/api/` — `client.ts` (fetch, CSRF, разбор ошибок), `session.tsx` (вход, `/auth/me`), `hooks/` (запросы TanStack Query).
- `src/pages/` — по странице на раздел; `src/ui/` — общие компоненты; `src/lib/` — форматирование, фильтры в URL, SSE.
- `src/i18n/{ru,en}.json` — словари; тест следит, чтобы наборы ключей совпадали.
