import type { ApiClient } from "./contract";
import { API_ERROR_CODES, ApiError, type ApiErrorCode } from "./errors";
import type {
  Checkout,
  ConnectionInfo,
  CreateDeviceInput,
  Device,
  IssuedDevice,
  Me,
  Plan,
  Subscription,
} from "./types";

export interface HttpDeps {
  baseUrl: string;
  getInitDataRaw: () => string | undefined;
  /** Подменяется в тестах; в приложении — глобальный fetch. */
  fetchImpl?: typeof fetch;
}

const KNOWN_CODES: ReadonlySet<string> = new Set(API_ERROR_CODES);

interface ErrorEnvelope {
  error?: { code?: string; message?: string };
}

export function createHttpClient(deps: HttpDeps): ApiClient {
  const fetchImpl = deps.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    method: "GET" | "POST" | "DELETE",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const raw = deps.getInitDataRaw();
    if (!raw) {
      // До сети не доходим: без initData личности нет, и 401 гарантирован.
      throw new ApiError(
        "unauthorized",
        401,
        "приложение открыто вне Telegram",
      );
    }

    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `tma ${raw}`,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let response: Response;
    try {
      response = await fetchImpl(`${deps.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (cause) {
      throw new ApiError(
        "network",
        0,
        cause instanceof Error ? cause.message : "сеть недоступна",
      );
    }

    if (!response.ok) throw await toApiErrorFromResponse(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async function toApiErrorFromResponse(response: Response): Promise<ApiError> {
    let envelope: ErrorEnvelope = {};
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      // Прокси и балансировщики отдают HTML — это нормальный случай, не сбой клиента.
    }

    const raw = envelope.error?.code;
    const code: ApiErrorCode = KNOWN_CODES.has(raw ?? "")
      ? (raw as ApiErrorCode)
      : "internal";

    return new ApiError(code, response.status, envelope.error?.message);
  }

  return {
    getMe: () => request<Me>("GET", "/tma/me"),
    listPlans: () => request<Plan[]>("GET", "/tma/plans"),

    async getSubscription() {
      const envelope = await request<{ subscription: Subscription | null }>(
        "GET",
        "/tma/subscription",
      );
      return envelope.subscription;
    },

    startTrial: () =>
      request<Subscription>("POST", "/tma/subscription/trial", {}),

    createCheckout: (planCode: string) =>
      request<Checkout>("POST", "/tma/checkout", { plan_code: planCode }),

    listDevices: () => request<Device[]>("GET", "/tma/devices"),

    createDevice: (input: CreateDeviceInput) =>
      request<IssuedDevice>("POST", "/tma/devices", input),

    revokeDevice: (deviceId: string) =>
      request<void>("DELETE", `/tma/devices/${encodeURIComponent(deviceId)}`),

    getConnection: () => request<ConnectionInfo>("GET", "/tma/connection"),
  };
}
