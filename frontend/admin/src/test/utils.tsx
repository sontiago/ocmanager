import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { createClient } from "../api/client";
import { SessionProvider } from "../api/session";
import { I18nProvider } from "../i18n";

export const ADMIN = {
  id: 1,
  username: "root",
  role: "owner",
  totp_enabled: false,
  last_login_at: null,
};

export interface MockRequest {
  method: string;
  url: URL;
  body: unknown;
}
type Handler = Response | object | ((req: MockRequest) => Response | object | undefined);

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function apiError(status: number, code: string, message = code): Response {
  return json(status, { error: { code, message } });
}

/**
 * Подставной fetch. Ключ — "METHOD /admin/path" (без query). Значение: объект → 200 JSON,
 * Response как есть, функция получает запрос. Неизвестный маршрут → 404 и запись в `calls`.
 */
export function mockApi(handlers: Record<string, Handler> = {}) {
  const table: Record<string, Handler> = {
    "GET /admin/auth/me": { admin: ADMIN, csrf_token: "csrf-1" },
    ...handlers,
  };
  const calls: MockRequest[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    const req: MockRequest = {
      method,
      url,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(req);
    const handler = table[`${method} ${url.pathname}`];
    if (handler === undefined) return apiError(404, "not_found");
    const result = typeof handler === "function" ? handler(req) : handler;
    if (result === undefined) return new Response(null, { status: 204 });
    return result instanceof Response ? result.clone() : json(200, result);
  }) as typeof fetch;
  return { fetchImpl, calls };
}

export function renderRoutes(
  routes: RouteObject[],
  opts: { route?: string | { pathname: string; state?: unknown }; handlers?: Record<string, Handler> } = {},
) {
  const api = mockApi(opts.handlers);
  const client = createClient({ fetchImpl: api.fetchImpl });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, {
    initialEntries: [opts.route ?? "/"] as never,
  });
  const utils = render(
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client}>
          <RouterProvider router={router} />
        </SessionProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
  return { ...utils, ...api, router, queryClient };
}

/** Одна страница по маршруту `/`, под сессией админа. */
export function renderPage(
  element: React.ReactNode,
  opts: { route?: string; path?: string; handlers?: Record<string, Handler> } = {},
) {
  return renderRoutes([{ path: opts.path ?? "/", element }, { path: "*", element: null }], {
    route: opts.route ?? "/",
    handlers: opts.handlers,
  });
}
