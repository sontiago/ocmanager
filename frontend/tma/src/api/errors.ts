import type { MessageKey } from "../i18n/ru";

export const API_ERROR_CODES = [
  "network",
  "unauthorized",
  "initdata_expired",
  "rate_limited",
  "device_limit_reached",
  "trial_already_used",
  "subscription_inactive",
  "node_unavailable",
  "not_found",
  "internal",
] as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

const RETRYABLE: ReadonlySet<ApiErrorCode> = new Set([
  "network",
  "internal",
  "node_unavailable",
]);

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;

  constructor(code: ApiErrorCode, status: number, message?: string) {
    super(message ?? code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }

  /** Повторять запрос имеет смысл только при сбое транспорта или сервера. */
  get retryable(): boolean {
    return RETRYABLE.has(this.code);
  }

  /**
   * Ключ каталога i18n. Возвращаемый тип — MessageKey без приведения:
   * если в ru.ts не окажется ключа error.<код>, это будет ошибка компиляции.
   */
  messageKey(): MessageKey {
    return `error.${this.code}`;
  }
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(
    "internal",
    0,
    err instanceof Error ? err.message : String(err),
  );
}
