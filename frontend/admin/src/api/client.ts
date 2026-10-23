import { ApiError } from "./errors";

export type QueryValue = string | number | boolean | undefined;
export type Query = Record<string, QueryValue>;

export interface ClientDeps {
  /** Подменяется в тестах; в приложении — глобальный fetch. */
  fetchImpl?: typeof fetch;
  onUnauthorized?: () => void;
}

export interface ApiClient {
  get<T>(path: string, query?: Query): Promise<T>;
  post<T = void>(path: string, body?: unknown): Promise<T>;
  patch<T>(path: string, body?: unknown): Promise<T>;
  delete(path: string): Promise<void>;
  setCsrf(token: string | null): void;
  /** Задаётся после создания: провайдер сессии знает о клиенте, клиент о провайдере — нет. */
  setOnUnauthorized(fn: (() => void) | undefined): void;
}

const PREFIX = "/admin";

export function queryString(query: Query | undefined): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string };
}

export function createClient(deps: ClientDeps = {}): ApiClient {
  const fetchImpl = deps.fetchImpl ?? globalThis.fetch.bind(globalThis);
  let csrf: string | null = null;
  let onUnauthorized = deps.onUnauthorized;

  async function request<T>(
    method: "GET" | "POST" | "PATCH" | "DELETE",
    path: string,
    body?: unknown,
    query?: Query,
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;

    let response: Response;
    try {
      response = await fetchImpl(`${PREFIX}${path}${queryString(query)}`, {
        method,
        headers,
        credentials: "same-origin",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError("network", 0, "network error");
    }

    if (!response.ok) {
      let code = `http_${response.status}`;
      let message: string | undefined;
      try {
        const data = (await response.json()) as ErrorEnvelope;
        code = data.error?.code ?? code;
        message = data.error?.message;
      } catch {
        // тело не JSON (например, страница прокси): остаётся http_<status>
      }
      if (response.status === 401) onUnauthorized?.();
      throw new ApiError(code, response.status, message);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    get: (path, query) => request("GET", path, undefined, query),
    post: (path, body) => request("POST", path, body),
    patch: (path, body) => request("PATCH", path, body),
    delete: (path) => request("DELETE", path),
    setCsrf: (token) => {
      csrf = token;
    },
    setOnUnauthorized: (fn) => {
      onUnauthorized = fn;
    },
  };
}
