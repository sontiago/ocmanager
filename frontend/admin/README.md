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

`src/api/generated.d.ts` сгенерирован из OpenAPI и закоммичен. Сервер для этого не нужен: схема берётся прямо
из кода бэкенда.

```bash
npm run api:types:offline   # перегенерировать (make admin-types в backend/)
npm run api:check           # проверить, что типы не отстали (то же делает CI)
```

`npm run api:types` берёт схему с запущенного `make api-admin` — тот же результат, если нужно проверить живой сервер.

## Устройство

- `src/api/` — `client.ts` (fetch, CSRF, разбор ошибок), `session.tsx` (вход, `/auth/me`), `hooks/` (запросы TanStack Query).
- `src/pages/` — по странице на раздел; `src/ui/` — общие компоненты; `src/lib/` — форматирование, фильтры в URL, SSE.
- `src/i18n/{ru,en}.json` — словари; тест следит, чтобы наборы ключей совпадали.
